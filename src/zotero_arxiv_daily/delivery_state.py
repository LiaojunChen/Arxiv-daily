"""Permanent exposure ledger, written only after successful Pages deployment."""
import json
import os
import tempfile
import sys
import hashlib
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path

from .recommendation import canonical_arxiv_id


def batch_fingerprint(date, ids):
    return hashlib.sha256(json.dumps([date, sorted(ids)], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def record_delivery(profile, snapshot):
    ledger = profile.setdefault("recommended_papers", {})
    for paper in snapshot.get("similar_papers", []):
        key = canonical_arxiv_id(paper.get("arxiv_id", ""))
        if key:
            ledger.setdefault(key, snapshot.get("updated_at", ""))
    if snapshot.get("batch_id") and snapshot.get("updated_at", "") >= profile.get("delivery", {}).get("updated_at", ""):
        profile["delivery"] = {"batch_id": snapshot["batch_id"], "run_id": snapshot.get("run_id"),
                               "updated_at": snapshot.get("updated_at", ""),
                               "profile_version": snapshot.get("profile_version"),
                               "papers": snapshot.get("similar_papers", []),
                               "ranking": snapshot.get("pipeline_status", {}).get("ranking", {})}


def main():
    path = Path("data/interest_profile.json")
    profile = json.loads(path.read_text(encoding="utf-8"))
    if "--recover" in sys.argv:
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
        url = os.environ.get("PUBLISHED_SNAPSHOT_URL") or f"https://{owner}.github.io/{repo}/papers.json"
        # Recover a deployment that succeeded before the ledger commit failed.
        # Fail closed on network errors instead of silently recommending duplicates.
        try:
            with urlopen(Request(url, headers={"User-Agent": "ArxivDaily/1.0", "Cache-Control": "no-cache"}), timeout=30) as response:
                snapshot = json.load(response)
        except HTTPError as exc:
            if exc.code == 404: return  # First deployment has no prior issue.
            raise
        if not snapshot.get("batch_id"):
            date = snapshot.get("pipeline_status", {}).get("arxiv_listing_date")
            ids = [p["arxiv_id"] for p in snapshot.get("candidate_papers", []) if date and p.get("listing_date") == date]
            if ids:
                snapshot["batch_id"] = batch_fingerprint(date, ids)
    else:
        snapshot = json.loads(Path("data/papers.json").read_text(encoding="utf-8"))
    record_delivery(profile, snapshot)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
        json.dump(profile, out, ensure_ascii=False, indent=2)
        temp = out.name
    os.replace(temp, path)


if __name__ == "__main__":
    main()
