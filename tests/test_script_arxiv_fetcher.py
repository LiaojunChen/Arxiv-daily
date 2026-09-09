"""Tests for the GitHub Pages daily-fetch arXiv script."""

from pathlib import Path
import sys
import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import arxiv_fetcher  # noqa: E402
import source_http


RSS_XML_WITH_ABSTRACT_INSTITUTION = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns:dc="http://purl.org/dc/elements/1.1/">
  <title>cs.AI updates</title>
  <entry>
    <id>oai:arXiv.org:2606.00001v1</id>
    <title>Institution Mentions Are Not Affiliations</title>
    <summary>
      We compare against a benchmark from MIT and a dataset collected by Stanford University.
      The authors do not list affiliations in this feed entry.
    </summary>
    <dc:creator>Ada Lovelace, Grace Hopper</dc:creator>
    <category term="cs.AI" />
    <published>2026-06-04T00:00:00Z</published>
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
    papers = arxiv_fetcher.get_latest_papers("cs.AI")

    assert papers[0]["arxiv_id"] == "2606.00001"
    assert papers[0]["authors"] == ["Ada Lovelace", "Grace Hopper"]
    assert papers[0]["affiliations"] == []


def test_empty_feed_preserves_upstream_date_and_cache_evidence(monkeypatch):
    body = '<feed xmlns="http://www.w3.org/2005/Atom"><updated>2026-09-08T04:00:20Z</updated></feed>'
    def respond(request, timeout):
        assert request.get_header("Cache-control") == "no-cache, max-age=0"
        response = FakeResponse(body)
        response.headers = {"Age": "83251", "X-Cache": "HIT, HIT"}
        return response
    monkeypatch.setattr(source_http.urllib.request, "urlopen", respond)
    assert arxiv_fetcher.get_latest_papers("cs.CV") == []
    evidence = source_http.fetches[-1]
    assert evidence["empty_feed"]
    assert evidence["feed_updated"] == "2026-09-08T04:00:20Z"
    assert evidence["cache_age_seconds"] == "83251"


def test_rate_limit_is_not_reported_as_an_empty_feed(monkeypatch):
    from urllib.error import HTTPError
    calls = []
    def limited(request, timeout):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 429, "Rate limited", {"Retry-After": "120"}, None)
    monkeypatch.setattr(source_http.urllib.request, "urlopen", limited)
    with pytest.raises(HTTPError):
        arxiv_fetcher.get_latest_papers("cs.CV")
    assert len(calls) == 1
    assert source_http.fetches[-1]["status"] == 429
    assert source_http.fetches[-1]["retry_after"] == "120"


@pytest.mark.parametrize("body", ['<html>Unavailable</html>',
    '<feed xmlns="http://www.w3.org/2005/Atom"><title>Feed error: invalid category</title></feed>'])
def test_invalid_rss_response_is_not_empty_success(monkeypatch, body):
    monkeypatch.setattr(source_http.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(body))
    with pytest.raises(ValueError):
        arxiv_fetcher.get_latest_papers("cs.CV")


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
