"""Post-publication metadata refresh must preserve selection and feedback identity."""
import copy
import json

from zotero_arxiv_daily.affiliation_refresh import refresh_snapshot
import affiliation_extractor as ae
from zotero_arxiv_daily.delivery_state import record_delivery


def paper(key):
    return dict(arxiv_id=key, authors=["Alice"], title="World model", abstract="Robotic planning",
                affiliations=[], affiliation_status="pending", categories=["cs.RO"])


def snapshot():
    selected = [paper("2609.00001"), paper("2609.00002")]
    return dict(updated_at="2026-09-11T08:05:00+08:00", run_id="same-run", batch_id="same-batch",
                profile_version="same-profile", similar_papers=selected, followed_papers=[], hf_papers=[],
                candidate_papers=[paper("2609.99999"), *copy.deepcopy(selected)],
                subscriptions={"followed_institutions": ["MIT"]},
                pipeline_status={"ranking": {"reused_batch": True}})


def setup_extractor(monkeypatch):
    monkeypatch.setattr(ae, "OPENAI_API_KEY", "")
    monkeypatch.setattr(ae, "AFFILIATION_MAX_PAPERS", 0)


def test_refresh_only_fetches_visible_papers_and_updates_all_copies(tmp_path, monkeypatch):
    setup_extractor(monkeypatch)
    calls = []
    monkeypatch.setattr(ae, "fetch_paper_text", lambda key: calls.append(key) or r"\affiliation{MIT}")
    data = snapshot()
    old = copy.deepcopy(data)
    profile = {}
    record_delivery(profile, data)
    ledger = copy.deepcopy(profile["recommended_papers"])
    refresh_snapshot(data, tmp_path)
    assert calls == ["2609.00001", "2609.00002"]
    for key in ("run_id", "batch_id", "profile_version"):
        assert data[key] == old[key]
    assert [p["arxiv_id"] for p in data["similar_papers"]] == [p["arxiv_id"] for p in old["similar_papers"]]
    assert data["updated_at"] != old["updated_at"]
    assert all(p["affiliations"] for p in data["similar_papers"])
    assert data["candidate_papers"][0]["affiliations"] == []
    assert data["candidate_papers"][1]["affiliations"] == data["similar_papers"][0]["affiliations"]
    assert len(data["followed_papers"]) == 2
    assert data["pipeline_status"]["affiliation_refresh"] == "complete"
    assert data["pipeline_status"]["ranking"] == old["pipeline_status"]["ranking"]
    record_delivery(profile, data)
    assert profile["recommended_papers"] == ledger
    assert profile["delivery"]["papers"][0]["affiliations"]
    assert json.loads((tmp_path / "candidates.json").read_text())[1]["affiliations"]
    refresh_snapshot(data, tmp_path)
    assert calls == ["2609.00001", "2609.00002"]


def test_late_refresh_prioritizes_selected_before_candidate_pool(tmp_path, monkeypatch):
    setup_extractor(monkeypatch)
    monkeypatch.setattr(ae, "AFFILIATION_MAX_PAPERS", 2)
    calls = []
    monkeypatch.setattr(ae, "fetch_paper_text", lambda key: calls.append(key) or r"\affiliation{MIT}")
    refresh_snapshot(snapshot(), tmp_path, include_candidates=True)
    assert calls == ["2609.00001", "2609.00002"]


def test_missing_source_is_reported_without_inventing_affiliations(tmp_path, monkeypatch, capsys):
    setup_extractor(monkeypatch)
    monkeypatch.setattr(ae, "fetch_paper_text", lambda key: None)
    data = refresh_snapshot(snapshot(), tmp_path)
    assert data["pipeline_status"]["affiliation_refresh"] == "partial"
    assert data["pipeline_status"]["recommendation_affiliations_resolved"] == 0
    assert all(p["affiliation_status"] == "unresolved" for p in data["similar_papers"])
    assert "::warning::" in capsys.readouterr().out


def test_zero_budget_uses_existing_metadata_without_network(tmp_path, monkeypatch):
    setup_extractor(monkeypatch)
    def unexpected_request(key):
        raise AssertionError("Cache-only refresh must not download")
    monkeypatch.setattr(ae, "fetch_paper_text", unexpected_request)
    data = snapshot()
    data["similar_papers"][0]["affiliations"] = [{"author": "Alice", "affiliation": "MIT"}]
    refresh_snapshot(data, tmp_path, budget_seconds=0)
    assert data["pipeline_status"]["recommendation_affiliations_resolved"] == 1
    assert data["candidate_papers"][1]["affiliations"]
