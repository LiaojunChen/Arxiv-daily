"""
ArXiv API fetcher: query latest papers and filter by followed authors/institutions.
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from config import (
    ARXIV_API_BASE,
    ARXIV_QUERY,
    MAX_PAPER_NUM,
    get_followed_authors,
    get_followed_institutions,
)

# ArXiv API rate limit: 1 request per 3 seconds in production
# For a single daily fetch, a 5-second delay is safe.
ARXIV_DELAY = 5


def _make_arxiv_url(categories: str, max_results: int, start: int = 0) -> str:
    """Build ArXiv API query URL."""
    params = {
        "search_query": " OR ".join([f"cat:{c}" for c in categories.split("+")]),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
        "start": str(start),
    }
    return f"{ARXIV_API_BASE}?{urllib.parse.urlencode(params)}"


def _parse_arxiv_xml(xml_data: str) -> list[dict]:
    """Parse ArXiv API XML response into a list of paper dicts."""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_data)
    papers = []

    for entry in root.findall("atom:entry", ns):
        arxiv_id_full = entry.find("atom:id", ns).text.strip()
        arxiv_id = arxiv_id_full.split("/abs/")[-1]
        # Remove version suffix if present (e.g. "2301.12345v2" -> "2301.12345")
        arxiv_id = arxiv_id.split("v")[0] if "v" in arxiv_id.split("/")[-1] else arxiv_id

        title = " ".join(entry.find("atom:title", ns).text.strip().split())
        abstract = " ".join(entry.find("atom:summary", ns).text.strip().split())

        author_list = []
        affiliations = []
        for a in entry.findall("atom:author", ns):
            name_el = a.find("atom:name", ns)
            aff_el = a.find("arxiv:affiliation", ns)
            name = " ".join(name_el.text.strip().split()) if name_el is not None and name_el.text else ""
            aff = " ".join(aff_el.text.strip().split()) if aff_el is not None and aff_el.text else ""
            author_list.append(name)
            if aff:
                affiliations.append({"author": name, "affiliation": aff})

        categories = [
            c.get("term")
            for c in entry.findall("atom:category", ns)
            if c.get("term")
        ]

        published = entry.find("atom:published", ns).text.strip()

        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": author_list,
                "affiliations": affiliations,
                "abstract": abstract,
                "categories": categories,
                "published": published,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "abstract_url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )

    return papers


def fetch_arxiv_papers(
    categories: str = None,
    max_results: int = None,
) -> list[dict]:
    """Fetch recent papers from ArXiv API."""
    if categories is None:
        categories = ARXIV_QUERY
    if max_results is None:
        max_results = MAX_PAPER_NUM * 3  # Fetch more to allow filtering

    all_papers = []
    # ArXiv API returns max 2000 results per call; we paginate up to max_results
    for start in range(0, max_results, 100):
        batch_size = min(100, max_results - start)
        url = _make_arxiv_url(categories, batch_size, start)
        print(f"[INFO] Fetching ArXiv: start={start}, count={batch_size}")

        req = urllib.request.Request(url, headers={"User-Agent": "arXivDaily/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                xml_data = resp.read().decode("utf-8")
        except Exception as e:
            print(f"[ERROR] ArXiv API request failed: {e}")
            break

        papers = _parse_arxiv_xml(xml_data)
        if not papers:
            break
        all_papers.extend(papers)

        if len(papers) < batch_size:
            break

    print(f"[INFO] Fetched {len(all_papers)} papers from ArXiv")
    return all_papers


def filter_by_authors(papers: list[dict]) -> list[dict]:
    """Filter papers whose authors match the followed author list."""
    followed = [a.lower() for a in get_followed_authors()]
    if not followed:
        return []

    matched = []
    for paper in papers:
        paper_authors_lower = [a.lower() for a in paper["authors"]]
        for fa in followed:
            for pa in paper_authors_lower:
                if fa in pa:
                    matched.append({**paper, "matched_by": f"author:{fa}", "source": "followed"})
                    break
            else:
                continue
            break
    return matched


def filter_by_institutions(papers: list[dict]) -> list[dict]:
    """
    Filter papers by institution affiliation.
    Checks author affiliations from ArXiv metadata first, then falls back to abstract text.
    """
    followed = [inst.lower() for inst in get_followed_institutions()]
    if not followed:
        return []

    matched = []
    for paper in papers:
        # Check explicit affiliations from ArXiv metadata
        paper_affs = [a.get("affiliation", "").lower() for a in paper.get("affiliations", [])]
        # Also check abstract as fallback
        text_to_search = " ".join(paper_affs) + " " + paper["abstract"].lower()
        for inst in followed:
            if inst in text_to_search:
                matched.append(
                    {**paper, "matched_by": f"institution:{inst}", "source": "followed"}
                )
                break
    return matched


def filter_today_papers(papers: list[dict]) -> list[dict]:
    """Keep only papers published today (in UTC)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [p for p in papers if p["published"].startswith(today)]


def get_latest_papers(categories: str = None) -> list[dict]:
    """
    Main entry point: fetch latest ArXiv papers and return normalized list.
    """
    papers = fetch_arxiv_papers(categories)
    return papers
