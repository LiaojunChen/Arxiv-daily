from datetime import datetime, timezone

import pytest

from zotero_arxiv_daily.schedule_health import expected_listing_date, is_fresh, recovery_due


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("instant,expected", [
    ("2026-09-09T00:05:00", "2026-09-09"),
    ("2026-01-07T00:05:00", "2026-01-06"),
    ("2026-01-07T01:05:00", "2026-01-07"),
    ("2026-09-12T10:00:00", "2026-09-11"),
    ("2026-09-14T00:05:00", "2026-09-14"),
])
def test_dst_and_weekend_release_dates(instant, expected):
    assert expected_listing_date(utc(instant)) == expected


def test_new_generation_timestamp_does_not_hide_stale_papers():
    snapshot = {"updated_at": "2026-09-09T10:45:00+08:00",
                "pipeline_status": {"arxiv": "ok", "arxiv_listing_date": "2026-09-07"}}
    now = utc("2026-09-09T02:00:00")
    assert not is_fresh(snapshot, now)
    assert recovery_due(snapshot, [], now)
    snapshot["pipeline_status"]["arxiv_listing_date"] = "2026-09-09"
    assert is_fresh(snapshot, now)
    assert not recovery_due(snapshot, [], now)


@pytest.mark.parametrize("status,created", [
    ("queued", "2026-09-09T00:00:00Z"),
    ("in_progress", "2026-09-09T00:00:00Z"),
    ("completed", "2026-09-09T01:30:00Z"),
])
def test_no_dispatch_storm(status, created):
    assert not recovery_due({}, [{"status": status, "createdAt": created}], utc("2026-09-09T02:00:00"))


def test_no_weekend_or_before_grace_dispatch():
    assert not recovery_due({}, [], utc("2026-09-12T02:00:00"))
    assert not recovery_due({}, [], utc("2026-09-09T00:30:00"))


def test_verify_pending_warns_and_writes_summary_without_failing(tmp_path, monkeypatch, capsys):
    import json
    from zotero_arxiv_daily import schedule_health
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    snapshot = {"pipeline_status": {"arxiv": "stale", "arxiv_listing_date": "2026-09-07"}}
    (tmp_path / "data/papers.json").write_text(json.dumps(snapshot))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(schedule_health.sys, "argv", ["health", "--verify"])
    schedule_health.main()
    assert "::warning" in capsys.readouterr().out
    assert "pending/stale" in summary.read_text()
    assert not is_fresh(snapshot, utc("2026-09-09T02:00:00"))
    assert recovery_due(snapshot, [], utc("2026-09-09T02:00:00"))
    # Broken snapshot data remains an actual error, not a pending release.
    (tmp_path / "data/papers.json").write_text("broken json")
    with pytest.raises(json.JSONDecodeError):
        schedule_health.main()
