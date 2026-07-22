from omegaconf import open_dict

from tests.canned_responses import make_sample_paper
from zotero_arxiv_daily.feedback import make_paper_id
from zotero_arxiv_daily.feedback_sync import apply_pending_feedback
from zotero_arxiv_daily.interest_profile import InterestProfile


def test_feedback_sync_updates_profile_without_email_config(config, tmp_path, monkeypatch):
    """The standalone synchronizer should only need GitHub feedback access."""
    with open_dict(config):
        config.interest.enabled = True
        config.interest.state_path = str(tmp_path / "interest_profile.json")

    profile = InterestProfile.from_config(config)
    paper = make_sample_paper(keywords=["robot planning"])
    paper.paper_id = make_paper_id(paper)
    profile.set_last_run(run_id="run-1", papers=[paper], exploration_keywords=[])
    profile.save()

    closed = []

    class StubFeedbackClient:
        def fetch_feedback(self):
            return [
                {
                    "paper_id": paper.paper_id,
                    "action": "like",
                    "run_id": "run-1",
                    "issue_number": 17,
                }
            ]

        def close_feedback_issues(self, items):
            closed.extend(items)

    monkeypatch.setattr(
        "zotero_arxiv_daily.feedback_sync.GitHubFeedbackClient.from_config",
        lambda _: StubFeedbackClient(),
    )

    updated_profile, applied = apply_pending_feedback(config)

    assert len(applied) == 1
    assert "robot planning" in updated_profile.top_keywords()
    assert [item["issue_number"] for item in closed] == [17]
