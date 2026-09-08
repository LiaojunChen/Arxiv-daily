from __future__ import annotations

import math
import re
from collections import Counter

from .recommendation import paper_keywords

from .protocol import Paper
from .recommendation import matched_keywords_for_text, phrase_matches


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
_EXTRA_STOPWORDS = {
    "abstract",
    "analysis",
    "approach",
    "based",
    "benchmark",
    "data",
    "datasets",
    "demonstrate",
    "experiments",
    "framework",
    "method",
    "methods",
    "novel",
    "paper",
    "performance",
    "present",
    "propose",
    "results",
    "show",
    "shows",
    "state",
    "study",
    "task",
    "tasks",
    "training",
    "using",
}
_STOPWORDS = set("a an the of and or to in on for is are we our it as by be can new more".split()) | _EXTRA_STOPWORDS


def normalize_keyword(keyword: str) -> str:
    keyword = re.sub(r"\s+", " ", keyword.strip().lower())
    keyword = keyword.strip(" -_.,;:/()[]{}")
    return keyword


def normalize_keywords(keywords: list[str] | tuple[str, ...] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for keyword in keywords or []:
        if not isinstance(keyword, str):
            continue
        item = normalize_keyword(keyword)
        if item and item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _paper_text(paper: Paper) -> str:
    return f"{paper.title or ''}\n{paper.abstract or ''}".strip()


def _valid_phrase(phrase: str) -> bool:
    phrase = normalize_keyword(phrase)
    if not phrase or len(phrase) > 70:
        return False
    tokens = _WORD_RE.findall(phrase)
    if not tokens:
        return False
    if all(token.lower() in _STOPWORDS for token in tokens):
        return False
    if len(tokens) == 1 and (tokens[0].lower() in _STOPWORDS or len(tokens[0]) < 4):
        return False
    return True


def extract_keywords_from_text(text: str, max_keywords: int = 6) -> list[str]:
    tokens = [token.lower() for token in _WORD_RE.findall(text or "")]
    tokens = [token for token in tokens if token not in _STOPWORDS]
    if not tokens:
        return []

    counts: Counter[str] = Counter()
    for n in (3, 2, 1):
        for i in range(0, max(0, len(tokens) - n + 1)):
            phrase = " ".join(tokens[i:i + n])
            if _valid_phrase(phrase):
                counts[phrase] += 1 + (0.4 * (n - 1))

    return [phrase for phrase, _ in counts.most_common(max_keywords)]


def assign_keywords_to_papers(papers: list[Paper], max_keywords: int = 6) -> None:
    for paper, keywords in zip(papers, paper_keywords([_paper_text(p) for p in papers], max_keywords)):
        paper.keywords = keywords


def matched_keywords_for_paper(paper: Paper, keywords: list[str]) -> list[str]:
    text = f"{paper.title or ''} {paper.abstract or ''} {' '.join(paper.keywords)}".lower()
    return matched_keywords_for_text(text, keywords)


def keyword_overlap_score(paper: Paper, keywords: list[str]) -> float:
    normalized_keywords = normalize_keywords(keywords)
    if not normalized_keywords:
        return 0.0

    text = f"{paper.title or ''} {paper.abstract or ''}".lower()
    paper_keyword_text = " ".join(paper.keywords).lower()
    score = 0.0

    for keyword in normalized_keywords:
        tokens = keyword.split()
        if not tokens:
            continue
        keyword_score = 0.0
        if phrase_matches(text, keyword):
            keyword_score += 3.0
        if phrase_matches(paper_keyword_text, keyword):
            keyword_score += 2.0
        overlap = sum(phrase_matches(text, token) for token in tokens) / len(tokens)
        keyword_score += 2.0 * overlap
        score += min(keyword_score, 5.0)

    scaled = (score / (len(normalized_keywords) * 5.0)) * 10.0
    return round(min(10.0, math.sqrt(max(scaled, 0.0) / 10.0) * 10.0), 3)
