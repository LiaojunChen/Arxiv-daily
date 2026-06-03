"""
HuggingFace Daily Papers fetcher.
Calls the HF public API to retrieve curated daily papers.
No authentication required.
"""

import requests
from datetime import datetime, timezone


HF_API_BASE = "https://huggingface.co/api/daily_papers"
HF_TIMEOUT = 15


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


def fetch_hf_daily_papers(date: str = None) -> list[dict]:
    """
    Fetch HuggingFace daily papers.

    Args:
        date: YYYY-MM-DD format. Defaults to today (UTC).
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    all_papers = []
    page = 1

    while True:
        url = f"{HF_API_BASE}?date={date}&page={page}&limit=50"
        print(f"[INFO] Fetching HF papers: page={page}")

        try:
            resp = requests.get(url, timeout=HF_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[ERROR] HF papers API request failed: {e}")
            break

        if not data:
            break

        for item in data:
            all_papers.append(_parse_hf_paper(item))

        if len(data) < 50:
            break
        page += 1

    print(f"[INFO] Fetched {len(all_papers)} HF daily papers for {date}")
    return all_papers
