"""Tests for scripts.affiliation_extractor."""

from pathlib import Path
import sys


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import affiliation_extractor  # noqa: E402


class _DownloadResponse:
    status_code = 200

    def __init__(self, content_length: int):
        self.headers = {"Content-Length": str(content_length)}
        self.iterated = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        self.iterated = True
        yield b"should not be downloaded"


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


def test_extract_affiliations_from_latex_commands():
    paper_text = r"""
    \author{Ada Lovelace}
    \affiliation{Department of Computer Science, MIT}
    \author{Grace Hopper}
    \affil{OpenAI Research}
    """

    affiliations = affiliation_extractor.extract_affiliations_from_paper_text(
        paper_text,
        ["Ada Lovelace", "Grace Hopper"],
    )

    assert affiliations == [
        {"author": "Ada Lovelace", "affiliation": "Department of Computer Science, MIT"},
        {"author": "Grace Hopper", "affiliation": "OpenAI Research"},
    ]


def test_clean_latex_affiliation_removes_leading_markers():
    assert (
        affiliation_extractor._clean_latex_affiliation("1 University of California, Los Angeles")
        == "University of California, Los Angeles"
    )


def test_clean_latex_affiliation_removes_stray_backslashes():
    assert (
        affiliation_extractor._clean_latex_affiliation(r"Nanyang Technological University \\")
        == "Nanyang Technological University"
    )


def test_clean_latex_affiliation_removes_structured_address_noise():
    raw = (
        "organization= Department of Computer Science, Tsinghua University, "
        "addressline= Haidian District, city= Beijing, postcode= 100084, country= China"
    )

    assert affiliation_extractor._clean_latex_affiliation(raw) == (
        "Department of Computer Science, Tsinghua University"
    )


def test_html_affiliation_spans_are_preserved_for_deterministic_extraction():
    html = b"""
    <html><body>
      <span class="ltx_contact ltx_role_affiliation">MIT CSAIL</span>
      <div class="ltx_abstract">
        A sufficiently long abstract for the HTML quality threshold.
        This sentence is repeated to model a real arXiv HTML response.
        A sufficiently long abstract for the HTML quality threshold.
        This sentence is repeated to model a real arXiv HTML response.
        A sufficiently long abstract for the HTML quality threshold.
      </div>
    </body></html>
    """

    paper_text = affiliation_extractor._extract_text_from_html_bytes(html)
    affiliations = affiliation_extractor.extract_affiliations_from_paper_text(
        paper_text,
        ["Ada Lovelace"],
    )

    assert affiliations == [
        {"author": "Ada Lovelace", "affiliation": "MIT CSAIL"}
    ]


def test_download_limited_skips_oversized_source_before_streaming(monkeypatch):
    response = _DownloadResponse(affiliation_extractor.MAX_DOWNLOAD_BYTES + 1)
    monkeypatch.setattr(
        affiliation_extractor.requests,
        "get",
        lambda *args, **kwargs: response,
    )

    assert affiliation_extractor._download_limited("https://arxiv.org/e-print/test") is None
    assert response.iterated is False


def test_extract_affiliations_from_ieee_author_sentence():
    paper_text = r"""
    \IEEEauthorblockA{Ada Lovelace and Grace Hopper are with
    eBRAIN Lab, Division of Engineering, New York University Abu Dhabi,
    United Arab Emirates.}
    """

    affiliations = affiliation_extractor.extract_affiliations_from_paper_text(
        paper_text,
        ["Ada Lovelace", "Grace Hopper"],
    )

    assert affiliations == [
        {
            "author": "Ada Lovelace",
            "affiliation": "eBRAIN Lab, Division of Engineering, New York University Abu Dhabi, United Arab Emirates.",
        }
    ]


def test_extract_affiliations_from_numbered_author_block():
    paper_text = r"""
    \author{Han Zhu 1 , Chengkun Cai 2* , Yuanfeng Song 3
    1 The Hong Kong University of Science and Technology
    2 ByteDance, China
    3 University College London}
    """

    affiliations = affiliation_extractor.extract_affiliations_from_paper_text(
        paper_text,
        ["Han Zhu", "Chengkun Cai", "Yuanfeng Song"],
    )

    assert affiliations == [
        {"author": "Han Zhu", "affiliation": "The Hong Kong University of Science and Technology"},
        {"author": "Chengkun Cai", "affiliation": "ByteDance, China"},
        {"author": "Yuanfeng Song", "affiliation": "University College London"},
    ]


def test_extract_affiliations_from_inline_numbered_author_block():
    paper_text = r"""
    \author{Han Zhu 1 , Chengkun Cai 2* , Yuanfeng Song 3
    1 The Hong Kong University of Science and Technology 2 ByteDance, China 3 University College London}
    """

    affiliations = affiliation_extractor.extract_affiliations_from_paper_text(
        paper_text,
        ["Han Zhu", "Chengkun Cai", "Yuanfeng Song"],
    )

    assert affiliations == [
        {"author": "Han Zhu", "affiliation": "The Hong Kong University of Science and Technology"},
        {"author": "Chengkun Cai", "affiliation": "ByteDance, China"},
        {"author": "Yuanfeng Song", "affiliation": "University College London"},
    ]


def test_enrich_affiliations_normalizes_existing_affiliations(monkeypatch):
    paper = {
        "arxiv_id": "2606.00001",
        "authors": ["Ada Lovelace", "Grace Hopper"],
        "affiliations": [
            "MIT",
            {"author": "Grace Hopper", "institution": "OpenAI"},
            {"author": "Ignored", "affiliation": ""},
        ],
    }
    monkeypatch.setattr(affiliation_extractor, "AFFILIATION_MAX_PAPERS", 5)
    monkeypatch.setattr(
        affiliation_extractor,
        "fetch_paper_text",
        lambda arxiv_id: (_ for _ in ()).throw(AssertionError("should not fetch source")),
    )

    enriched = affiliation_extractor.enrich_affiliations_for_display_papers([[paper]])

    assert enriched == 0
    assert paper["affiliations"] == [
        {"author": "Ada Lovelace", "affiliation": "MIT"},
        {"author": "Grace Hopper", "affiliation": "OpenAI"},
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


def test_enrich_affiliations_runs_deterministic_extraction_without_openai_key(monkeypatch):
    paper = {"arxiv_id": "2606.00001", "authors": ["Ada Lovelace"], "affiliations": []}
    monkeypatch.setattr(affiliation_extractor, "OPENAI_API_KEY", "")
    monkeypatch.setattr(affiliation_extractor, "AFFILIATION_MAX_PAPERS", 5)
    monkeypatch.setattr(
        affiliation_extractor,
        "fetch_paper_text",
        lambda arxiv_id: r"\affiliation{MIT CSAIL}",
    )

    enriched = affiliation_extractor.enrich_affiliations_for_display_papers([[paper]])

    assert enriched == 1
    assert paper["affiliations"] == [
        {"author": "Ada Lovelace", "affiliation": "MIT CSAIL"}
    ]


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


def test_enrichment_budget_is_shared_fairly_and_duplicates_are_propagated(monkeypatch):
    similar_first = {
        "arxiv_id": "2606.00001",
        "authors": ["Ada Lovelace"],
        "affiliations": [],
    }
    similar_second = {
        "arxiv_id": "2606.00002",
        "authors": ["Grace Hopper"],
        "affiliations": [],
    }
    hf_first = {
        "arxiv_id": "2606.00003",
        "authors": ["Alan Turing"],
        "affiliations": [],
    }
    duplicate = {
        "arxiv_id": "2606.00001",
        "authors": ["Ada Lovelace"],
        "affiliations": [],
    }
    monkeypatch.setattr(affiliation_extractor, "OPENAI_API_KEY", "")
    monkeypatch.setattr(affiliation_extractor, "AFFILIATION_MAX_PAPERS", 2)
    monkeypatch.setattr(
        affiliation_extractor,
        "fetch_paper_text",
        lambda arxiv_id: rf"\affiliation{{University {arxiv_id}}}",
    )

    enriched = affiliation_extractor.enrich_affiliations_for_display_papers(
        [[similar_first, similar_second], [hf_first, duplicate]]
    )

    assert enriched == 2
    assert similar_first["affiliations"]
    assert hf_first["affiliations"]
    assert similar_second["affiliations"] == []
    assert duplicate["affiliations"] == similar_first["affiliations"]
