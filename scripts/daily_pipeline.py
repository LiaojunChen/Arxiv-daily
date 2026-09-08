"""Generate a single public snapshot for Pages and email, including all candidates."""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from zotero_arxiv_daily.recommendation import canonical_arxiv_id, paper_keywords, mmr_select, matched_keywords_for_text
from pipeline_state import fingerprint, read_json, write_json
from config import MAX_PAPER_NUM, ARXIV_QUERY, load_user_config, get_followed_authors, get_followed_institutions
from arxiv_fetcher import get_latest_papers, filter_by_authors, filter_by_institutions
from hf_fetcher import fetch_hf_daily_papers
from affiliation_extractor import enrich_affiliations_for_display_papers
from interest_state import load_interest_state, load_interest_weights
from zotero_similar import compute_similarity, fetch_zotero_items


def merge_candidates(groups):
    papers = {}
    for group in groups:
        for raw in group:
            key = canonical_arxiv_id(raw.get("arxiv_id", ""))
            if not key:
                continue
            paper = {**raw, "arxiv_id": key}
            previous = papers.get(key, {})
            for field in ("authors", "affiliations", "abstract", "categories"):
                if field == "affiliations" and previous.get("version") != paper.get("version") and paper.get("version"):
                    continue
                if not paper.get(field) and previous.get(field):
                    paper[field] = previous[field]
            paper["sources"] = sorted(set(previous.get("sources", [])) | {raw.get("source", "arxiv")})
            papers[key] = {**previous, **paper}
    return list(papers.values())


def generate():
    from fetch_papers import output_result, _validate_display_data
    load_user_config(ROOT / "data/config.json")
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    profile_path = Path(os.environ.get("INTEREST_PROFILE_PATH") or ROOT / "data/interest_profile.json")
    cache_dir = Path(os.environ.get("PIPELINE_CACHE_DIR") or ROOT / "data/cache")
    source_errors = {}
    def fetch_source(name, fetch):
        try:
            return fetch()
        except Exception as exc:
            source_errors[name] = type(exc).__name__
            print(f"[WARN] {name} source failed: {exc}")
            return []
    hf = fetch_source("hf", fetch_hf_daily_papers)
    rss = fetch_source("arxiv", lambda: get_latest_papers(ARXIV_QUERY))
    for paper in rss:
        paper["source_date"] = today
    current = merge_candidates([hf, rss])
    _validate_display_data([], [], current)
    for paper in current:
        paper.setdefault("source_date", today)
    cutoff = (now.date() - timedelta(days=7)).isoformat()
    previous = [p for p in read_json(cache_dir / "candidates.json", []) if p.get("source_date", "") >= cutoff]
    candidates = merge_candidates([previous, current])
    candidates.sort(key=lambda p: p.get("source_date", ""), reverse=True)
    candidates.sort(key=lambda p: p.get("affiliation_status") == "unresolved")
    enrich_affiliations_for_display_papers([candidates], cache_path=cache_dir / "affiliations.json",
        budget_seconds=float(os.environ.get("AFFILIATION_BUDGET_SECONDS") or 900))
    for paper, keywords in zip(candidates, paper_keywords([f"{p['title']}\n{p['abstract']}" for p in candidates])):
        paper["keywords"] = keywords
    by_id = {p["arxiv_id"]: p for p in candidates}
    current = [by_id[p["arxiv_id"]] for p in current]
    hf = [{**by_id[canonical_arxiv_id(p["arxiv_id"])], "source": "huggingface"} for p in hf]
    interests, suppressed = load_interest_state(profile_path)
    weights = load_interest_weights(profile_path)
    diagnostics = {}
    os.environ["RERANK_CACHE_PATH"] = str(cache_dir / "rerank.json")
    # Score all current candidates before selecting; subscription search is independent.
    ranked = compute_similarity([] if interests else fetch_zotero_items(), current,
        top_n=len(current), interest_keywords=interests, suppressed_keywords=suppressed,
        keyword_weights=weights, diagnostics=diagnostics)
    seen = read_json(cache_dir / "recommended.json")
    for paper in ranked:
        date = seen.get(paper["arxiv_id"], "")
        if cutoff <= date < today:
            paper["similarity_score"] *= .5
            paper["previously_recommended"] = True
    ranked.sort(key=lambda p: p["similarity_score"], reverse=True)
    select = lambda papers, n: mmr_select(papers, limit=n,
        score_getter=lambda p: p["similarity_score"], text_getter=lambda p: p["title"] + "\n" + p["abstract"])
    # Explicit exploration quota within the same total delivery count.
    exploration_count = min(MAX_PAPER_NUM // 5, int(os.environ.get("EXPLORATION_PAPER_COUNT") or 10))
    primary = select(ranked, max(0, MAX_PAPER_NUM - exploration_count))
    ids = {p["arxiv_id"] for p in primary}
    adjacent = [p for p in ranked if p["arxiv_id"] not in ids and
        any(term not in interests for term in p.get("keywords", [])) and not matched_keywords_for_text(p["abstract"], suppressed)]
    exploration = select(adjacent, exploration_count)
    for paper in primary:
        paper["recommendation_group"] = "primary"
    for paper in exploration:
        paper["recommendation_group"] = "exploration"
    selected = primary + exploration
    # Use remaining relevant results when the exploration quota cannot be filled.
    selected_ids = {p["arxiv_id"] for p in selected}
    for paper in select([p for p in ranked if p["arxiv_id"] not in selected_ids], MAX_PAPER_NUM - len(selected)):
        paper["recommendation_group"] = "primary"
        selected.append(paper)
    followed = merge_candidates([filter_by_authors(candidates), filter_by_institutions(candidates)])
    profile_version = fingerprint([interests, suppressed, weights])[:16]
    run_id = "daily-" + fingerprint([today, profile_version, selected, candidates])[:24]
    result = output_result(selected, followed, hf, candidate_papers=candidates, metadata={
        "run_id": run_id, "profile_version": profile_version, "top_keywords": interests,
        "exploration_keywords": sorted({k for p in exploration for k in p.get("keywords", []) if k not in interests}),
        "subscriptions": {"followed_authors": get_followed_authors(), "followed_institutions": get_followed_institutions()},
        "pipeline_status": {"arxiv": "ok" if rss else "empty_or_unavailable", "hf": "ok" if hf else "empty_or_unavailable",
            "source_errors": source_errors,
            "ranking": diagnostics, "affiliations_resolved": sum(bool(p.get("affiliations")) for p in candidates),
            "candidate_count": len(candidates)},
        "coverage": {"from": min(p["source_date"] for p in candidates), "to": today, "categories": ARXIV_QUERY},
    })
    write_json(cache_dir / "candidates.json", candidates)
    seen.update({p["arxiv_id"]: today for p in selected})
    write_json(cache_dir / "recommended.json", {key: date for key, date in seen.items() if date >= cutoff})
    return result
