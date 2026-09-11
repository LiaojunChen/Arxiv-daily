"""Generate a single public snapshot for Pages and email, including all candidates."""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from zotero_arxiv_daily.recommendation import canonical_arxiv_id, paper_keywords
from zotero_arxiv_daily.schedule_health import expected_listing_date
from pipeline_state import fingerprint, read_json, write_json
from config import MAX_PAPER_NUM, ARXIV_QUERY, load_user_config, get_followed_authors, get_followed_institutions
from arxiv_fetcher import get_latest_papers
from arxiv_listing import get_new_listing_papers
from hf_fetcher import fetch_hf_daily_papers
from affiliation_extractor import enrich_affiliations_for_display_papers
from interest_state import load_interest_state, load_interest_weights
from zotero_similar import fetch_zotero_items
from personalization import rank_personalized, select_personalized, follow_signals
from source_http import fetches as source_fetches


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
    source_fetches.clear()
    from fetch_papers import output_result, _validate_display_data
    load_user_config(ROOT / "data/config.json")
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    profile_path = Path(os.environ.get("INTEREST_PROFILE_PATH") or ROOT / "data/interest_profile.json")
    cache_dir = Path(os.environ.get("PIPELINE_CACHE_DIR") or ROOT / "data/cache")
    profile = read_json(profile_path, {})
    source_errors = {}
    def fetch_source(name, fetch):
        try:
            return fetch()
        except Exception as exc:
            source_errors[name] = type(exc).__name__
            print(f"[WARN] {name} source failed: {exc}")
            return []
    hf = fetch_source("hf", fetch_hf_daily_papers)
    rss = fetch_source("arxiv_listing", lambda: get_new_listing_papers(ARXIV_QUERY))
    arxiv_source = "new_listing"
    expected_date = expected_listing_date(now)
    listing_dates = [p.get("listing_date", "") for p in rss]
    if not rss or min(listing_dates) < expected_date:
        fallback = fetch_source("arxiv", lambda: get_latest_papers(ARXIV_QUERY))
        fallback_date = max((p.get("published", "")[:10] for p in fallback), default="")
        if fallback and (not rss or fallback_date > max(listing_dates)):
            rss = [{**p, "listing_date": fallback_date} for p in fallback]
            arxiv_source = "rss"
    source_dates = [p.get("listing_date", "") for p in rss]
    source_fresh = bool(source_dates) and min(source_dates) >= expected_date
    if not source_fresh:
        print(f"[WARN] arXiv release pending/stale: expected {expected_date}; received {sorted(set(source_dates))}")
    for paper in rss:
        paper.setdefault("source_date", (paper.get("published") or today)[:10])
    current = merge_candidates([hf, rss])
    _validate_display_data([], [], current)
    for paper in current:
        paper.setdefault("source_date", today)
    cutoff = (now.date() - timedelta(days=7)).isoformat()
    # Published metadata is durable even if Actions evicts its incremental cache.
    previous = [p for p in merge_candidates([
        read_json(cache_dir / "candidates.json", []), profile.get("delivery", {}).get("papers", [])
    ]) if p.get("source_date", "") >= cutoff]
    candidates = merge_candidates([previous, current])
    candidates.sort(key=lambda p: p.get("source_date", ""), reverse=True)
    delivered_ids = {
        canonical_arxiv_id(p.get("arxiv_id", ""))
        for p in profile.get("delivery", {}).get("papers", [])
    }
    # The later enrichment run has a finite time budget. Resolve papers already
    # visible in the current issue before spending that budget on the full
    # seven-day candidate pool.
    candidates.sort(key=lambda p: (
        canonical_arxiv_id(p.get("arxiv_id", "")) not in delivered_ids,
        p.get("affiliation_status") == "unresolved",
    ))
    enrich_affiliations_for_display_papers([candidates], cache_path=cache_dir / "affiliations.json",
        budget_seconds=float(os.environ.get("AFFILIATION_BUDGET_SECONDS") or 900))
    for paper, keywords in zip(candidates, paper_keywords([f"{p['title']}\n{p['abstract']}" for p in candidates])):
        paper["keywords"] = keywords
    by_id = {p["arxiv_id"]: p for p in candidates}
    current = [by_id[p["arxiv_id"]] for p in current]
    hf = [{**by_id[canonical_arxiv_id(p["arxiv_id"])], "source": "huggingface"} for p in hf]
    interests, suppressed = load_interest_state(profile_path)
    weights = load_interest_weights(profile_path)
    for p in candidates:
        p["user_actions"] = [action for action, field in (("read", "read_papers"), ("bookmark", "bookmarked_papers"))
                             if p["arxiv_id"] in profile.get(field, {})]
    profile.setdefault("subscriptions", {"followed_authors": get_followed_authors(), "followed_institutions": get_followed_institutions()})
    diagnostics = {}
    os.environ["RERANK_CACHE_PATH"] = str(cache_dir / "rerank.json")
    listing_date = max((p.get("listing_date") or p.get("source_date", "") for p in rss), default=today)
    # HF is a supplementary view. Old curated papers cannot displace new arXiv announcements.
    rss_ids = {canonical_arxiv_id(p["arxiv_id"]) for p in rss}
    fresh = [p for p in current if p.get("listing_date") == listing_date or
             (arxiv_source == "rss" and p["arxiv_id"] in rss_ids)]
    batch_id = fingerprint([listing_date, sorted(p["arxiv_id"] for p in fresh)])[:24]
    delivery = profile.get("delivery", {})
    if not rss or (not source_fresh and delivery.get("batch_id")):
        if not delivery.get("batch_id"):
            raise RuntimeError("arXiv unavailable and no published issue to preserve")
        batch_id = delivery["batch_id"]
    blocked = set(profile.get("recommended_papers", {})) | set(profile.get("read_papers", {})) | set(profile.get("dismissed_papers", {}))
    if delivery.get("batch_id") == batch_id:
        # Refresh metadata of an existing issue; never generate a second issue from the same batch.
        selected = [{**p, "affiliations": by_id.get(p["arxiv_id"], p).get("affiliations", []),
                     "user_actions": by_id.get(p["arxiv_id"], p).get("user_actions", []),
                     "affiliation_status": by_id.get(p["arxiv_id"], p).get("affiliation_status", "pending")}
                    for p in delivery.get("papers", []) if p["arxiv_id"] not in profile.get("dismissed_papers", {})]
        diagnostics = {**delivery.get("ranking", {}), "reused_batch": True}
    else:
        eligible = [p for p in fresh if p["arxiv_id"] not in blocked]
        ranked = rank_personalized(eligible, profile, fetch_zotero_items(), diagnostics)
        selected = select_personalized(ranked, MAX_PAPER_NUM, int(os.environ.get("EXPLORATION_PAPER_COUNT") or 10))
    exploration = [p for p in selected if p.get("recommendation_group") == "exploration"]
    followed = [{**p, "source": "followed"} for p in candidates if any(follow_signals(p, profile["subscriptions"]))]
    profile_version = fingerprint([interests, suppressed, weights, profile.get("positive_examples", {}), profile["subscriptions"]])[:16]
    if diagnostics.get("reused_batch"):
        profile_version = delivery.get("profile_version") or profile_version
    run_id = "daily-" + fingerprint([today, profile_version, selected, candidates])[:24]
    result = output_result(selected, followed, hf, candidate_papers=candidates, metadata={
        "run_id": run_id, "batch_id": batch_id, "profile_version": profile_version, "top_keywords": interests,
        "exploration_keywords": sorted({k for p in exploration for k in p.get("keywords", []) if k not in interests}),
        "subscriptions": profile["subscriptions"],
        "pipeline_status": {"arxiv": ("ok" if source_fresh else "stale") if rss else "empty_or_unavailable", "hf": "ok" if hf else "empty_or_unavailable",
            "expected_listing_date": expected_date,
            "arxiv_source": arxiv_source, "arxiv_listing_date": max((p.get("listing_date", "") for p in rss), default=""),
            "source_errors": source_errors,
            "source_fetches": list(source_fetches),
            "ranking": diagnostics, "affiliations_resolved": sum(bool(p.get("affiliations")) for p in candidates),
            "candidate_count": len(candidates)},
        "coverage": {"from": min(p["source_date"] for p in candidates), "to": today, "categories": ARXIV_QUERY},
    })
    write_json(cache_dir / "candidates.json", candidates)
    return result
