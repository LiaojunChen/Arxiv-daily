"""
ArXiv paper fetcher using the same two-step approach as zotero-arxiv-daily:
  1. RSS/Atom feed to get today's paper IDs (lightweight, rarely rate-limited)
  2. Query API by id_list for detailed metadata (cheaper than full search)
"""

import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import time
from datetime import datetime, timezone

from config import (
    ARXIV_API_BASE,
    ARXIV_QUERY,
    MAX_PAPER_NUM,
    get_followed_authors,
    get_followed_institutions,
)


def _fetch_rss_paper_ids(categories: str) -> list[str]:
    """
    Step 1: Use RSS Atom feed to get today's new paper IDs.
    This is the same lightweight endpoint the original project uses.
    Format: https://rss.arxiv.org/atom/cs.AI+cs.CL
    Returns list of arXiv IDs (without version suffix).
    """
    # Build URL: replace "+" in ARXIV_QUERY with actual "+" for RSS
    query = "+".join(categories.split("+"))
    url = f"https://rss.arxiv.org/atom/{query}"
    print(f"[INFO] Fetching RSS feed: {url}")

    req = urllib.request.Request(url, headers={"User-Agent": "arXivDaily/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as e:
        print(f"[ERROR] RSS feed request failed: {e}")
        return []

    # Parse Atom XML to extract paper IDs
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_data)

    # Check for feed errors
    title_el = root.find("atom:title", ns)
    if title_el is not None and "Feed error" in (title_el.text or ""):
        print(f"[ERROR] RSS feed error: {title_el.text}")
        return []

    ids = []
    for entry in root.findall("atom:entry", ns):
        id_el = entry.find("atom:id", ns)
        if id_el is not None and id_el.text:
            # Format: "http://arxiv.org/abs/2301.12345v2" → "2301.12345"
            arxiv_id = id_el.text.strip().split("/abs/")[-1]
            arxiv_id = arxiv_id.split("v")[0]
            ids.append(arxiv_id)

    print(f"[INFO] RSS feed returned {len(ids)} paper IDs for today")
    return ids


def _fetch_papers_by_ids(arxiv_ids: list[str]) -> list[dict]:
    """
    Step 2: Get detailed paper metadata by querying the ArXiv API with id_list.
    id_list queries are much cheaper than search queries for ArXiv.
    Batched in groups of 20 with delays between batches (matching original project).
    """
    max_batch_retries = 5
    batch_retry_delay = 30

    all_papers = []
    batch_size = 20

    for i in range(0, len(arxiv_ids), batch_size):
        batch = arxiv_ids[i : i + batch_size]
        print(f"[INFO] Fetching batch {i // batch_size + 1}/{(len(arxiv_ids) - 1) // batch_size + 1} ({len(batch)} IDs)")

        for attempt in range(max_batch_retries):
            try:
                papers = _request_batch_by_ids(batch)
                all_papers.extend(papers)
                break
            except Exception as e:
                status = getattr(e, "code", None)
                if status == 429 and attempt < max_batch_retries - 1:
                    wait = batch_retry_delay * (attempt + 1)
                    print(f"[WARN] ArXiv 429 on batch {i // batch_size + 1}, retrying in {wait}s (attempt {attempt + 1}/{max_batch_retries})")
                    time.sleep(wait)
                else:
                    print(f"[ERROR] Batch {i // batch_size + 1} failed: {e}")
                    break

        # 3 second delay between batches (matching original project)
        if i + batch_size < len(arxiv_ids):
            time.sleep(3)

    print(f"[INFO] Fetched metadata for {len(all_papers)} papers via id_list API")
    return all_papers


def _request_batch_by_ids(arxiv_ids: list[str]) -> list[dict]:
    """Query ArXiv API for specific paper IDs."""
    id_param = ",".join(arxiv_ids)
    url = f"{ARXIV_API_BASE}?id_list={urllib.parse.quote(id_param)}&max_results={len(arxiv_ids)}"

    req = urllib.request.Request(url, headers={"User-Agent": "arXivDaily/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            xml_data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from e

    return _parse_api_xml(xml_data)


def _parse_api_xml(xml_data: str) -> list[dict]:
    """Parse ArXiv API Atom XML response into paper dicts."""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_data)
    papers = []

    for entry in root.findall("atom:entry", ns):
        id_full = entry.find("atom:id", ns).text.strip()
        arxiv_id = id_full.split("/abs/")[-1].split("v")[0]

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

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": author_list,
            "affiliations": affiliations,
            "abstract": abstract,
            "categories": categories,
            "published": published,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "abstract_url": f"https://arxiv.org/abs/{arxiv_id}",
            "source": "arxiv",
        })

    return papers


def get_latest_papers(categories: str = None) -> list[dict]:
    """
    Main entry point: fetch today's new ArXiv papers.
    Uses two-step approach (RSS → ID list → API) to avoid rate limiting.
    """
    if categories is None:
        categories = ARXIV_QUERY

    # Step 1: Get today's paper IDs from RSS Atom feed
    ids = _fetch_rss_paper_ids(categories)
    if not ids:
        print("[ERROR] No paper IDs from RSS feed.")
        return []

    # Step 2: Fetch detailed metadata by ID batches
    papers = _fetch_papers_by_ids(ids)
    return papers


# ── Author/Institution filtering (unchanged) ──────────────

def filter_by_authors(papers: list[dict]) -> list[dict]:
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
    followed = [inst.lower() for inst in get_followed_institutions()]
    if not followed:
        return []

    matched = []
    for paper in papers:
        paper_affs = [a.get("affiliation", "").lower() for a in paper.get("affiliations", [])]
        text_to_search = " ".join(paper_affs) + " " + paper["abstract"].lower()
        for inst in followed:
            if inst in text_to_search:
                matched.append({**paper, "matched_by": f"institution:{inst}", "source": "followed"})
                break
    return matched


def filter_today_papers(papers: list[dict]) -> list[dict]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [p for p in papers if p["published"].startswith(today)]
