"""Tests for the GitHub Pages daily-fetch arXiv script."""

from pathlib import Path
import sys


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import arxiv_fetcher  # noqa: E402


RSS_XML_WITH_ABSTRACT_INSTITUTION = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>cs.AI updates</title>
  <entry>
    <id>oai:arXiv.org:2606.00001v1</id>
    <title>Institution Mentions Are Not Affiliations</title>
    <summary>
      We compare against a benchmark from MIT and a dataset collected by Stanford University.
      The authors do not list affiliations in this feed entry.
    </summary>
    <author>
      <name>Ada Lovelace</name>
    </author>
    <category term="cs.AI" />
    <published>2026-06-04T00:00:00Z</published>
  </entry>
</feed>
"""


API_XML_WITH_AFFILIATIONS = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2606.00001v2</id>
    <author>
      <name>Ada Lovelace</name>
      <arxiv:affiliation>  MIT CSAIL  </arxiv:affiliation>
    </author>
    <author>
      <name>Grace Hopper</name>
      <arxiv:affiliation>OpenAI</arxiv:affiliation>
    </author>
  </entry>
</feed>
"""


class FakeResponse:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def test_get_latest_papers_does_not_infer_affiliations_from_abstract(monkeypatch):
    monkeypatch.setattr(
        arxiv_fetcher.urllib.request,
        "urlopen",
        lambda req, timeout: FakeResponse(RSS_XML_WITH_ABSTRACT_INSTITUTION),
    )
    monkeypatch.setattr(arxiv_fetcher, "_enrich_affiliations_from_arxiv_api", lambda papers: 0)

    papers = arxiv_fetcher.get_latest_papers("cs.AI")

    assert papers[0]["arxiv_id"] == "2606.00001"
    assert papers[0]["affiliations"] == []


def test_parse_api_affiliations_uses_explicit_metadata_only():
    affiliations = arxiv_fetcher._parse_api_affiliations(API_XML_WITH_AFFILIATIONS)

    assert affiliations == {
        "2606.00001": [
            {"author": "Ada Lovelace", "affiliation": "MIT CSAIL"},
            {"author": "Grace Hopper", "affiliation": "OpenAI"},
        ]
    }


def test_enrich_affiliations_from_arxiv_api_attaches_by_arxiv_id(monkeypatch):
    papers = [
        {"arxiv_id": "2606.00001", "affiliations": []},
        {"arxiv_id": "2606.00002", "affiliations": []},
    ]
    monkeypatch.setattr(
        arxiv_fetcher,
        "_fetch_arxiv_api_affiliations",
        lambda ids: {"2606.00001": [{"author": "Ada Lovelace", "affiliation": "MIT CSAIL"}]},
    )

    enriched = arxiv_fetcher._enrich_affiliations_from_arxiv_api(papers)

    assert enriched == 1
    assert papers[0]["affiliations"] == [{"author": "Ada Lovelace", "affiliation": "MIT CSAIL"}]
    assert papers[1]["affiliations"] == []


def test_filter_by_institutions_ignores_abstract_mentions(monkeypatch):
    monkeypatch.setattr(arxiv_fetcher, "get_followed_institutions", lambda: ["MIT"])
    papers = [
        {
            "arxiv_id": "2606.00001",
            "authors": ["Ada Lovelace"],
            "abstract": "This abstract mentions MIT but has no affiliation metadata.",
            "affiliations": [],
        },
        {
            "arxiv_id": "2606.00002",
            "authors": ["Grace Hopper"],
            "abstract": "No institution mention.",
            "affiliations": [{"author": "Grace Hopper", "affiliation": "MIT CSAIL"}],
        },
    ]

    matched = arxiv_fetcher.filter_by_institutions(papers)

    assert [paper["arxiv_id"] for paper in matched] == ["2606.00002"]
