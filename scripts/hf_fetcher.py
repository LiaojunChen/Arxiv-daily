"""
HuggingFace Daily Papers fetcher.
Calls the HF public API to retrieve curated daily papers.
No authentication required.
"""

import requests
import os
from datetime import datetime, timedelta, timezone


HF_API_BASE = "https://huggingface.co/api/daily_papers"
HF_TIMEOUT = 15
HF_PAGE_SIZE = int(os.environ.get("HF_PAGE_SIZE") or "50")
HF_MAX_PAPERS = int(os.environ.get("HF_MAX_PAPERS") or "50")
HF_FALLBACK_DAYS = int(os.environ.get("HF_FALLBACK_DAYS") or "7")


def _parse_hf_paper(item: dict) -> dict:
    """Convert a HF daily paper item to our standard paper dict."""
    paper = item.get("paper", {})
    arxiv_id = paper.get("id", "") or paper.get("arxivId", "")

    # Authors from HF: may be a list of dicts with name, or list of strings
    authors_raw = paper.get("authors", [])
    authors = []
    affiliations = []
    for a in authors_raw:
        if isinstance(a, dict):
            name = a.get("name", "")
            aff = a.get("affiliation", "")
            authors.append(name)
            if aff:
                affiliations.append({"author": name, "affiliation": aff})
        else:
            authors.append(str(a))

    categories = paper.get("tags", []) or paper.get("categories", [])

    # Get the best URL available
    paper_url = paper.get("paperUrl", "") or f"https://arxiv.org/abs/{arxiv_id}"
    pdf_url = paper.get("pdfUrl", "") or f"https://arxiv.org/pdf/{arxiv_id}"

    published = item.get("publishedAt", "")

    return {
        "arxiv_id": arxiv_id,
        "title": paper.get("title", ""),
        "authors": authors,
        "affiliations": affiliations,
        "abstract": paper.get("summary", "") or paper.get("abstract", ""),
        "categories": [c if isinstance(c, str) else c.get("label", str(c)) for c in categories],
        "published": published,
        "pdf_url": pdf_url,
        "abstract_url": paper_url,
        "hf_upvotes": item.get("upvotes", 0),
        "hf_submitter": item.get("submittedBy", {}).get("user", "") if isinstance(item.get("submittedBy"), dict) else "",
        "source": "huggingface",
    }


def _fetch_hf_papers_for_date(date: str) -> list[dict]:
    """Fetch one explicit Hugging Face daily-paper date."""
    all_papers = []
    seen_ids = set()
    page = 1

    while len(all_papers) < HF_MAX_PAPERS:
        limit = min(HF_PAGE_SIZE, HF_MAX_PAPERS - len(all_papers))
        url = f"{HF_API_BASE}?date={date}&page={page}&limit={limit}"
        print(f"[INFO] Fetching HF papers for {date}: page={page}")

        try:
            resp = requests.get(url, timeout=HF_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[ERROR] HF papers API request failed for {date}: {e}")
            break

        if not data:
            break

        new_on_page = 0
        for item in data:
            paper = _parse_hf_paper(item)
            key = paper.get("arxiv_id") or paper.get("title")
            if not key or key in seen_ids:
                continue
            seen_ids.add(key)
            all_papers.append(paper)
            new_on_page += 1
            if len(all_papers) >= HF_MAX_PAPERS:
                break

        if new_on_page == 0:
            print("[WARN] HF papers page returned no new papers; stopping pagination.")
            break
        if len(data) < limit:
            break
        page += 1

    return all_papers


def fetch_hf_daily_papers(date: str = None) -> list[dict]:
    """
    Fetch HuggingFace daily papers.

    Args:
        date: YYYY-MM-DD format. Defaults to today (UTC).
    """
    requested_date = (
        datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if date
        else datetime.now(timezone.utc)
    )
    fallback_days = 0 if date else HF_FALLBACK_DAYS

    for offset in range(fallback_days + 1):
        candidate_date = (requested_date - timedelta(days=offset)).strftime("%Y-%m-%d")
        papers = _fetch_hf_papers_for_date(candidate_date)
        if papers:
            if offset:
                print(
                    f"[INFO] HF daily list is empty for the current date; "
                    f"using the latest non-empty date {candidate_date}."
                )
            print(
                f"[INFO] Fetched {len(papers)} HF daily papers for {candidate_date} "
                f"(max={HF_MAX_PAPERS})"
            )
            return papers

    print(
        f"[WARN] No HF daily papers found in the last {fallback_days + 1} date(s)."
    )
    return []
