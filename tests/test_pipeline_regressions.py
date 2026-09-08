"""Regression coverage for subscription recall, feedback trust and daily delivery."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import affiliation_extractor as ae
import daily_pipeline as pipeline
import zotero_similar as ranking
from subscriptions import matches_author, matches_institution
from zotero_arxiv_daily.feedback import GitHubFeedbackClient, MARKER_START, MARKER_END, make_paper_id
from zotero_arxiv_daily.interest_profile import InterestProfile
from zotero_arxiv_daily.recommendation import matched_keywords_for_text, mmr_select
from zotero_arxiv_daily.snapshot_mail import snapshot_papers
from tests.canned_responses import make_sample_paper


def paper(key="2609.00001", **overrides):
    return dict(arxiv_id=key, title="World model with tactile sensing", abstract="Tactile sensing improves robot planning.",
        authors=["Alice Smith"], affiliations=[], categories=["cs.AI"], source="arxiv",
        published="2026-09-08", abstract_url=f"https://arxiv.org/abs/{key}", pdf_url=f"https://arxiv.org/pdf/{key}", **overrides)


@pytest.mark.parametrize("name", ["MIT", "麻省理工学院", "Massachusetts Institute of Technology"])
def test_institution_aliases(name):
    assert matches_institution("CSAIL, Massachusetts Institute of Technology", name)
    assert not matches_institution("Committee Research", "MIT")


def test_author_boundaries():
    assert matches_author("Alice-Smith", "alice smith")
    assert not matches_author("Joann Smith", "Ann Smith")
    assert not matches_author("Alice Smith", "Smith")


def test_keyword_boundaries_and_cjk():
    assert not matched_keywords_for_text("A chair design", ["ai"])
    assert matched_keywords_for_text("An AI world-model", ["ai", "world model"]) == ["ai", "world model"]
    assert matched_keywords_for_text("基于世界模型的规划", ["世界模型"]) == ["世界模型"]
    assert matched_keywords_for_text("World models for planning", ["world model"]) == ["world model"]


def test_partial_rerank_failure_uses_one_scale(monkeypatch):
    monkeypatch.delenv("RERANK_CACHE_PATH", raising=False)
    monkeypatch.setattr(ranking, "SILICONFLOW_API_KEY", "fake")
    monkeypatch.setattr(ranking, "SILICONFLOW_BATCH_SIZE", 1)
    monkeypatch.setattr(ranking.time, "sleep", lambda _: None)
    def rerank(query, docs):
        if "World model" in docs[0]:
            raise RuntimeError("timeout")
        return [.9]
    monkeypatch.setattr(ranking, "_rerank_batch", rerank)
    other = {**paper("2609.00002"), "title": "Unrelated", "abstract": "Unrelated"}
    diagnostics = {}
    result = ranking.compute_similarity([], [paper(), other], 1, interest_keywords=["world model"], diagnostics=diagnostics)
    assert result[0]["arxiv_id"] == "2609.00001"
    assert diagnostics["degraded"] and diagnostics["failed_batches"] == 1


@pytest.mark.parametrize("results", [[], [{"index": 0, "relevance_score": float("nan")}],
    [{"index": -1, "relevance_score": .5}], [{"index": 0, "relevance_score": .5}] * 2])
def test_bad_rerank_responses_fail_closed(monkeypatch, results):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"results": results}).encode()
    monkeypatch.setattr(ranking.urllib.request, "urlopen", lambda *a, **kw: Response())
    with pytest.raises(RuntimeError):
        ranking._rerank_batch("test", ["test"])


def test_mmr_does_not_fill_slots_with_zero_scores():
    assert mmr_select([0, 1, float("nan")], limit=3, score_getter=lambda p: p, text_getter=str) == [1]


def test_rerank_cache_avoids_duplicate_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("RERANK_CACHE_PATH", str(tmp_path / "scores.json"))
    calls = []
    monkeypatch.setattr(ranking, "_rerank_batch", lambda q, docs: calls.append(docs) or [.8] * len(docs))
    assert ranking._cached_rerank("query", ["one", "two"]) == [.8, .8]
    ranking._cached_rerank("query", ["two", "three"])
    assert calls == [["one", "two"], ["three"]]


def test_affiliation_cache_and_budget(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ae, "fetch_paper_text", lambda key: calls.append(key) or r"\affiliation{MIT}")
    monkeypatch.setattr(ae, "OPENAI_API_KEY", "")
    cache = tmp_path / "aff.json"
    first = paper()
    ae.enrich_affiliations_for_display_papers([[first]], cache_path=cache)
    second = paper()
    ae.enrich_affiliations_for_display_papers([[second]], cache_path=cache)
    assert calls == ["2609.00001"]
    assert second["affiliation_status"] == "resolved"
    pending = paper("2609.00002")
    ae.enrich_affiliations_for_display_papers([[pending]], cache_path=cache, budget_seconds=0)
    assert pending["affiliation_status"] == "pending"


def test_legacy_negative_affiliation_cache_is_retried(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        ae,
        "fetch_paper_text",
        lambda key: calls.append(key) or r"\sfsetaffiliation{Salesforce AI Research}",
    )
    monkeypatch.setattr(ae, "OPENAI_API_KEY", "")
    cache = tmp_path / "aff.json"
    target = paper("2609.05295")
    ae.write_json(
        cache,
        {
            ae.paper_cache_key(target): {
                "affiliations": [],
                "expires_at": ae.time.time() + 6 * 3600,
            }
        },
    )

    ae.enrich_affiliations_for_display_papers([[target]], cache_path=cache)

    assert calls == ["2609.05295"]
    assert target["affiliations"] == [
        {"author": "Alice Smith", "affiliation": "Salesforce AI Research"}
    ]


def test_old_email_feedback_survives_next_run_and_reload(tmp_path):
    state = tmp_path / "profile.json"
    profile = InterestProfile(state)
    old = make_sample_paper(keywords=["tactile sensing"])
    old.paper_id = make_paper_id(old)
    profile.set_last_run(run_id="old", papers=[old], exploration_keywords=[])
    profile.set_last_run(run_id="new", papers=[], exploration_keywords=[])
    profile.save()
    profile = InterestProfile(state)
    event = dict(paper_id=old.paper_id, action="like", run_id="old", issue_number=1)
    assert len(profile.apply_feedback([event])) == 1
    assert profile.apply_feedback([event]) == []


def test_unknown_feedback_never_acknowledged_in_mixed_batch(tmp_path):
    profile = InterestProfile(tmp_path / "profile.json")
    p = make_sample_paper(keywords=["tactile sensing"])
    p.paper_id = make_paper_id(p)
    profile.set_last_run(run_id="run", papers=[p], exploration_keywords=[])
    profile.apply_feedback([dict(paper_id="unknown", action="like", run_id="run", issue_number=1),
        dict(paper_id=p.paper_id, action="like", run_id="run", issue_number=2)])
    assert "issue:1" not in profile.data["processed_feedback"]
    assert "issue:2" in profile.data["processed_feedback"]


def test_github_outsiders_and_embedded_metadata_rejected(monkeypatch):
    client = GitHubFeedbackClient("owner/repo", "fake")
    body = MARKER_START + json.dumps(dict(paper_id="fake", run_id="fake", action="like", paper={"keywords": ["injected"]})) + MARKER_END
    monkeypatch.setattr(client, "_request_json", lambda _: [dict(number=1, user={"login": "outsider"}, body=body),
        dict(number=2, user={"login": "owner"}, body=body)])
    events = client.fetch_feedback()
    assert [p["issue_number"] for p in events] == [2]
    assert "paper" not in events[0]


def test_full_candidate_pool_and_identical_email_selection(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/config.json").write_text('{"followed_authors":[],"followed_institutions":[]}', encoding="utf-8")
    (tmp_path / "data/interest_profile.json").write_text('{"keywords":[{"term":"world model","score":10}]}', encoding="utf-8")
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.delenv("INTEREST_PROFILE_PATH", raising=False)
    monkeypatch.delenv("PIPELINE_CACHE_DIR", raising=False)
    monkeypatch.setattr(pipeline, "MAX_PAPER_NUM", 1)
    monkeypatch.setattr(pipeline, "fetch_hf_daily_papers", lambda: [])
    monkeypatch.setattr(pipeline, "get_new_listing_papers", lambda _: [])
    monkeypatch.setattr(pipeline, "get_latest_papers", lambda _: [paper(), paper("2609.00002")])
    monkeypatch.setattr(pipeline, "enrich_affiliations_for_display_papers", lambda *a, **kw: None)
    monkeypatch.setattr(ranking, "SILICONFLOW_API_KEY", "")
    import fetch_papers
    monkeypatch.setattr(fetch_papers, "output_result", lambda selected, followed, hf, **kw:
        dict(similar_papers=selected, followed_papers=followed, hf_papers=hf, **kw["metadata"], candidate_papers=kw["candidate_papers"]))
    result = pipeline.generate()
    assert len(result["candidate_papers"]) == 2
    assert len(result["similar_papers"]) == 1
    assert result["candidate_papers"][1]["keywords"]
    mail = snapshot_papers(result, "owner/repo")
    assert [p.paper_id for p in mail] == [p["arxiv_id"] for p in result["similar_papers"]]
    assert pipeline.generate()["run_id"] == result["run_id"]


def test_merge_deduplicates_arxiv_versions():
    assert len(pipeline.merge_candidates([[paper("2609.00001v1")], [paper("2609.00001v2")]])) == 1


def test_empty_query_uses_default(monkeypatch):
    import importlib
    import config as script_config
    monkeypatch.setenv("ARXIV_QUERY", "   ")
    importlib.reload(script_config)
    assert "cs.AI" in script_config.ARXIV_QUERY


def test_offline_evaluation_requires_labels_and_scores_order():
    from evaluate_recommendations import evaluate
    snapshot = {"similar_papers": [{"arxiv_id": "a"}, {"arxiv_id": "b"}]}
    with pytest.raises(ValueError):
        evaluate(snapshot, {"a": {"relevance": 3}}, 2)
    result = evaluate(snapshot, {"a": {"relevance": 3}, "b": {"relevance": 0}}, 2)
    assert result["precision_at_k"] == .5
    assert result["ndcg_at_k"] == 1


def test_new_version_does_not_inherit_stale_affiliation():
    old = {**paper(), "version": "v1", "affiliations": ["Old Institute"]}
    new = {**paper(), "version": "v2"}
    assert pipeline.merge_candidates([[old], [new]])[0]["affiliations"] == []
