"""Synchronise submitted GitHub feedback into the local interest profile.

This module deliberately has no SMTP, retriever, or LLM dependency.  It is
used by the daily mail run as a best-effort fallback and by a dedicated GitHub
Actions workflow, so feedback continues to learn even when email is disabled.
"""

from __future__ import annotations

import logging
import os
import sys

import hydra
from loguru import logger
from omegaconf import DictConfig

from .cloudflare_feedback import CloudflareFeedbackClient
from .feedback import GitHubFeedbackClient
from .interest_profile import InterestProfile


def apply_pending_feedback(
    config: DictConfig,
    *,
    acknowledge: bool | None = None,
) -> tuple[InterestProfile, list[dict]]:
    """Fetch and persist feedback, optionally acknowledging providers afterwards.

    GitHub Actions defers the acknowledgement until the profile commit is
    pushed. Local callers retain the convenient immediate acknowledgement by
    default, while still using durable feedback IDs for idempotency.
    """
    if acknowledge is None:
        acknowledge = not _env_enabled("DEFER_FEEDBACK_ACK")
    profile = InterestProfile.from_config(config)
    github_client = GitHubFeedbackClient.from_config(config)
    cloudflare_client = CloudflareFeedbackClient.from_config(config)

    try:
        github_feedback = github_client.fetch_feedback()
    except Exception as exc:  # A delivery run must still be able to recommend papers.
        logger.warning(f"Failed to collect GitHub feedback; continuing with current profile: {exc}")
        github_feedback = []

    try:
        cloudflare_feedback = cloudflare_client.fetch_feedback()
    except Exception as exc:  # A GitHub API failure must not block web feedback.
        logger.warning(f"Failed to collect Cloudflare feedback; continuing with current profile: {exc}")
        cloudflare_feedback = []

    feedback_items = github_feedback + cloudflare_feedback

    applied = profile.apply_feedback(feedback_items)
    if not applied:
        logger.info("No new feedback to apply.")
    else:
        # Persist before either provider is acknowledged. A retry may leave an
        # event open, but it will never lose a submitted preference because the
        # processed IDs are durable in the profile file.
        profile.save()

    if acknowledge:
        _acknowledge_processed_feedback(
            profile,
            github_client,
            cloudflare_client,
            github_feedback,
            cloudflare_feedback,
        )
    return profile, applied


def acknowledge_processed_feedback(config: DictConfig) -> int:
    """Acknowledge provider events already committed to the interest profile."""
    profile = InterestProfile.from_config(config)
    github_client = GitHubFeedbackClient.from_config(config)
    cloudflare_client = CloudflareFeedbackClient.from_config(config)

    try:
        github_feedback = github_client.fetch_feedback()
    except Exception as exc:
        logger.warning(f"Failed to collect GitHub feedback for acknowledgement: {exc}")
        github_feedback = []
    try:
        cloudflare_feedback = cloudflare_client.fetch_feedback()
    except Exception as exc:
        logger.warning(f"Failed to collect Cloudflare feedback for acknowledgement: {exc}")
        cloudflare_feedback = []
    return _acknowledge_processed_feedback(
        profile,
        github_client,
        cloudflare_client,
        github_feedback,
        cloudflare_feedback,
    )


def _acknowledge_processed_feedback(
    profile: InterestProfile,
    github_client: GitHubFeedbackClient,
    cloudflare_client: CloudflareFeedbackClient,
    github_feedback: list[dict],
    cloudflare_feedback: list[dict],
) -> int:
    processed = {str(item) for item in profile.data.get("processed_feedback", [])}
    github_processed = [
        item for item in github_feedback if profile.feedback_key(item) in processed
    ]
    cloudflare_processed = [
        item for item in cloudflare_feedback if profile.feedback_key(item) in processed
    ]
    try:
        github_client.close_feedback_issues(github_processed)
    except Exception as exc:
        logger.warning(f"Failed to close processed GitHub feedback issue(s): {exc}")
    try:
        cloudflare_client.acknowledge_feedback(cloudflare_processed)
    except Exception as exc:
        logger.warning(f"Failed to acknowledge processed Cloudflare feedback event(s): {exc}")
    return len(github_processed) + len(cloudflare_processed)


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _configure_logging() -> None:
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    for logger_name in logging.root.manager.loggerDict:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


@hydra.main(version_base=None, config_path="../../config", config_name="default")
def main(config: DictConfig) -> None:
    _configure_logging()
    if not config.interest.get("enabled", False):
        logger.info("Interest mode is disabled; feedback sync has nothing to update.")
        return
    if _env_enabled("ACKNOWLEDGE_PROCESSED_FEEDBACK"):
        acknowledged = acknowledge_processed_feedback(config)
        logger.info(f"Feedback acknowledgement complete; handled {acknowledged} item(s).")
        return
    _, applied = apply_pending_feedback(config)
    logger.info(f"Feedback sync complete; applied {len(applied)} item(s).")


if __name__ == "__main__":
    main()
