"""Tests for scripts.hf_fetcher."""

from pathlib import Path
import sys


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import hf_fetcher  # noqa: E402


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _hf_item(arxiv_id: str) -> dict:
    return {
        "paper": {
            "id": arxiv_id,
            "title": f"Paper {arxiv_id}",
            "authors": ["Ada Lovelace"],
            "summary": "A paper summary.",
        },
        "publishedAt": "2026-06-05T00:00:00.000Z",
        "upvotes": 1,
    }


def test_fetch_hf_daily_papers_respects_max_papers(monkeypatch):
    pages = {
        1: [_hf_item(f"2606.{i:05d}") for i in range(50)],
        2: [_hf_item(f"2606.{i:05d}") for i in range(50, 100)],
    }
    requested_pages = []

    def fake_get(url, timeout):
        page = int(url.split("page=", 1)[1].split("&", 1)[0])
        requested_pages.append(page)
        return _FakeResponse(pages[page])

    monkeypatch.setattr(hf_fetcher, "HF_MAX_PAPERS", 60)
    monkeypatch.setattr(hf_fetcher, "HF_PAGE_SIZE", 50)
    monkeypatch.setattr(hf_fetcher.requests, "get", fake_get)

    papers = hf_fetcher.fetch_hf_daily_papers(date="2026-06-05")

    assert len(papers) == 60
    assert requested_pages == [1, 2]


def test_fetch_hf_daily_papers_stops_on_duplicate_page(monkeypatch):
    repeated_page = [_hf_item(f"2606.{i:05d}") for i in range(50)]
    requested_pages = []

    def fake_get(url, timeout):
        page = int(url.split("page=", 1)[1].split("&", 1)[0])
        requested_pages.append(page)
        return _FakeResponse(repeated_page)

    monkeypatch.setattr(hf_fetcher, "HF_MAX_PAPERS", 100)
    monkeypatch.setattr(hf_fetcher, "HF_PAGE_SIZE", 50)
    monkeypatch.setattr(hf_fetcher.requests, "get", fake_get)

    papers = hf_fetcher.fetch_hf_daily_papers(date="2026-06-05")

    assert len(papers) == 50
    assert requested_pages == [1, 2]
