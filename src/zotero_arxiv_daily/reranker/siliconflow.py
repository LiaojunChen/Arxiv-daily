import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from loguru import logger

from .base import BaseReranker, register_reranker
from ..protocol import CorpusPaper, Paper


@register_reranker("siliconflow")
class SiliconFlowReranker(BaseReranker):
    """Rerank candidates through SiliconFlow's /v1/rerank API."""

    def rerank(self, candidates: list[Paper], corpus: list[CorpusPaper]) -> list[Paper]:
        if not candidates:
            return []

        query = self._build_interest_query(corpus)
        batch_size = int(self._config_value("batch_size", 64))
        score_scale = float(self._config_value("score_scale", 10.0))
        ranked: list[Paper] = []

        logger.info(
            f"Reranking {len(candidates)} candidate papers with SiliconFlow "
            f"model {self._config_value('model', None)}"
        )

        for start in range(0, len(candidates), batch_size):
            batch = candidates[start:start + batch_size]
            documents = [self._format_candidate(paper) for paper in batch]
            scores_by_index = self._rerank_batch(query, documents)

            for index, paper in enumerate(batch):
                score = scores_by_index.get(index)
                if score is None:
                    logger.warning(f"SiliconFlow rerank did not return a score for batch index {index}")
                    score = 0.0
                paper.score = score * score_scale
                ranked.append(paper)

        return sorted(ranked, key=lambda paper: paper.score, reverse=True)

    def get_similarity_score(self, s1: list[str], s2: list[str]):
        raise NotImplementedError("SiliconFlowReranker uses direct rerank scores, not a similarity matrix.")

    def _config_value(self, key: str, default):
        value = self.config.reranker.siliconflow.get(key)
        return default if value is None else value

    def _build_interest_query(self, corpus: list[CorpusPaper]) -> str:
        max_papers = int(self._config_value("max_query_papers", 30))
        max_chars = int(self._config_value("max_query_chars", 12000))
        sorted_corpus = sorted(corpus, key=lambda paper: paper.added_date, reverse=True)

        intro = (
            "The following papers are from the user's Zotero library and represent recent "
            "research interests. Rank new candidate papers by relevance to these interests.\n\n"
        )
        parts = [intro]

        for paper in sorted_corpus[:max_papers]:
            paths = ", ".join(paper.paths) if paper.paths else "Unknown"
            text = (
                f"Title: {paper.title}\n"
                f"Collections: {paths}\n"
                f"Abstract: {paper.abstract}\n\n"
            )
            if sum(len(part) for part in parts) + len(text) > max_chars:
                remaining = max_chars - sum(len(part) for part in parts)
                if remaining > 0:
                    parts.append(text[:remaining].rstrip())
                break
            parts.append(text)

        return "".join(parts).strip()

    def _format_candidate(self, paper: Paper) -> str:
        max_chars = int(self._config_value("max_document_chars", 4000))
        authors = ", ".join(paper.authors) if paper.authors else "Unknown"
        document = (
            f"Title: {paper.title}\n"
            f"Authors: {authors}\n"
            f"Abstract: {paper.abstract}"
        )
        return document[:max_chars].rstrip()

    def _rerank_batch(self, query: str, documents: list[str]) -> dict[int, float]:
        key = self._config_value("key", None)
        if not key:
            raise ValueError("config.reranker.siliconflow.key must be set to use SiliconFlow rerank.")

        url = self._config_value("url", "https://api.siliconflow.cn/v1/rerank")
        model = self._config_value("model", "Qwen/Qwen3-Reranker-0.6B")
        timeout = float(self._config_value("timeout", 60))
        instruction = self._config_value("instruction", None)

        payload = {
            "model": model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "return_documents": False,
        }
        if instruction:
            payload["instruction"] = instruction

        data = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"SiliconFlow rerank request failed with HTTP {exc.code}: {body[:500]}") from exc
        except URLError as exc:
            raise RuntimeError(f"SiliconFlow rerank request failed: {exc}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SiliconFlow rerank response is not valid JSON: {body[:500]}") from exc

        results = parsed.get("results")
        if not isinstance(results, list):
            raise RuntimeError(f"SiliconFlow rerank response missing results list: {parsed}")

        scores: dict[int, float] = {}
        for item in results:
            try:
                index = int(item["index"])
                score = float(item["relevance_score"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Invalid SiliconFlow rerank result item: {item}") from exc
            scores[index] = score

        return scores
