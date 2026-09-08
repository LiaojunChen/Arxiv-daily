"""Prepare and register a snapshot before either delivery surface consumes it."""
import os
import sys
from pathlib import Path
import hydra
from omegaconf import DictConfig
from .feedback_sync import apply_pending_feedback


@hydra.main(version_base=None, config_path="../../config", config_name="default")
def main(config: DictConfig):
    profile, _ = apply_pending_feedback(config, acknowledge=False)
    expected_path = Path("data/interest_profile.json").resolve()
    if profile.state_path.resolve() != expected_path and os.environ.get("GITHUB_ACTIONS"):
        raise ValueError("The scheduled snapshot workflow persists data/interest_profile.json; use that interest.state_path.")
    profile.save()
    os.environ["INTEREST_PROFILE_PATH"] = str(profile.state_path.resolve())
    if not os.environ.get("ARXIV_QUERY", "").strip():
        os.environ["ARXIV_QUERY"] = "+".join(config.source.arxiv.category or [])
    if not os.environ.get("MAX_PAPER_NUM", "").strip():
        os.environ["MAX_PAPER_NUM"] = str(config.interest.get("primary_paper_count", 50) + config.interest.get("exploration_paper_count", 10))
    os.environ["EXPLORATION_PAPER_COUNT"] = str(config.interest.get("exploration_paper_count", 10))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from daily_pipeline import generate
    snapshot = generate()
    profile.data.setdefault("runs", {})[snapshot["run_id"]] = {
        "run_id": snapshot["run_id"], "generated_at": snapshot["updated_at"],
        "papers": {p["arxiv_id"]: {key: p.get(key, []) for key in ("title", "keywords", "matched_keywords")}
                   for p in snapshot["candidate_papers"] + snapshot["similar_papers"]},
    }
    profile.data["updated_at"] = snapshot["updated_at"]
    profile.save()


if __name__ == "__main__":
    main()
