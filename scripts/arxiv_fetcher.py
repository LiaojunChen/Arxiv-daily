"""
ArXiv paper fetcher: uses the RSS Atom feed to get today's new papers
with full metadata (including author affiliations).

The RSS feed (rss.arxiv.org) is designed for feed readers and is NOT
rate-limited — it includes full paper details in one request, avoiding
the need to hit the search API at all.
"""

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from config import (
    ARXIV_QUERY,
    ARXIV_API_BASE,
    get_followed_authors,
    get_followed_institutions,
)


def get_latest_papers(categories: str = None) -> list[dict]:
    """
    Fetch today's new ArXiv papers.
    Step 1: RSS Atom feed for basic metadata (no affiliations in RSS).
    Step 2: API queries by id_list to enrich with author affiliations.
    """
    if categories is None:
        categories = ARXIV_QUERY

    # Normalize categories: handle +, comma, space, newline separators
    cats = [
        c.strip()
        for c in categories.replace(",", "+").replace(" ", "+").replace("\n", "+").split("+")
        if c.strip()
    ]
    query = "+".join(cats)
    url = f"https://rss.arxiv.org/atom/{query}"

    print(f"[INFO] Fetching ArXiv RSS feed: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "arXivDaily/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as e:
        print(f"[ERROR] RSS feed request failed: {e}")
        return []

    papers = _parse_atom_feed(xml_data)
    print(f"[INFO] RSS feed returned {len(papers)} papers")

    # Step 2: Enrich with affiliations from ArXiv API (id_list queries)
    ids = [p["arxiv_id"] for p in papers]
    try:
        aff_map = _fetch_affiliations_by_ids(ids)
        for p in papers:
            if not p["affiliations"] and p["arxiv_id"] in aff_map:
                p["affiliations"] = aff_map[p["arxiv_id"]]
        enriched = sum(1 for p in papers if p["affiliations"])
        print(f"[INFO] Enriched affiliations for {enriched}/{len(papers)} papers")
    except Exception as e:
        print(f"[WARN] Could not enrich affiliations (API limited): {e}")

    return papers


def _fetch_affiliations_by_ids(arxiv_ids: list[str]) -> dict[str, list[dict]]:
    """
    Query ArXiv API by id_list to get author affiliations.
    Uses the `arxiv` Python package (same as the original zotero-arxiv-daily
    project) with its built-in retry logic for rate limiting.
    Returns map of arxiv_id → list of {author, affiliation} dicts.
    """
    if not arxiv_ids:
        return {}

    try:
        import arxiv
    except ImportError:
        print("[WARN] arxiv package not installed, skipping affiliation enrichment.")
        return {}

    import time as time_mod

    max_batch_retries = 5
    batch_retry_delay = 30
    batch_size = 20
    aff_map = {}

    # Match the original project's client settings exactly
    client = arxiv.Client(num_retries=10, delay_seconds=10)

    for i in range(0, len(arxiv_ids), batch_size):
        batch = arxiv_ids[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(arxiv_ids) - 1) // batch_size + 1

        for attempt in range(max_batch_retries):
            try:
                search = arxiv.Search(id_list=batch)
                results = list(client.results(search))
                for r in results:
                    affs = []
                    for a in r.authors:
                        aff_str = getattr(a, 'affiliation', '') or ''
                        if aff_str:
                            affs.append({"author": a.name, "affiliation": aff_str})
                    if affs:
                        # Extract clean arxiv_id from the result
                        rid = r.entry_id.split("/abs/")[-1].split("v")[0]
                        aff_map[rid] = affs
                break
            except arxiv.HTTPError as exc:
                if exc.status == 429 and attempt < max_batch_retries - 1:
                    wait = batch_retry_delay * (attempt + 1)
                    print(f"[WARN] Affiliations API 429 batch {batch_num}/{total_batches}, retry in {wait}s")
                    time_mod.sleep(wait)
                else:
                    if attempt == 0:
                        print(f"[WARN] Affiliations batch {batch_num} failed: {exc}")
                    break
            except Exception as exc:
                if attempt == 0:
                    print(f"[WARN] Affiliations batch {batch_num} failed: {exc}")
                break

        if i + batch_size < len(arxiv_ids):
            time_mod.sleep(3)

    return aff_map


def _parse_atom_feed(xml_data: str) -> list[dict]:
    """Parse ArXiv Atom feed XML into paper dicts with full metadata."""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_data)

    # Check for feed errors
    title_el = root.find("atom:title", ns)
    if title_el is not None and "Feed error" in (title_el.text or ""):
        print(f"[ERROR] RSS feed error: {title_el.text}")
        return []

    papers = []
    for entry in root.findall("atom:entry", ns):
        # ID → arxiv ID
        id_full = entry.find("atom:id", ns).text.strip()
        arxiv_id = id_full.split("/abs/")[-1].split("v")[0]

        # Title
        title_el = entry.find("atom:title", ns)
        title = " ".join(title_el.text.strip().split()) if title_el is not None and title_el.text else ""

        # Abstract (summary)
        summary_el = entry.find("atom:summary", ns)
        abstract = " ".join(summary_el.text.strip().split()) if summary_el is not None and summary_el.text else ""

        # Authors with affiliations (from <arxiv:affiliation>)
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

        # Categories
        categories = [
            c.get("term")
            for c in entry.findall("atom:category", ns)
            if c.get("term")
        ]

        # Published date
        pub_el = entry.find("atom:published", ns)
        published = pub_el.text.strip() if pub_el is not None and pub_el.text else ""

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


# ── Author/Institution filtering ──────────────────────────

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
