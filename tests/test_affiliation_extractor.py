"""Tests for scripts.affiliation_extractor."""

from pathlib import Path
import sys


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import affiliation_extractor  # noqa: E402


def test_normalize_affiliation_response_handles_strings_and_objects():
    raw = [
        "MIT",
        {"author": "Grace Hopper", "affiliation": "OpenAI"},
        {"name": "Alan Turing", "institution": "Princeton University"},
        {"author": "Grace Hopper", "affiliation": "openai"},
        {"author": "No Aff", "affiliation": "Unknown"},
    ]

    affiliations = affiliation_extractor._normalize_affiliation_response(
        raw,
        ["Ada Lovelace", "Grace Hopper", "Alan Turing"],
    )

    assert affiliations == [
        {"author": "Ada Lovelace", "affiliation": "MIT"},
        {"author": "Grace Hopper", "affiliation": "OpenAI"},
        {"author": "Alan Turing", "affiliation": "Princeton University"},
    ]


def test_enrich_affiliations_for_display_papers_updates_missing_affiliations(monkeypatch):
    paper = {
        "arxiv_id": "2606.00001",
        "title": "A Paper",
        "authors": ["Ada Lovelace"],
        "affiliations": [],
    }
    monkeypatch.setattr(affiliation_extractor, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(affiliation_extractor, "AFFILIATION_MAX_PAPERS", 5)
    monkeypatch.setattr(affiliation_extractor, "fetch_paper_text", lambda arxiv_id: "source text")
    monkeypatch.setattr(
        affiliation_extractor,
        "_call_llm_for_affiliations",
        lambda p, text: [{"author": "Ada Lovelace", "affiliation": "MIT CSAIL"}],
    )

    enriched = affiliation_extractor.enrich_affiliations_for_display_papers([[paper]])

    assert enriched == 1
    assert paper["affiliations"] == [{"author": "Ada Lovelace", "affiliation": "MIT CSAIL"}]


def test_enrich_affiliations_skips_without_openai_key(monkeypatch):
    paper = {"arxiv_id": "2606.00001", "authors": ["Ada Lovelace"], "affiliations": []}
    monkeypatch.setattr(affiliation_extractor, "OPENAI_API_KEY", "")

    enriched = affiliation_extractor.enrich_affiliations_for_display_papers([[paper]])

    assert enriched == 0
    assert paper["affiliations"] == []


def test_enrich_affiliations_continues_when_source_read_fails(monkeypatch):
    bad_paper = {"arxiv_id": "2606.00001", "authors": ["Ada Lovelace"], "affiliations": []}
    good_paper = {"arxiv_id": "2606.00002", "authors": ["Grace Hopper"], "affiliations": []}
    monkeypatch.setattr(affiliation_extractor, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(affiliation_extractor, "AFFILIATION_MAX_PAPERS", 5)

    def fetch_text(arxiv_id):
        if arxiv_id == "2606.00001":
            raise EOFError("truncated gzip")
        return "source text"

    monkeypatch.setattr(affiliation_extractor, "fetch_paper_text", fetch_text)
    monkeypatch.setattr(
        affiliation_extractor,
        "_call_llm_for_affiliations",
        lambda p, text: [{"author": "Grace Hopper", "affiliation": "OpenAI"}],
    )

    enriched = affiliation_extractor.enrich_affiliations_for_display_papers([[bad_paper, good_paper]])

    assert enriched == 1
    assert bad_paper["affiliations"] == []
    assert good_paper["affiliations"] == [{"author": "Grace Hopper", "affiliation": "OpenAI"}]
