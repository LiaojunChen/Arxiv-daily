"""Enrich an already published issue without fetching or selecting new papers."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from affiliation_extractor import enrich_affiliations_for_display_papers
from personalization import follow_signals
from pipeline_state import write_json


def refresh_snapshot(snapshot, cache_dir, budget_seconds=900, include_candidates=False):
    # A single ordered group spends the budget on recommendations first. Passing
    # separate groups would interleave the 50 selected papers with the full pool.
    fields = ("similar_papers", "followed_papers", "hf_papers", "candidate_papers")
    papers = [paper for field in fields for paper in snapshot.get(field, [])]
    visible = [paper for field in fields[:-1] for paper in snapshot.get(field, [])]
    enrich_affiliations_for_display_papers(
        [papers if include_candidates else visible], cache_path=Path(cache_dir) / "affiliations.json",
        budget_seconds=budget_seconds,
    )
    # Update copies in the candidate pool without spending the early refresh
    # budget downloading thousands of papers that were not selected.
    enrich_affiliations_for_display_papers(
        [papers], cache_path=Path(cache_dir) / "affiliations.json", budget_seconds=0,
    )
    candidates = snapshot.get("candidate_papers", [])
    # Newly discovered institutions must become available to the followed tab too.
    if "subscriptions" in snapshot:
        snapshot["followed_papers"] = [
            {**p, "source": "followed"} for p in candidates
            if any(follow_signals(p, snapshot["subscriptions"]))
        ]
    selected = snapshot.get("similar_papers", [])
    resolved = sum(bool(p.get("affiliations")) for p in selected)
    status = snapshot.setdefault("pipeline_status", {})
    status.update(
        affiliations_resolved=sum(bool(p.get("affiliations")) for p in candidates),
        recommendation_affiliations_resolved=resolved,
        recommendation_affiliations_total=len(selected),
        affiliation_refresh="complete" if resolved == len(selected) else "partial",
    )
    # Keep the issue/run identity for feedback and permanent deduplication, but
    # change the metadata timestamp so open browser tabs pick up the enrichment.
    original_time = datetime.fromisoformat(snapshot["updated_at"])
    snapshot["updated_at"] = datetime.now(original_time.tzinfo or timezone.utc).isoformat(timespec="seconds")
    write_json(Path(cache_dir) / "candidates.json", candidates)
    print(f"[AFFILIATIONS] Recommendations resolved: {resolved}/{len(selected)}")
    if selected and not resolved:
        print("::warning::No recommended paper affiliations resolved; inspect source/LLM extraction warnings.")
    return snapshot


def main():
    path = Path("data/papers.json")
    # Read strictly: a missing/broken snapshot must never overwrite the live issue.
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    refresh_snapshot(
        snapshot, os.environ.get("PIPELINE_CACHE_DIR") or "data/cache",
        float(os.environ.get("AFFILIATION_BUDGET_SECONDS") or 900),
        include_candidates=os.environ.get("AFFILIATION_INCLUDE_CANDIDATES") == "true",
    )
    write_json(path, snapshot)


if __name__ == "__main__":
    main()
