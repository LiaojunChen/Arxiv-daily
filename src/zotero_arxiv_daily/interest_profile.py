from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from .feedback import make_paper_id
from .keyword_extractor import normalize_keyword, normalize_keywords
from .protocol import CorpusPaper, Paper


DEFAULT_KEYWORDS = ["world model", "unified model", "generation model"]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _config_get(config, key: str, default=None):
    value = config.get(key, default)
    return default if value is None else value


class InterestProfile:
    def __init__(
        self,
        state_path: str | Path,
        *,
        default_keywords: list[str] | None = None,
        top_keyword_count: int = 10,
        score_decay: float = 0.95,
        interested_weight: float = 1.0,
        liked_weight: float = 3.0,
        max_feedback_history: int = 200,
    ):
        self.state_path = Path(state_path)
        self.default_keywords = normalize_keywords(default_keywords or DEFAULT_KEYWORDS)
        self.top_keyword_count = int(top_keyword_count)
        self.score_decay = float(score_decay)
        self.interested_weight = float(interested_weight)
        self.liked_weight = float(liked_weight)
        self.max_feedback_history = int(max_feedback_history)
        self.data = self._load_or_initialize()

    @classmethod
    def from_config(cls, config) -> "InterestProfile":
        interest_config = config.interest
        return cls(
            _config_get(interest_config, "state_path", "data/interest_profile.json"),
            default_keywords=list(_config_get(interest_config, "default_keywords", DEFAULT_KEYWORDS)),
            top_keyword_count=int(_config_get(interest_config, "top_keyword_count", 10)),
            score_decay=float(_config_get(interest_config, "score_decay", 0.95)),
            interested_weight=float(_config_get(interest_config, "interested_weight", 1.0)),
            liked_weight=float(_config_get(interest_config, "liked_weight", 3.0)),
            max_feedback_history=int(_config_get(interest_config, "max_feedback_history", 200)),
        )

    def _load_or_initialize(self) -> dict[str, Any]:
        if self.state_path.exists():
            with self.state_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            data.setdefault("version", 1)
            data.setdefault("keywords", [])
            data.setdefault("processed_feedback", [])
            data.setdefault("feedback_history", [])
            data.setdefault("last_run", {})
            self._ensure_default_keywords(data)
            return data

        data = {
            "version": 1,
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "keywords": [],
            "processed_feedback": [],
            "feedback_history": [],
            "last_run": {},
        }
        self._ensure_default_keywords(data)
        return data

    def _ensure_default_keywords(self, data: dict[str, Any]) -> None:
        scores = self._keyword_scores(data)
        base_score = 10.0
        for index, keyword in enumerate(self.default_keywords):
            scores.setdefault(keyword, base_score - index)
        data["keywords"] = self._scores_to_keyword_items(scores)

    def _keyword_scores(self, data: dict[str, Any] | None = None) -> dict[str, float]:
        source = self.data if data is None else data
        scores: dict[str, float] = {}
        for item in source.get("keywords", []):
            if isinstance(item, dict):
                keyword = normalize_keyword(str(item.get("term", "")))
                score = item.get("score", 0.0)
            else:
                keyword = normalize_keyword(str(item))
                score = 1.0
            if keyword:
                scores[keyword] = max(scores.get(keyword, 0.0), float(score))
        return scores

    def _scores_to_keyword_items(self, scores: dict[str, float]) -> list[dict[str, Any]]:
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [
            {
                "term": keyword,
                "score": round(float(score), 4),
            }
            for keyword, score in ranked[: max(self.top_keyword_count * 5, self.top_keyword_count)]
            if score > 0.01
        ]

    def top_keywords(self, limit: int | None = None) -> list[str]:
        limit = self.top_keyword_count if limit is None else int(limit)
        return [item["term"] for item in self.data.get("keywords", [])[:limit]]

    def to_corpus(self, keywords: list[str] | None = None) -> list[CorpusPaper]:
        selected = normalize_keywords(keywords or self.top_keywords())
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return [
            CorpusPaper(
                title=f"User interest keyword: {keyword}",
                abstract=(
                    f"The user is interested in papers about {keyword}. "
                    f"Rank candidate papers higher when their title, abstract, contribution, or extracted keywords match {keyword}."
                ),
                added_date=now - timedelta(minutes=index),
                paths=["interest-profile"],
            )
            for index, keyword in enumerate(selected)
        ]

    def apply_feedback(self, feedback_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not feedback_items:
            return []

        scores = {keyword: score * self.score_decay for keyword, score in self._keyword_scores().items()}
        processed = set(str(item) for item in self.data.get("processed_feedback", []))
        last_papers = self.data.get("last_run", {}).get("papers", {})
        applied: list[dict[str, Any]] = []

        for item in feedback_items:
            feedback_key = self._feedback_key(item)
            if feedback_key in processed:
                continue

            paper_id = str(item.get("paper_id"))
            paper = last_papers.get(paper_id)
            processed.add(feedback_key)
            if not paper:
                logger.warning(f"Feedback for unknown paper_id {paper_id} was marked processed but not applied.")
                continue

            action = item.get("action")
            weight = self.liked_weight if action == "like" else self.interested_weight
            keywords = normalize_keywords(paper.get("keywords", []) + paper.get("matched_keywords", []))
            if not keywords:
                keywords = normalize_keywords(_title_phrases(paper.get("title", "")))

            for index, keyword in enumerate(keywords):
                scores[keyword] = scores.get(keyword, 0.0) + weight / (1.0 + index * 0.35)

            record = {
                "processed_at": utcnow_iso(),
                "feedback_key": feedback_key,
                "paper_id": paper_id,
                "action": action,
                "paper_title": paper.get("title"),
                "keywords": keywords,
                "issue_url": item.get("issue_url"),
            }
            applied.append(record)

        if applied:
            history = self.data.get("feedback_history", []) + applied
            self.data["feedback_history"] = history[-self.max_feedback_history :]
            self.data["keywords"] = self._scores_to_keyword_items(scores)
            self.data["processed_feedback"] = sorted(processed)[-1000:]
            self.data["updated_at"] = utcnow_iso()
            logger.info(f"Applied {len(applied)} feedback item(s) to the interest profile.")

        return applied

    def set_last_run(
        self,
        *,
        run_id: str,
        papers: list[Paper],
        exploration_keywords: list[str],
    ) -> None:
        paper_map: dict[str, Any] = {}
        for paper in papers:
            paper_id = paper.paper_id or make_paper_id(paper)
            paper.paper_id = paper_id
            paper_map[paper_id] = {
                "title": paper.title,
                "url": paper.url,
                "pdf_url": paper.pdf_url,
                "score": paper.score,
                "keywords": paper.keywords,
                "matched_keywords": paper.matched_keywords,
                "recommendation_group": paper.recommendation_group,
            }

        self.data["last_run"] = {
            "run_id": run_id,
            "generated_at": utcnow_iso(),
            "top_keywords": self.top_keywords(),
            "exploration_keywords": exploration_keywords,
            "papers": paper_map,
        }
        self.data["updated_at"] = utcnow_iso()

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def _feedback_key(self, item: dict[str, Any]) -> str:
        if item.get("issue_number") is not None:
            return f"issue:{item['issue_number']}"
        return f"{item.get('run_id')}:{item.get('paper_id')}:{item.get('action')}"


def _title_phrases(title: str) -> list[str]:
    words = [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", title or "")]
    phrases: list[str] = []
    for n in (3, 2):
        for i in range(0, max(0, len(words) - n + 1)):
            phrases.append(" ".join(words[i:i + n]))
    return phrases[:6]


def guess_exploration_keywords(
    *,
    top_keywords: list[str],
    candidates: list[Paper],
    feedback_history: list[dict[str, Any]],
    openai_client,
    llm_config,
    max_keywords: int = 10,
    use_llm: bool = True,
) -> list[str]:
    if use_llm:
        guessed = _guess_exploration_keywords_with_llm(
            top_keywords=top_keywords,
            candidates=candidates,
            feedback_history=feedback_history,
            openai_client=openai_client,
            llm_config=llm_config,
            max_keywords=max_keywords,
        )
        if guessed:
            return guessed

    return fallback_exploration_keywords(top_keywords, candidates, max_keywords=max_keywords)


def _guess_exploration_keywords_with_llm(
    *,
    top_keywords: list[str],
    candidates: list[Paper],
    feedback_history: list[dict[str, Any]],
    openai_client,
    llm_config,
    max_keywords: int,
) -> list[str]:
    candidate_counter = Counter()
    for paper in candidates[:120]:
        for keyword in paper.keywords:
            candidate_counter[normalize_keyword(keyword)] += 1
    observed_keywords = [keyword for keyword, _ in candidate_counter.most_common(40)]
    recent_feedback = feedback_history[-20:]

    prompt = (
        "Suggest adjacent research keywords for exploratory paper recommendations.\n"
        f"Current top keywords: {top_keywords}\n"
        f"Recent feedback: {recent_feedback}\n"
        f"Candidate-paper keywords observed today: {observed_keywords}\n\n"
        f"Return a JSON array of at most {max_keywords} short keyword phrases. "
        "Avoid duplicates and avoid broad generic phrases."
    )
    try:
        response = openai_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You suggest concise scientific search keywords and return only valid JSON.",
                },
                {"role": "user", "content": prompt[:8000]},
            ],
            **llm_config.get("generation_kwargs", {}),
        )
        content = response.choices[0].message.content
    except Exception as exc:
        logger.warning(f"LLM exploration keyword guess failed: {exc}")
        return []

    match = re.search(r"\[.*\]", content or "", flags=re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    return _dedupe_exploration_keywords(parsed, top_keywords, max_keywords=max_keywords)


def fallback_exploration_keywords(
    top_keywords: list[str],
    candidates: list[Paper],
    *,
    max_keywords: int = 10,
) -> list[str]:
    counter: Counter[str] = Counter()
    for paper in candidates:
        boost = max(float(paper.score or 0.0), 1.0)
        for keyword in paper.keywords:
            keyword = normalize_keyword(keyword)
            if keyword:
                counter[keyword] += boost

    return _dedupe_exploration_keywords(
        [keyword for keyword, _ in counter.most_common(max_keywords * 5)],
        top_keywords,
        max_keywords=max_keywords,
    )


def _dedupe_exploration_keywords(
    keywords: list[Any],
    top_keywords: list[str],
    *,
    max_keywords: int,
) -> list[str]:
    top = normalize_keywords(top_keywords)
    selected: list[str] = []
    for item in keywords:
        keyword = normalize_keyword(str(item))
        if not keyword:
            continue
        if keyword in selected:
            continue
        if any(keyword == current or keyword in current or current in keyword for current in top):
            continue
        selected.append(keyword)
        if len(selected) >= max_keywords:
            break
    return selected
