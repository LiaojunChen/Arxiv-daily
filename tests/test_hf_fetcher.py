"""Tests for scripts.hf_fetcher."""

from pathlib import Path
import sys
from datetime import datetime


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


def test_fetch_hf_daily_papers_falls_back_to_previous_non_empty_date(monkeypatch):
    requested_dates = []

    # Use standard paper dicts because this test targets date selection only.
    paper = hf_fetcher._parse_hf_paper(_hf_item("2607.13285"))
    monkeypatch.setattr(hf_fetcher, "HF_FALLBACK_DAYS", 3)

    def fake_fetch(date):
        requested_dates.append(date)
        return [] if date == "2026-07-18" else [paper]

    monkeypatch.setattr(hf_fetcher, "_fetch_hf_papers_for_date", fake_fetch)
    monkeypatch.setattr(
        hf_fetcher,
        "datetime",
        type(
            "FixedDateTime",
            (datetime,),
            {"now": classmethod(lambda cls, tz=None: cls(2026, 7, 18, tzinfo=tz))},
        ),
    )

    papers = hf_fetcher.fetch_hf_daily_papers()

    assert requested_dates == ["2026-07-18", "2026-07-17"]
    assert papers == [paper]


def test_explicit_hf_date_does_not_fall_back(monkeypatch):
    requested_dates = []
    monkeypatch.setattr(hf_fetcher, "HF_FALLBACK_DAYS", 7)
    monkeypatch.setattr(
        hf_fetcher,
        "_fetch_hf_papers_for_date",
        lambda date: requested_dates.append(date) or [],
    )

    assert hf_fetcher.fetch_hf_daily_papers(date="2026-07-18") == []
    assert requested_dates == ["2026-07-18"]
