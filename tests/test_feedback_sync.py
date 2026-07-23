from omegaconf import open_dict

from tests.canned_responses import make_sample_paper
from zotero_arxiv_daily.feedback import make_paper_id
from zotero_arxiv_daily.feedback_sync import acknowledge_processed_feedback, apply_pending_feedback
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


def test_feedback_sync_acknowledges_cloudflare_only_after_profile_is_updated(config, tmp_path, monkeypatch):
    with open_dict(config):
        config.interest.enabled = True
        config.interest.state_path = str(tmp_path / "interest_profile.json")

    acknowledgements = []

    class StubGitHubFeedbackClient:
        def fetch_feedback(self):
            return []

        def close_feedback_issues(self, items):
            assert items == []

    cloudflare_event = {
        "feedback_id": 101,
        "paper_id": "2607.12345",
        "run_id": "pages-20260723T010203Z",
        "action": "like",
        "source": "cloudflare",
        "paper": {
            "title": "Robot Planning with World Models",
            "keywords": ["robot planning", "world model"],
            "matched_keywords": ["world model"],
        },
    }

    class StubCloudflareFeedbackClient:
        def fetch_feedback(self):
            return [cloudflare_event]

        def acknowledge_feedback(self, items):
            acknowledgements.extend(items)

    monkeypatch.setattr(
        "zotero_arxiv_daily.feedback_sync.GitHubFeedbackClient.from_config",
        lambda _: StubGitHubFeedbackClient(),
    )
    monkeypatch.setattr(
        "zotero_arxiv_daily.feedback_sync.CloudflareFeedbackClient.from_config",
        lambda _: StubCloudflareFeedbackClient(),
    )

    updated_profile, applied = apply_pending_feedback(config)

    assert len(applied) == 1
    assert "robot planning" in updated_profile.top_keywords()
    assert [item["feedback_id"] for item in acknowledgements] == [101]
    assert (tmp_path / "interest_profile.json").exists()


def test_feedback_sync_keeps_cloudflare_processing_when_github_fails(config, tmp_path, monkeypatch):
    with open_dict(config):
        config.interest.enabled = True
        config.interest.state_path = str(tmp_path / "interest_profile.json")

    class FailingGitHubFeedbackClient:
        def fetch_feedback(self):
            raise RuntimeError("GitHub unavailable")

        def close_feedback_issues(self, items):
            assert items == []

    acknowledgements = []

    class StubCloudflareFeedbackClient:
        def fetch_feedback(self):
            return [
                {
                    "feedback_id": 102,
                    "paper_id": "2607.54321",
                    "run_id": "pages-20260723T010203Z",
                    "action": "interested",
                    "source": "cloudflare",
                    "paper": {
                        "title": "Embodied Robot Planning",
                        "keywords": ["embodied ai"],
                        "matched_keywords": [],
                    },
                }
            ]

        def acknowledge_feedback(self, items):
            acknowledgements.extend(items)

    monkeypatch.setattr(
        "zotero_arxiv_daily.feedback_sync.GitHubFeedbackClient.from_config",
        lambda _: FailingGitHubFeedbackClient(),
    )
    monkeypatch.setattr(
        "zotero_arxiv_daily.feedback_sync.CloudflareFeedbackClient.from_config",
        lambda _: StubCloudflareFeedbackClient(),
    )

    _, applied = apply_pending_feedback(config)

    assert len(applied) == 1
    assert [item["feedback_id"] for item in acknowledgements] == [102]


def test_feedback_sync_can_defer_cloudflare_ack_until_after_profile_commit(config, tmp_path, monkeypatch):
    with open_dict(config):
        config.interest.enabled = True
        config.interest.state_path = str(tmp_path / "interest_profile.json")

    acknowledgements = []
    cloudflare_event = {
        "feedback_id": 103,
        "paper_id": "2607.98765",
        "run_id": "pages-20260723T010203Z",
        "action": "like",
        "source": "cloudflare",
        "paper": {
            "title": "Visual World Models",
            "keywords": ["visual world model"],
            "matched_keywords": [],
        },
    }

    class StubGitHubFeedbackClient:
        def fetch_feedback(self):
            return []

        def close_feedback_issues(self, items):
            assert items == []

    class StubCloudflareFeedbackClient:
        def fetch_feedback(self):
            return [cloudflare_event]

        def acknowledge_feedback(self, items):
            acknowledgements.extend(items)

    github_client = StubGitHubFeedbackClient()
    cloudflare_client = StubCloudflareFeedbackClient()
    monkeypatch.setattr(
        "zotero_arxiv_daily.feedback_sync.GitHubFeedbackClient.from_config",
        lambda _: github_client,
    )
    monkeypatch.setattr(
        "zotero_arxiv_daily.feedback_sync.CloudflareFeedbackClient.from_config",
        lambda _: cloudflare_client,
    )

    _, applied = apply_pending_feedback(config, acknowledge=False)

    assert len(applied) == 1
    assert acknowledgements == []
    assert (tmp_path / "interest_profile.json").exists()

    acknowledged = acknowledge_processed_feedback(config)

    assert acknowledged == 1
    assert [item["feedback_id"] for item in acknowledgements] == [103]
