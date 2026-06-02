from urllib.parse import parse_qs, urlparse

from tests.canned_responses import make_sample_paper
from zotero_arxiv_daily.feedback import build_feedback_issue_url, make_paper_id, parse_feedback_body
from zotero_arxiv_daily.interest_profile import InterestProfile
from zotero_arxiv_daily.keyword_extractor import assign_keywords_to_papers, keyword_overlap_score


def test_feedback_issue_url_round_trips_payload():
    paper = make_sample_paper(title="A World Model Paper")
    paper.paper_id = make_paper_id(paper)

    url = build_feedback_issue_url("owner/repo", paper, "like", "run-1")
    query = parse_qs(urlparse(url).query)
    payload = parse_feedback_body(query["body"][0])

    assert payload["paper_id"] == paper.paper_id
    assert payload["action"] == "like"
    assert payload["run_id"] == "run-1"


def test_interest_profile_updates_keywords_from_feedback(tmp_path):
    state_path = tmp_path / "interest_profile.json"
    profile = InterestProfile(
        state_path,
        default_keywords=["world model", "unified model", "generation model"],
    )
    paper = make_sample_paper(
        title="Robot Planning with Latent World Models",
        keywords=["robot planning", "latent world model", "embodied ai"],
        matched_keywords=["world model"],
    )
    paper.paper_id = make_paper_id(paper)
    profile.set_last_run(run_id="run-1", papers=[paper], exploration_keywords=[])

    applied = profile.apply_feedback(
        [{"paper_id": paper.paper_id, "action": "like", "run_id": "run-1", "issue_number": 7}]
    )

    assert len(applied) == 1
    assert "robot planning" in profile.top_keywords()
    assert "latent world model" in profile.top_keywords()


def test_keyword_extraction_and_overlap_score():
    paper = make_sample_paper(
        title="Learning World Models for Video Generation",
        abstract="We learn a latent world model for controllable video generation and planning.",
    )

    assign_keywords_to_papers([paper], max_keywords=5)
    score = keyword_overlap_score(paper, ["world model", "video generation"])

    assert paper.keywords
    assert score > 0
