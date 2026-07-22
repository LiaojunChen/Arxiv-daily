"""Synchronise submitted GitHub feedback into the local interest profile.

This module deliberately has no SMTP, retriever, or LLM dependency.  It is
used by the daily mail run as a best-effort fallback and by a dedicated GitHub
Actions workflow, so feedback continues to learn even when email is disabled.
"""

from __future__ import annotations

import logging
import sys

import hydra
from loguru import logger
from omegaconf import DictConfig

from .feedback import GitHubFeedbackClient
from .interest_profile import InterestProfile


def apply_pending_feedback(config: DictConfig) -> tuple[InterestProfile, list[dict]]:
    """Fetch, apply, persist, and optionally close all newly submitted feedback."""
    profile = InterestProfile.from_config(config)
    client = GitHubFeedbackClient.from_config(config)
    try:
        feedback_items = client.fetch_feedback()
    except Exception as exc:  # A delivery run must still be able to recommend papers.
        logger.warning(f"Failed to collect GitHub feedback; continuing with current profile: {exc}")
        return profile, []

    applied = profile.apply_feedback(feedback_items)
    if not applied:
        logger.info("No new GitHub feedback to apply.")
        return profile, []

    # Persist before closing issues.  A retry may leave an issue open, but it
    # will never lose a submitted preference because processed IDs are durable.
    profile.save()
    applied_keys = {item["feedback_key"] for item in applied}
    client.close_feedback_issues(
        [item for item in feedback_items if profile.feedback_key(item) in applied_keys]
    )
    return profile, applied


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
    _, applied = apply_pending_feedback(config)
    logger.info(f"Feedback sync complete; applied {len(applied)} item(s).")


if __name__ == "__main__":
    main()
