"""Small, dependency-free helpers shared by the email and web recommenders.

The project has two delivery surfaces: the scheduled email and the GitHub Pages
dashboard.  They use different candidate fetchers, but must apply the same
interest-profile semantics once candidates have been scored.  Keeping these
operations here avoids silently giving the two surfaces different treatment of
negative feedback or diversity.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from typing import TypeVar


T = TypeVar("T")

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{1,}")
_SIMILARITY_STOPWORDS = {
    "about", "after", "also", "analysis", "approach", "based", "between",
    "data", "from", "into", "method", "model", "models", "paper", "results",
    "study", "that", "their", "these", "this", "using", "with",
}


def normalize_keyword(keyword: str) -> str:
    """Normalize a user/profile keyword without changing its meaning."""
    value = re.sub(r"\s+", " ", str(keyword or "").strip().lower())
    return value.strip(" -_.,;:/()[]{}")


def normalize_keywords(keywords: Sequence[str] | None) -> list[str]:
    """Normalize, de-duplicate, and preserve the order of keyword phrases."""
    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in keywords or []:
        if not isinstance(keyword, str):
            continue
        value = normalize_keyword(keyword)
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def matched_keywords_for_text(text: str, keywords: Sequence[str] | None) -> list[str]:
    """Return profile phrases that are materially represented in ``text``.

    Exact phrase matches are preferred.  For longer phrases, a two-thirds token
    match is also useful because scientific abstracts often insert modifiers
    between a user's keyword terms.
    """
    text_lower = str(text or "").lower()
    matches: list[str] = []
    for keyword in normalize_keywords(keywords):
        tokens = keyword.split()
        if keyword in text_lower:
            matches.append(keyword)
            continue
        if tokens and sum(token in text_lower for token in tokens) / len(tokens) >= 0.67:
            matches.append(keyword)
    return matches


def negative_feedback_penalty(
    text: str,
    suppressed_keywords: Sequence[str] | None,
    *,
    per_keyword: float = 2.0,
) -> tuple[float, list[str]]:
    """Return the bounded score penalty and matched negative-interest phrases."""
    matched = matched_keywords_for_text(text, suppressed_keywords)
    return min(float(per_keyword) * len(matched), 8.0), matched


def recommendation_reason(
    matched_keywords: Sequence[str] | None,
    *,
    group: str | None = None,
    diversity_selected: bool = False,
) -> str:
    """Create a concise, user-visible explanation without exposing raw scores."""
    matched = normalize_keywords(matched_keywords)
    if group == "exploration":
        prefix = "Exploratory match"
    else:
        prefix = "Matches your interests"

    if matched:
        reason = f"{prefix}: {', '.join(matched[:4])}"
    elif group == "exploration":
        reason = "Exploratory pick adjacent to your current interests"
    else:
        reason = "Relevant to your current interest profile"

    if diversity_selected:
        reason += "; selected to keep this issue diverse"
    return reason


def _similarity_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(str(text or ""))
        if token.lower() not in _SIMILARITY_STOPWORDS
    }


def token_jaccard_similarity(left: str, right: str) -> float:
    """A deterministic lightweight similarity suitable for MMR diversification."""
    left_tokens = _similarity_tokens(left)
    right_tokens = _similarity_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def mmr_select(
    items: Sequence[T],
    *,
    limit: int,
    score_getter: Callable[[T], float | None],
    text_getter: Callable[[T], str],
    diversity_lambda: float = 0.65,
) -> list[T]:
    """Select high-relevance items while penalising near-duplicate papers.

    This is maximal marginal relevance (MMR): the first item is the best
    relevance score, while every later item balances relevance against its most
    similar item already selected. Scores are normalized with a small relevance
    floor: a good but slightly lower-scoring distinct paper should be able to
    displace a near-duplicate, while the original score still determines the
    first pick and strongly preferred candidates.
    """
    if limit <= 0 or not items:
        return []

    candidates = list(items)
    if len(candidates) <= limit:
        return candidates

    diversity_lambda = min(1.0, max(0.0, float(diversity_lambda)))
    raw_scores = []
    for item in candidates:
        score = score_getter(item)
        raw_scores.append(float(score) if score is not None and math.isfinite(float(score)) else 0.0)

    low, high = min(raw_scores), max(raw_scores)
    if high - low < 1e-9:
        relevance = [1.0] * len(candidates)
    else:
        # Pure min-max normalization turns the lowest candidate into exactly
        # zero relevance, which makes MMR unable to select a useful distinct
        # paper whenever the top scores are tightly clustered.  The floor is
        # intentional: diversity is a secondary signal, not a zero-quality
        # fallback.
        relevance = [0.5 + 0.5 * (score - low) / (high - low) for score in raw_scores]

    selected_indices: list[int] = []
    available = set(range(len(candidates)))
    while available and len(selected_indices) < limit:
        best_index = -1
        best_value = float("-inf")
        for index in sorted(available):
            redundancy = max(
                (
                    token_jaccard_similarity(
                        text_getter(candidates[index]), text_getter(candidates[selected_index])
                    )
                    for selected_index in selected_indices
                ),
                default=0.0,
            )
            value = diversity_lambda * relevance[index] - (1.0 - diversity_lambda) * redundancy
            if value > best_value:
                best_index = index
                best_value = value
        selected_indices.append(best_index)
        available.remove(best_index)

    return [candidates[index] for index in selected_indices]
