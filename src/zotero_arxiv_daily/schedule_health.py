"""Announcement-aware freshness checks and bounded recovery dispatches."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def expected_listing_date(now):
    """Next calendar day of the latest Sun–Thu 20:00 ET announcement.

    Holidays and upstream delays remain pending, never fabricated as fresh data.
    """
    local = now.astimezone(ZoneInfo("America/New_York"))
    announcement = local.replace(hour=20, minute=0, second=0, microsecond=0)
    if local < announcement:
        announcement -= timedelta(days=1)
    while announcement.weekday() not in (6, 0, 1, 2, 3):
        announcement -= timedelta(days=1)
    return (announcement.date() + timedelta(days=1)).isoformat()


def is_fresh(snapshot, now):
    status = snapshot.get("pipeline_status", {})
    return (status.get("arxiv") == "ok" and
            status.get("arxiv_listing_date", "") >= expected_listing_date(now))


def recovery_due(snapshot, runs, now):
    local = now.astimezone(ZoneInfo("America/New_York"))
    # Grace period after release; bounded through the following morning.
    if not ((local.weekday() in (6, 0, 1, 2, 3) and local.hour >= 21) or
            (local.weekday() in (0, 1, 2, 3, 4) and local.hour < 12)):
        return False
    if is_fresh(snapshot, now):
        return False
    for run in runs:
        if run["status"] in ("queued", "in_progress", "waiting", "pending", "requested"):
            return False
        created = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
        if now - created < timedelta(hours=1):
            return False
    return True


def main():
    now = datetime.now(timezone.utc)
    if "--verify" in sys.argv:
        snapshot = json.loads(Path("data/papers.json").read_text(encoding="utf-8"))
        if not is_fresh(snapshot, now):
            actual = snapshot.get("pipeline_status", {}).get("arxiv_listing_date", "unknown")
            message = (f"arXiv release pending/stale: expected {expected_listing_date(now)}, got {actual}. "
                       "Previous recommendations preserved; automatic recovery remains enabled. "
                       "Holidays or upstream caching may delay release.")
            print(f"::warning title=Waiting for arXiv release::{message}")
        else:
            message = f"arXiv release is current: {snapshot['pipeline_status']['arxiv_listing_date']}."
            print(message)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                summary.write(f"### Paper release status\n\n{message}\n")
        return
    repo = os.environ["GITHUB_REPOSITORY"]
    owner, name = repo.split("/", 1)
    request = Request(f"https://{owner}.github.io/{name}/papers.json",
                      headers={"User-Agent": "arXivDaily/1.0", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        snapshot = json.load(response)
    runs = json.loads(subprocess.check_output([
        "gh", "run", "list", "--repo", repo, "--workflow", "daily-fetch.yml",
        "--limit", "20", "--json", "status,createdAt"], text=True))
    if recovery_due(snapshot, runs, now):
        subprocess.run(["gh", "workflow", "run", "daily-fetch.yml", "--repo", repo,
                        "--ref", os.environ["DEFAULT_BRANCH"], "-f", "quick=true"], check=True)
        print("Dispatched stale/missing release recovery.")
    else:
        print("No recovery needed, outside release window, or a recent/active run exists.")


if __name__ == "__main__":
    main()
