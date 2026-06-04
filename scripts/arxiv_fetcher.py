"""
ArXiv paper fetcher: uses the RSS Atom feed to get today's new papers
with full metadata (including author affiliations).

The RSS feed (rss.arxiv.org) is designed for feed readers and is NOT
rate-limited — it includes full paper details in one request, avoiding
the need to hit the search API at all.
"""

import json
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
    Enrich papers with author affiliations using Semantic Scholar batch API.
    Returns map of arxiv_id → list of {author, affiliation} dicts.
    """
    if not arxiv_ids:
        return {}

    aff_map = {}
    target_ids = arxiv_ids[:200]
    batch_size = 100
    print(f"[INFO] Fetching affiliations via Semantic Scholar for {len(target_ids)} papers...")

    for b in range(0, len(target_ids), batch_size):
        batch = target_ids[b:b + batch_size]
        try:
            s2_ids = [f"ArXiv:{aid}" for aid in batch]
            payload = json.dumps({"ids": s2_ids}).encode("utf-8")
            url = "https://api.semanticscholar.org/graph/v1/paper/batch?fields=authors"
            req = urllib.request.Request(
                url, data=payload, method="POST",
                headers={"Content-Type": "application/json", "User-Agent": "arXivDaily/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                results = json.loads(resp.read().decode("utf-8"))

            if not isinstance(results, list):
                print(f"[WARN] Semantic Scholar unexpected response: {type(results)}")
                continue

            for item in results:
                if not item or not isinstance(item, dict):
                    continue
                # Get arxiv_id back from paperId or externalIds
                ext_ids = item.get("externalIds", {}) or {}
                arxiv_id = ext_ids.get("ArXiv", "")
                if not arxiv_id:
                    continue

                affs = []
                for a in item.get("authors", []):
                    name = a.get("name", "")
                    aff_list = a.get("affiliations", [])
                    aff_name = aff_list[0] if aff_list else ""
                    if aff_name:
                        affs.append({"author": name, "affiliation": aff_name})
                if affs:
                    aff_map[arxiv_id] = affs

            print(f"[INFO]   batch {b // batch_size + 1}: {len(results)} results")
        except Exception as e:
            print(f"[WARN] Semantic Scholar batch {b // batch_size + 1} failed: {e}")

    print(f"[INFO] Fetched affiliations for {len(aff_map)}/{len(target_ids)} papers")
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
