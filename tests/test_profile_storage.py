import copy
import gzip
import json

import pytest

from zotero_arxiv_daily import profile_storage as storage
from zotero_arxiv_daily.interest_profile import InterestProfile


def make_run(index, abstract="A world model for robot planning."):
    return {
        "run_id": f"run-{index}", "generated_at": f"2026-09-{index + 1:02d}T00:00:00Z",
        "selected_ids": ["2609.00001"],
        "papers": {"2609.00001": {"title": "World model", "abstract": abstract,
                                   "keywords": ["world model"], "matched_keywords": []}},
    }


def test_migration_preserves_every_run_and_permanent_state(tmp_path):
    path = tmp_path / "profile.json"
    data = {"runs": {f"run-{i}": make_run(i) for i in range(8)},
            "processed_feedback": ["issue:1"], "recommended_papers": {"2609.00001": "yesterday"},
            "keywords": [{"term": "world model", "score": 42}],
            "delivery": {"batch_id": "published"}, "paper_actions": {"2609.00001:like": "today"}}
    original = copy.deepcopy(data)
    storage.save_profile(path, data)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert set(persisted["runs"]) == {"run-5", "run-6", "run-7"}
    assert {k: v for k, v in persisted.items() if k != "runs"} == {k: v for k, v in original.items() if k != "runs"}
    for key, run in original["runs"].items():
        assert (persisted["runs"].get(key) or storage.load_archived_run(path, key)) == run
    before = path.read_bytes()
    archives = {p.name: p.read_bytes() for p in storage.archive_directory(path).iterdir()}
    storage.save_profile(path, data)
    assert path.read_bytes() == before
    assert {p.name: p.read_bytes() for p in storage.archive_directory(path).iterdir()} == archives


def test_byte_budget_archives_even_one_large_run(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_ACTIVE_RUN_BYTES", 1000)
    path = tmp_path / "profile.json"
    run = make_run(0, "摘要" * 2000)
    data = {"runs": {"run-0": run}}
    storage.save_profile(path, data)
    assert data["runs"] == {}
    assert storage.load_archived_run(path, "run-0") == run
    assert path.stat().st_size < 1000


def test_archived_feedback_applies_once_after_reload(tmp_path):
    path = tmp_path / "profile.json"
    profile = InterestProfile(path)
    profile.data["runs"] = {f"run-{i}": make_run(i) for i in range(8)}
    profile.save()
    event = {"paper_id": "2609.00001", "run_id": "run-0", "action": "like", "issue_number": 12}
    profile = InterestProfile(path)
    assert "run-0" not in profile.data["runs"]
    assert len(profile.apply_feedback([event])) == 1
    assert profile.data["positive_examples"]["2609.00001"]["abstract"] == make_run(0)["papers"]["2609.00001"]["abstract"]
    profile.save()
    assert InterestProfile(path).apply_feedback([event]) == []


def test_byte_budget_keeps_newest_window_not_smaller_older_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_ACTIVE_RUN_BYTES", 1500)
    path = tmp_path / "profile.json"
    runs = {"run-0": make_run(0), "run-1": make_run(1, "x" * 1200), "run-2": make_run(2)}
    data = {"runs": runs}
    storage.save_profile(path, data)
    assert list(data["runs"]) == ["run-2"]
    assert storage.load_archived_run(path, "run-0") == runs["run-0"]


def test_missing_run_stays_pending_and_paths_cannot_escape(tmp_path):
    path = tmp_path / "profile.json"
    profile = InterestProfile(path)
    event = {"paper_id": "2609.00001", "run_id": "../../outside", "action": "like", "issue_number": 12}
    assert profile.apply_feedback([event]) == []
    assert profile.data["processed_feedback"] == []
    assert storage.archive_path(path, event["run_id"]).parent == storage.archive_directory(path)


def test_failed_archive_write_leaves_profile_and_memory_intact(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    data = {"runs": {f"run-{i}": make_run(i) for i in range(8)}}
    original = copy.deepcopy(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    def fail_replace(*args):
        raise OSError("disk full")
    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        storage.save_profile(path, data)
    assert data == original
    assert path.read_bytes() == before
    assert not list(storage.archive_directory(path).iterdir())


def test_failed_profile_write_is_retryable(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    data = {"runs": {f"run-{i}": make_run(i) for i in range(8)}}
    original = copy.deepcopy(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    replace = storage.os.replace
    def fail_profile(source, target):
        if target == path:
            raise OSError("profile write failed")
        replace(source, target)
    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "replace", fail_profile)
        with pytest.raises(OSError, match="profile write failed"):
            storage.save_profile(path, data)
    assert data == original
    assert path.read_bytes() == before
    storage.save_profile(path, data)
    for key, run in original["runs"].items():
        assert (data["runs"].get(key) or storage.load_archived_run(path, key)) == run


def test_file_guard_checks_archives_and_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_FILE_BYTES", 100)
    path = tmp_path / "profile.json"
    path.write_text("{}", encoding="utf-8")
    storage.check_profile_files(path)
    archive = storage.archive_path(path, "old")
    archive.parent.mkdir()
    archive.write_bytes(b"x" * 100)
    with pytest.raises(ValueError, match="refusing to commit"):
        storage.check_profile_files(path)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="budget"):
        storage.save_profile(path, {"permanent": "x" * 100})
    assert path.read_bytes() == before


def test_corrupt_archive_does_not_acknowledge_feedback(tmp_path):
    path = tmp_path / "profile.json"
    archive = storage.archive_path(path, "old")
    archive.parent.mkdir()
    archive.write_bytes(b"invalid gzip")
    profile = InterestProfile(path)
    with pytest.raises(gzip.BadGzipFile):
        profile.apply_feedback([{"paper_id": "2609.00001", "run_id": "old", "action": "like", "issue_number": 12}])
    assert profile.data["processed_feedback"] == []


def test_delivery_writer_also_archives_history(tmp_path, monkeypatch):
    from zotero_arxiv_daily import delivery_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(delivery_state.sys, "argv", ["delivery_state"])
    path = tmp_path / "data/interest_profile.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"runs": {f"run-{i}": make_run(i) for i in range(8)}}), encoding="utf-8")
    snapshot = {"batch_id": "new-batch", "updated_at": "2026-09-18T00:00:00Z",
                "similar_papers": [{"arxiv_id": "2609.00001"}]}
    (path.parent / "papers.json").write_text(json.dumps(snapshot), encoding="utf-8")
    delivery_state.main()
    profile = json.loads(path.read_text(encoding="utf-8"))
    assert len(profile["runs"]) == 3
    assert profile["recommended_papers"]["2609.00001"] == snapshot["updated_at"]
    assert profile["delivery"]["batch_id"] == "new-batch"
    assert storage.load_archived_run(path, "run-0") == make_run(0)
