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
from collections import Counter
from collections.abc import Callable, Sequence
from typing import TypeVar


T = TypeVar("T")


def canonical_arxiv_id(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/", "", value)
    value = re.sub(r"^(?:oai:arXiv.org:|ar[Xx]iv:)", "", value)
    value = re.sub(r"(?:\.pdf)?(?:[?#].*)?$", "", value)
    return re.sub(r"v\d+$", "", value)


def paper_keywords(documents: Sequence[str], limit: int = 6) -> list[list[str]]:
    """Corpus-weighted contiguous phrases, independent of the user's interests."""
    stop = _SIMILARITY_STOPWORDS | set("a an the of and or to in on for is are we our it as by be can new more that this these those learning learned propose proposed presents use via from than not has have was were will how which at its each both such their they all only into over under without across".split())
    counts = []
    for text in documents:
        counter = Counter()
        for sentence in re.split(r"[\n.!?;:]", text.lower()):
            tokens = re.findall(r"[a-z][a-z0-9-]{1,}", sentence)
            for n in (1, 2, 3):
                for i in range(len(tokens) - n + 1):
                    words = tokens[i:i+n]
                    if any(word in stop for word in words):
                        continue
                    counter[" ".join(words)] += 1
        counts.append(counter)
    df = Counter(term for counter in counts for term in counter)
    output = []
    for counter in counts:
        ranked = sorted(counter, key=lambda term: (-(1 + math.log(counter[term])) * (1 + math.log((1 + len(documents)) / (1 + df[term]))) * (1 + .4 * (len(term.split()) - 1)), term))
        selected = []
        for term in ranked:
            if not any(set(term.split()) <= set(existing.split()) for existing in selected):
                selected.append(term)
            if len(selected) >= limit:
                break
        output.append(selected)
    return output

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
        if phrase_matches(text_lower, keyword):
            matches.append(keyword)
            continue
        if len(tokens) >= 3 and sum(phrase_matches(text_lower, token) for token in tokens) / len(tokens) >= 0.67:
            matches.append(keyword)
    return matches


def phrase_matches(text: str, phrase: str) -> bool:
    """Match complete Latin words; CJK phrases may occur without spaces."""
    phrase = normalize_keyword(phrase)
    if not phrase:
        return False
    pattern = r"[\s-]+".join(re.escape(part) for part in phrase.split())
    if re.fullmatch(r"[a-z]{4,}", phrase.split()[-1]) and not phrase.endswith("s"):
        pattern += "s?"
    left = r"(?<![\w])" if phrase[0].isascii() and phrase[0].isalnum() else ""
    right = r"(?![\w])" if phrase[-1].isascii() and phrase[-1].isalnum() else ""
    return re.search(left + pattern + right, str(text).lower()) is not None


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

    # Unknown/zero relevance must not become eligible merely through diversity.
    candidates = [item for item in items if score_getter(item) is not None
                  and math.isfinite(float(score_getter(item))) and float(score_getter(item)) > 0]
    if not candidates:
        return []
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
    tokens = [_similarity_tokens(text_getter(item)) for item in candidates]
    redundancy_scores = [0.0] * len(candidates)
    available = set(range(len(candidates)))
    while available and len(selected_indices) < limit:
        best_index = -1
        best_value = float("-inf")
        for index in sorted(available):
            redundancy = redundancy_scores[index]
            value = diversity_lambda * relevance[index] - (1.0 - diversity_lambda) * redundancy
            if value > best_value:
                best_index = index
                best_value = value
        selected_indices.append(best_index)
        available.remove(best_index)
        for index in available:
            union = tokens[index] | tokens[best_index]
            similarity = len(tokens[index] & tokens[best_index]) / len(union) if union else 0.0
            redundancy_scores[index] = max(redundancy_scores[index], similarity)

    return [candidates[index] for index in selected_indices]
