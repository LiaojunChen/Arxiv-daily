"""Validation tests for the GitHub Pages paper-data pipeline."""

from pathlib import Path
import sys

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_papers  # noqa: E402


def _paper(**overrides):
    paper = {
        "arxiv_id": "2607.00001",
        "title": "A valid paper",
        "authors": ["Ada Lovelace"],
        "affiliations": [],
        "categories": ["cs.AI"],
        "abstract": "A valid abstract.",
    }
    paper.update(overrides)
    return paper


def test_validate_display_data_accepts_valid_primary_papers():
    fetch_papers._validate_display_data([_paper()], [], [])


def test_validate_display_data_rejects_empty_deployment():
    with pytest.raises(RuntimeError, match="No papers were fetched"):
        fetch_papers._validate_display_data([], [], [])


def test_validate_display_data_rejects_schema_drift_that_drops_all_authors():
    with pytest.raises(ValueError, match="missing authors"):
        fetch_papers._validate_display_data([_paper(authors=[])], [], [])


def test_validate_display_data_rejects_missing_identity_fields():
    with pytest.raises(ValueError, match="arxiv_id/title"):
        fetch_papers._validate_display_data([_paper(title="")], [], [])


def test_validate_display_data_rejects_malformed_arrays():
    with pytest.raises(ValueError, match="malformed list/text fields"):
        fetch_papers._validate_display_data([_paper(authors=None)], [], [])
