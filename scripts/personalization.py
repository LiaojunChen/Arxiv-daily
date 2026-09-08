"""Explicit multi-interest scoring and globally diverse exploration."""
import time

import zotero_similar as reranker
from subscriptions import matches_author, matches_institution
from zotero_arxiv_daily.recommendation import matched_keywords_for_text, token_jaccard_similarity, mmr_select


def follow_signals(paper, preferences):
    author = any(matches_author(author, followed) for author in paper.get("authors", [])
                 for followed in preferences.get("followed_authors", []))
    institution = any(matches_institution(aff.get("affiliation", "") if isinstance(aff, dict) else aff, followed)
                      for aff in paper.get("affiliations", []) for followed in preferences.get("followed_institutions", []))
    return author, institution


def rank_personalized(papers, profile, zotero=(), diagnostics=None):
    if not papers:
        return []
    interests = profile.get("keywords", [])[:10]
    channels = [(item["term"], max(.01, float(item.get("score", 1))),
                 f"Research on {item['term']}. Find papers whose main contribution advances this research topic.")
                for item in interests if item.get("term")]
    examples = list(profile.get("positive_examples", {}).values())[-8:]
    recent_zotero = sorted(zotero, key=lambda p: str(p.get("added_date", "")), reverse=True)[:8]
    for name, corpus in (("liked_papers", examples), ("zotero", recent_zotero)):
        if corpus:
            query = "Find new research related to these papers of interest:\n" + "\n".join(
                f"{p.get('title', '')}\n{p.get('abstract', '')[:1000]}" for p in corpus)
            channels.append((name, max((c[1] for c in channels), default=1) * .75, query))
    if not channels:
        channels = [("categories", 1, "Research in " + ", ".join(sorted({c for p in papers for c in p.get("categories", [])}))) ]
    positive_channels = list(channels)
    negative_examples = list(profile.get("negative_examples", {}).values())[-4:]
    if profile.get("negative_keywords") and negative_examples:
        channels.append(("negative_examples", 1, "Find papers dominated by these unwanted research directions:\n" +
                         "\n".join(f"{p.get('title', '')}\n{p.get('abstract', '')[:1000]}" for p in negative_examples)))
    documents = [reranker._format_candidate(p) for p in papers]
    scores = {}
    degraded = not bool(reranker.SILICONFLOW_API_KEY)
    failure = None
    if not degraded:
        try:
            for name, _, query in channels:
                values = []
                for start in range(0, len(papers), reranker.SILICONFLOW_BATCH_SIZE):
                    for attempt in range(2):
                        try:
                            values.extend(reranker._cached_rerank(query, documents[start:start + reranker.SILICONFLOW_BATCH_SIZE]))
                            break
                        except RuntimeError:
                            if attempt: raise
                            time.sleep(1)
                scores[name] = values
        except RuntimeError as exc:
            degraded, failure = True, type(exc).__name__
    if degraded:
        # A failure in any channel switches every channel to the same scale.
        scores = {name: [max(float(bool(matched_keywords_for_text(doc, [name]))),
                            token_jaccard_similarity(query, doc)) for doc in documents]
                  for name, _, query in channels}
    weights = {name: weight for name, weight, _ in positive_channels}
    total, highest = sum(weights.values()), max(weights.values())
    preferences = profile.get("subscriptions", {})
    negatives = [item["term"] for item in profile.get("negative_keywords", [])[:10]]
    ranked = []
    for index, paper in enumerate(papers):
        topic_scores = {name: scores[name][index] for name in weights}
        mean = sum(topic_scores[name] * weights[name] for name in weights) / total
        best = max(topic_scores[name] * weights[name] / highest for name in weights)
        semantic = 10 * (.65 * best + .35 * mean)
        text = paper["title"] + "\n" + paper["abstract"]
        negative_matches = matched_keywords_for_text(text, negatives)
        penalty = min(3.0, len(negative_matches) * .75 + .75 * scores.get("negative_examples", [0] * len(papers))[index])
        author_match, institution_match = follow_signals(paper, preferences)
        # Relative, capped boost: following cannot turn zero relevance into a top hit.
        boost = min(1.0, semantic * (.15 * author_match + .10 * institution_match))
        primary_topic = max(topic_scores, key=lambda name: topic_scores[name] * weights[name])
        ranked.append({**paper, "similarity_score": round(max(0, semantic - penalty + boost), 6),
            "semantic_score": semantic, "topic_scores": topic_scores, "primary_topic": primary_topic,
            "follow_boost": boost, "suppressed_keywords": negative_matches,
            "matched_keywords": matched_keywords_for_text(text, [c[0] for c in channels]),
            "source": "interest_profile", "scorer": "keyword" if degraded else reranker.SILICONFLOW_RERANK_MODEL,
            "recommendation_reason": f"Related to {primary_topic}" + ("; followed author/institution" if boost else "")})
    if diagnostics is not None:
        diagnostics.update(scorer="keyword" if degraded else reranker.SILICONFLOW_RERANK_MODEL,
                           degraded=degraded, failure=failure, channels=list(weights), channel_weights=weights)
    return sorted(ranked, key=lambda p: p["similarity_score"], reverse=True)


def select_personalized(ranked, limit=50, exploration_limit=10):
    """No quality cutoff: fill the requested count from eligible unseen papers."""
    if not ranked or limit <= 0:
        return []
    exploration_limit = min(exploration_limit, limit // 5)
    text = lambda p: p["title"] + "\n" + p["abstract"]
    # Numerical floor is selection-only; never alter the displayed relevance.
    score = lambda p: max(1e-9, p["similarity_score"])
    primary = mmr_select(ranked, limit=limit - exploration_limit, score_getter=score, text_getter=text)
    selected = list(primary)
    for p in primary:
        p["recommendation_group"] = "primary"
    ids = {p["arxiv_id"] for p in selected}
    # Require semantic proximity to a real interest channel, plus a topic or
    # vocabulary not already covered by the primary list. A stray keyword is not enough.
    semantic_scores = sorted(p.get("semantic_score", 0) for p in ranked)
    floor = max(semantic_scores[len(ranked) // 2], .25 * semantic_scores[-1])
    primary_topics = {p.get("primary_topic") for p in primary}
    primary_keywords = {k for p in primary for k in p.get("keywords", [])}
    pool = [p for p in ranked if p["arxiv_id"] not in ids and p.get("semantic_score", 0) >= floor
            and p.get("semantic_score", 0) > 0 and not p.get("suppressed_keywords")
            and (p.get("primary_topic") not in primary_topics or
                 len(set(p.get("keywords", [])) - primary_keywords) >= 2)]
    for _ in range(exploration_limit):
        if not pool: break
        # Compare with ALL already selected papers, including the primary group.
        next_paper = max(pool, key=lambda p: .65 * score(p) / max(1e-9, score(ranked[0])) -
                         .35 * max((token_jaccard_similarity(text(p), text(s)) for s in selected), default=0))
        next_paper["recommendation_group"] = "exploration"
        selected.append(next_paper)
        ids.add(next_paper["arxiv_id"])
        pool.remove(next_paper)
    # Keep 50 even when no defensible exploration candidates exist.
    while len(selected) < min(limit, len(ranked)):
        pool = [p for p in ranked if p["arxiv_id"] not in ids]
        next_paper = max(pool, key=lambda p: .65 * score(p) / max(1e-9, score(ranked[0])) -
                         .35 * max((token_jaccard_similarity(text(p), text(s)) for s in selected), default=0))
        next_paper["recommendation_group"] = "primary"
        selected.append(next_paper)
        ids.add(next_paper["arxiv_id"])
    return selected
