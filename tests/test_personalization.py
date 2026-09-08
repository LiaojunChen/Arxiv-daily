import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import personalization as engine
from zotero_arxiv_daily.delivery_state import record_delivery
from zotero_arxiv_daily.interest_profile import InterestProfile


def paper(key="2609.00001", **kwargs):
    return dict(arxiv_id=key, title="World model for planning", abstract="Robotic planning with tactile sensing.",
                authors=["Alice Smith"], affiliations=[], categories=["cs.AI"], **kwargs)


def test_separate_topics_use_explicit_weights_and_keep_examples(monkeypatch):
    monkeypatch.setattr(engine.reranker, "SILICONFLOW_API_KEY", "test")
    calls = []
    def score(query, docs):
        calls.append(query)
        return [.9, .1] if "world model" in query else [.1, .9]
    monkeypatch.setattr(engine.reranker, "_cached_rerank", score)
    profile = {"keywords": [{"term": "world model", "score": 10}, {"term": "vision", "score": 1}]}
    results = engine.rank_personalized([paper(), paper("2609.00002")], profile)
    assert len(calls) == 2
    assert results[0]["arxiv_id"] == "2609.00001"
    profile["keywords"][0]["score"], profile["keywords"][1]["score"] = 1, 10
    results = engine.rank_personalized([paper(), paper("2609.00002")], profile)
    assert results[0]["arxiv_id"] == "2609.00002"
    profile["positive_examples"] = {"a": {"title": "Liked tactile paper"}}
    engine.rank_personalized([paper(), paper("2609.00002")], profile, [{"title": "Zotero paper"}])
    assert any("Liked tactile paper" in q for q in calls)
    assert any("Zotero paper" in q for q in calls)


def test_channel_failure_falls_back_for_every_paper(monkeypatch):
    monkeypatch.setattr(engine.reranker, "SILICONFLOW_API_KEY", "test")
    monkeypatch.setattr(engine.time, "sleep", lambda _: None)
    def score(query, docs):
        if "vision" in query: raise RuntimeError("offline")
        return [.9] * len(docs)
    monkeypatch.setattr(engine.reranker, "_cached_rerank", score)
    status = {}
    results = engine.rank_personalized([paper()], {"keywords": [{"term": "world model"}, {"term": "vision"}]}, diagnostics=status)
    assert status["degraded"]
    assert results[0]["scorer"] == "keyword"


def test_following_boost_is_explicit_and_capped(monkeypatch):
    monkeypatch.setattr(engine.reranker, "SILICONFLOW_API_KEY", "test")
    monkeypatch.setattr(engine.reranker, "_cached_rerank", lambda *args: [.6])
    profile = {"keywords": [{"term": "world model"}], "subscriptions": {"followed_authors": ["Alice Smith"]}}
    result = engine.rank_personalized([paper()], profile)[0]
    assert 0 < result["follow_boost"] <= 1
    profile["subscriptions"]["followed_authors"] = []
    assert engine.rank_personalized([paper()], profile)[0]["follow_boost"] == 0


def test_keep_fifty_without_forcing_unrelated_exploration():
    candidates = [paper(str(i), similarity_score=0, semantic_score=0, keywords=["random", str(i)]) for i in range(65)]
    result = engine.select_personalized(candidates)
    assert len(result) == len({p["arxiv_id"] for p in result}) == 50
    assert all(p["recommendation_group"] == "primary" for p in result)


def test_negative_themes_need_distinct_papers_and_dismiss_is_local(tmp_path):
    profile = InterestProfile(tmp_path / "profile.json")
    event = {"paper_id": "2609.00001", "action": "not_interested", "source": "cloudflare", "feedback_id": 1,
             "paper": {"title": "Diffusion", "abstract": "Video diffusion", "keywords": ["diffusion"]}}
    profile.apply_feedback([event])
    assert not profile.suppressed_keywords()
    profile.apply_feedback([{**event, "feedback_id": 2}])
    assert not profile.suppressed_keywords()
    profile.apply_feedback([{**event, "paper_id": "2609.00002", "feedback_id": 3}])
    assert "diffusion" in profile.suppressed_keywords()
    before = copy.deepcopy(profile.data["negative_keywords"])
    profile.apply_feedback([{**event, "paper_id": "2609.00003", "action": "dismiss", "feedback_id": 4}])
    assert profile.data["negative_keywords"] == before
    assert "2609.00003" in profile.data["dismissed_papers"]


def test_read_and_bookmark_are_separate_from_exposure(tmp_path):
    profile = InterestProfile(tmp_path / "profile.json")
    base = {"paper_id": "2609.00001", "source": "cloudflare", "paper": paper()}
    before = copy.deepcopy(profile.data["keywords"])
    profile.apply_feedback([{**base, "feedback_id": 1, "action": "read"}])
    assert profile.data["keywords"] == before
    assert "2609.00001" in profile.data["read_papers"]
    profile.apply_feedback([{**base, "feedback_id": 2, "action": "bookmark"}])
    assert "2609.00001" in profile.data["bookmarked_papers"]
    assert "2609.00001" in profile.data["positive_examples"]
    assert not profile.data.get("recommended_papers")


def test_correcting_negative_feedback_removes_theme_evidence_without_extra_like_weight(tmp_path):
    profile = InterestProfile(tmp_path / "profile.json")
    base = {"paper_id": "a", "source": "cloudflare", "paper": {"title": "Vision paper", "keywords": ["vision"]}}
    profile.apply_feedback([{**base, "feedback_id": 1, "action": "like"}])
    weight = next(k["score"] for k in profile.data["keywords"] if k["term"] == "vision")
    profile.apply_feedback([{**base, "feedback_id": 2, "action": "not_interested"},
                            {**base, "paper_id": "b", "feedback_id": 3, "action": "not_interested"}])
    assert "vision" in profile.suppressed_keywords()
    profile.apply_feedback([{**base, "feedback_id": 4, "action": "like"}])
    assert "vision" not in profile.suppressed_keywords()
    assert "a" not in profile.data["dismissed_papers"]
    assert next(k["score"] for k in profile.data["keywords"] if k["term"] == "vision") == weight


def test_permanent_ledger_dedupes_versions_and_never_marks_all_candidates():
    profile = {}
    snapshot = {"similar_papers": [paper("2609.00001v2")], "candidate_papers": [paper("2609.00002")],
                "updated_at": "2026-09-08", "batch_id": "batch"}
    record_delivery(profile, snapshot)
    record_delivery(profile, snapshot)
    assert list(profile["recommended_papers"]) == ["2609.00001"]
    assert profile["delivery"]["batch_id"] == "batch"


def test_pipeline_freezes_a_batch_and_excludes_history_on_new_batch(tmp_path, monkeypatch):
    import daily_pipeline as pipeline
    import fetch_papers
    root = tmp_path / "data"
    root.mkdir()
    state = root / "interest_profile.json"
    state.write_text(json.dumps({"recommended_papers": {"old": "2020-01-01"}}))
    source = [paper(key, listing_date="2026-09-08", source_date="2026-09-08", source="arxiv") for key in ["old", "a", "b", "c", "d"]]
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setenv("INTEREST_PROFILE_PATH", str(state))
    monkeypatch.setenv("PIPELINE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(pipeline, "MAX_PAPER_NUM", 3)
    monkeypatch.setattr(pipeline, "get_new_listing_papers", lambda _: copy.deepcopy(source))
    monkeypatch.setattr(pipeline, "fetch_hf_daily_papers", lambda: [paper("old-hf", source_date="2020-01-01", source="huggingface")])
    monkeypatch.setattr(pipeline, "fetch_zotero_items", lambda: [])
    affiliation_orders = []
    monkeypatch.setattr(
        pipeline,
        "enrich_affiliations_for_display_papers",
        lambda groups, **k: affiliation_orders.append(
            [paper["arxiv_id"] for paper in groups[0]]
        ),
    )
    monkeypatch.setattr(engine.reranker, "SILICONFLOW_API_KEY", "")
    monkeypatch.setattr(fetch_papers, "output_result", lambda selected, followed, hf, **kw:
        dict(similar_papers=selected, followed_papers=followed, hf_papers=hf, **kw["metadata"], candidate_papers=kw["candidate_papers"]))
    first = pipeline.generate()
    ids = {p["arxiv_id"] for p in first["similar_papers"]}
    assert len(ids) == 3
    assert "old" not in ids and "old-hf" not in ids
    # Merely generating candidates has not marked them published.
    profile = json.loads(state.read_text())
    assert set(profile["recommended_papers"]) == {"old"}
    record_delivery(profile, first)
    state.write_text(json.dumps(profile))
    affiliation_orders.clear()
    same = pipeline.generate()
    assert same["pipeline_status"]["ranking"]["reused_batch"]
    assert {p["arxiv_id"] for p in same["similar_papers"]} == ids
    assert set(affiliation_orders[0][:len(ids)]) == ids
    for p in source:
        p["listing_date"] = p["source_date"] = "2026-09-09"
    source.append(paper("new", listing_date="2026-09-09", source_date="2026-09-09", source="arxiv"))
    next_issue = pipeline.generate()
    next_ids = {p["arxiv_id"] for p in next_issue["similar_papers"]}
    assert next_ids.isdisjoint(ids | {"old", "old-hf"})
    assert len(next_ids) == 2  # Never recycle old papers to fill the quota.
