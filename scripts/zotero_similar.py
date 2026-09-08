"""
Zotero-based similarity via SiliconFlow LLM Reranker.

Fetches user's Zotero library to build an interest profile (query),
then sends ArXiv candidates to SiliconFlow's /v1/rerank API for
relevance scoring using Qwen3-Reranker-0.6B.

This matches the approach used in the original zotero-arxiv-daily project.
"""

import json
import sys
import urllib.request
import urllib.error
import requests
import math
import time
import os
from pipeline_state import fingerprint, read_json, write_json
from datetime import datetime, timezone
from pathlib import Path
from config import (
    ZOTERO_ID,
    ZOTERO_KEY,
    ZOTERO_API_BASE,
    MAX_PAPER_NUM,
    SILICONFLOW_API_KEY,
    SILICONFLOW_RERANK_URL,
    SILICONFLOW_RERANK_MODEL,
    SILICONFLOW_BATCH_SIZE,
)

# ``daily-fetch.yml`` installs only ``scripts/requirements.txt``.  The shared
# selection helpers are intentionally stdlib-only, so adding src to the path
# lets the dashboard apply the same negative-feedback and MMR semantics as
# email without pulling in the full mail runtime.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zotero_arxiv_daily.recommendation import (  # noqa: E402
    matched_keywords_for_text,
    mmr_select,
    negative_feedback_penalty,
    recommendation_reason,
    token_jaccard_similarity,
)

ZOTERO_TIMEOUT = 15


def _zotero_headers() -> dict:
    return {"Zotero-API-Key": ZOTERO_KEY, "User-Agent": "arXivDaily/1.0"}


def fetch_zotero_items() -> list[dict]:
    """
    Fetch all items from the user's Zotero library.
    Returns a list of items with title, abstract, added_date, and collections.
    """
    if not ZOTERO_ID or not ZOTERO_KEY:
        print("[WARN] ZOTERO_ID or ZOTERO_KEY not set, skipping Zotero fetch.")
        return []

    all_items = []
    url = f"{ZOTERO_API_BASE}/users/{ZOTERO_ID}/items"
    params = {"limit": 100, "format": "json"}

    while url:
        try:
            resp = requests.get(
                url,
                headers=_zotero_headers(),
                params=params if "?" not in url else None,
                timeout=ZOTERO_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            all_items.extend(data)

            # Pagination via Link header
            url = None
            link_header = resp.headers.get("Link")
            if link_header:
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        url = part.split(";")[0].strip(" <>")
                        break
        except requests.RequestException as e:
            print(f"[ERROR] Zotero API request failed: {e}")
            break

    # Extract papers with title
    papers = []
    for item in all_items:
        data = item.get("data", {})
        title = data.get("title", "").strip()
        abstract = data.get("abstractNote", "").strip() or data.get("abstract", "").strip()
        if title:
            added_str = data.get("dateAdded", "")
            try:
                added_date = datetime.fromisoformat(added_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                added_date = datetime.min.replace(tzinfo=timezone.utc)

            papers.append(
                {
                    "title": title,
                    "abstract": abstract,
                    "added_date": added_date,
                }
            )

    print(f"[INFO] Fetched {len(papers)} items from Zotero library")
    return papers


def _build_interest_query(zotero_papers: list[dict]) -> str:
    """
    Build a query string from the user's Zotero library papers.
    This is sent as the `query` to the rerank API, representing user interests.
    Follows the same logic as SiliconFlowReranker._build_interest_query().
    """
    max_papers = 30
    max_chars = 12000

    # Sort by added_date descending (newest first)
    sorted_papers = sorted(
        zotero_papers, key=lambda p: p.get("added_date", datetime.min).replace(tzinfo=timezone.utc), reverse=True
    )

    intro = (
        "The following papers are from the user's Zotero library and represent recent "
        "research interests. Rank new candidate papers by relevance to these interests.\n\n"
    )
    parts = [intro]

    for paper in sorted_papers[:max_papers]:
        text = (
            f"Title: {paper['title']}\n"
            f"Abstract: {paper['abstract']}\n\n"
        )
        if sum(len(p) for p in parts) + len(text) > max_chars:
            remaining = max_chars - sum(len(p) for p in parts)
            if remaining > 0:
                parts.append(text[:remaining].rstrip())
            break
        parts.append(text)

    query = "".join(parts).strip()
    print(f"[INFO] Built interest query: {len(query)} chars")
    return query


def _build_keyword_interest_query(
    interest_keywords: list[str],
    suppressed_keywords: list[str],
) -> str:
    """Build the same positive/negative profile query used for web ranking."""
    query = (
        "The user has the following positive research interests. Rank papers by "
        "relevance and usefulness to these interests:\n"
        + ", ".join(interest_keywords)
    )
    if suppressed_keywords:
        query += (
            "\n\nThe user explicitly wants fewer papers about these themes. "
            "Rank papers dominated by them lower unless they strongly match a positive interest:\n"
            + ", ".join(suppressed_keywords)
        )
    return query


def _format_candidate(paper: dict) -> str:
    """Format a candidate paper as a document string for the rerank API."""
    max_chars = 4000
    authors = ", ".join(paper.get("authors", [])) or "Unknown"
    document = (
        f"Title: {paper['title']}\n"
        f"Authors: {authors}\n"
        f"Abstract: {paper['abstract']}"
    )
    return document[:max_chars].rstrip()


def _rerank_batch(query: str, documents: list[str]) -> list[float]:
    """
    Call SiliconFlow /v1/rerank API for one batch of documents.
    Returns a list of relevance_score values, one per document (same order).
    """
    payload = {
        "model": SILICONFLOW_RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": len(documents),
        "return_documents": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SILICONFLOW_RERANK_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"SiliconFlow rerank request failed with HTTP {e.code}: {body[:500]}"
        ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"SiliconFlow rerank request failed: {e}") from e

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"SiliconFlow rerank response is not valid JSON: {body[:500]}") from e

    results = parsed.get("results") if isinstance(parsed, dict) else None
    if not isinstance(results, list):
        raise RuntimeError(f"SiliconFlow rerank response missing results list: {parsed}")

    # Build ordered list matching the documents order
    scores = [0.0] * len(documents)
    seen = set()
    try:
        for item in results:
            idx = item["index"]
            score = float(item["relevance_score"])
            if type(idx) is not int or idx not in range(len(documents)) or idx in seen or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("invalid/duplicate rerank result")
            seen.add(idx)
            scores[idx] = score
        if len(seen) != len(documents):
            raise ValueError("incomplete rerank results")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid rerank response: {exc}") from exc

    return scores


def compute_similarity(
    zotero_papers: list[dict],
    arxiv_papers: list[dict],
    top_n: int = None,
    *,
    interest_keywords: list[str] | None = None,
    suppressed_keywords: list[str] | None = None,
    keyword_weights: dict[str, float] | None = None,
    diagnostics: dict | None = None,
) -> list[dict]:
    """
    Use SiliconFlow LLM Reranker to score ArXiv papers by relevance to
    the user's Zotero library (interest profile).

    Returns ArXiv papers sorted by relevance score (descending), top N.
    """
    if top_n is None:
        top_n = MAX_PAPER_NUM

    if not arxiv_papers:
        print("[WARN] No ArXiv papers to rank.")
        return []

    interest_keywords = interest_keywords or []
    suppressed_keywords = suppressed_keywords or []
    if interest_keywords:
        query = _build_keyword_interest_query(interest_keywords, suppressed_keywords)
        if keyword_weights:
            query += "\nInterest weights (higher is more important): " + json.dumps(keyword_weights, sort_keys=True)
    else:
        query = _build_interest_query(zotero_papers or [])

    if not zotero_papers and not interest_keywords:
        # Fallback: use a generic query based on paper categories
        all_cats = set()
        for p in arxiv_papers:
            all_cats.update(p.get("categories", []))
        query = (
            "The user is interested in papers from the following research areas: "
            + ", ".join(sorted(all_cats)[:10])
            + ". Rank new candidate papers by relevance to these areas."
        )
        print(f"[INFO] No Zotero items, using category-based query.")

    # Rerank all ArXiv papers in batches.  If the optional rerank secret is
    # absent, a deterministic keyword score still makes the profile useful.
    all_scores = [0.0] * len(arxiv_papers)
    failed = not bool(SILICONFLOW_API_KEY)
    failed_batches = 0
    if SILICONFLOW_API_KEY:
        total_batches = (len(arxiv_papers) + SILICONFLOW_BATCH_SIZE - 1) // SILICONFLOW_BATCH_SIZE
        for batch_idx in range(total_batches):
            start = batch_idx * SILICONFLOW_BATCH_SIZE
            end = min(start + SILICONFLOW_BATCH_SIZE, len(arxiv_papers))
            batch = arxiv_papers[start:end]
            documents = [_format_candidate(p) for p in batch]

            print(f"[INFO] Reranking batch {batch_idx + 1}/{total_batches} ({len(batch)} papers)...")
            for attempt in range(2):
                try:
                    scores = _cached_rerank(query, documents)
                    all_scores[start:end] = scores
                    break
                except RuntimeError as e:
                    if attempt == 0:
                        time.sleep(1)
                    else:
                        print(f"[ERROR] Rerank batch {batch_idx + 1} failed: {e}")
                        failed = True
                        failed_batches += 1
    if failed and interest_keywords:
        print("[WARN] Reranker unavailable; using keyword-profile ranking for the entire run.")
        weights = {term: max(0.0, float((keyword_weights or {}).get(term, 1))) for term in interest_keywords}
        for index, paper in enumerate(arxiv_papers):
            text = f"{paper.get('title', '')}\n{paper.get('abstract', '')}"
            matched = matched_keywords_for_text(text, interest_keywords)
            all_scores[index] = sum(weights[term] for term in matched) / max(1e-9, sum(weights.values()))
    elif failed:
        all_scores = [token_jaccard_similarity(query, _format_candidate(p)) for p in arxiv_papers]

    if diagnostics is not None:
        diagnostics.update(scorer="keyword" if failed else SILICONFLOW_RERANK_MODEL,
                           degraded=failed, failed_batches=failed_batches)

    # Attach scores and sort
    score_scale = 10.0
    scored = []
    for i, paper in enumerate(arxiv_papers):
        text = f"{paper.get('title', '')}\n{paper.get('abstract', '')}"
        matched = matched_keywords_for_text(text, interest_keywords)
        penalty, suppressed = negative_feedback_penalty(text, suppressed_keywords, per_keyword=2.0)
        score = max(0.0, all_scores[i] * score_scale - penalty)
        item = {
            **paper,
            "similarity_score": round(score, 4),
            "source": "interest_profile" if interest_keywords else "zotero_similar",
            "scorer": "keyword" if failed else SILICONFLOW_RERANK_MODEL,
        }
        if interest_keywords:
            item["matched_keywords"] = matched
            item["suppressed_keywords"] = suppressed
            item["recommendation_reason"] = recommendation_reason(
                matched,
                diversity_selected=True,
            )
        scored.append(item)

    scored.sort(key=lambda x: x["similarity_score"], reverse=True)

    candidate_pool = scored[: max(top_n * 5, top_n)]
    result = mmr_select(
        candidate_pool,
        limit=top_n,
        score_getter=lambda paper: paper.get("similarity_score"),
        text_getter=lambda paper: f"{paper.get('title', '')}\n{paper.get('abstract', '')}",
        diversity_lambda=0.65,
    )
    max_score = result[0]["similarity_score"] if result else "N/A"
    print(f"[INFO] Top {len(result)} diversified recommendations (max score: {max_score})")
    return result


def _cached_rerank(query, documents):
    path = os.environ.get("RERANK_CACHE_PATH")
    if not path:
        return _rerank_batch(query, documents)
    now = time.time()
    cache = {key: value for key, value in read_json(path).items() if value.get("expires_at", 0) > now}
    keys = [fingerprint([SILICONFLOW_RERANK_MODEL, query, doc]) for doc in documents]
    missing = [i for i, key in enumerate(keys) if key not in cache]
    if missing:
        scores = _rerank_batch(query, [documents[i] for i in missing])
        for i, score in zip(missing, scores, strict=True):
            cache[keys[i]] = {"score": score, "expires_at": now + 30 * 86400}
        write_json(path, cache)
    return [cache[key]["score"] for key in keys]
