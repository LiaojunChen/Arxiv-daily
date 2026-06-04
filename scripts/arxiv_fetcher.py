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

    # Step 2: Extract affiliations from abstract text (heuristic)
    # External APIs are rate-limited from GitHub Actions, so we parse
    # institution names from author names and abstract footnotes.
    text_enriched = _extract_affiliations_from_text(papers)
    enriched = sum(1 for p in papers if p.get("affiliations"))
    print(f"[INFO] Extracted affiliations for {text_enriched}/{len(papers)} papers (total with affs: {enriched})")

    return papers


def _extract_affiliations_from_text(papers: list[dict]) -> int:
    """
    Heuristic: extract affiliations from abstract text footnotes.
    Many papers list author affiliations at the end of the abstract
    or in patterns like "Author1 (MIT), Author2 (Stanford)".
    Returns count of papers enriched.
    """
    import re

    enriched = 0
    for p in papers:
        if p.get("affiliations"):
            continue  # already has affiliations

        abstract = p.get("abstract", "")
        affs_from_text = []

        # Pattern 1: "Author1, Author2 (Institution1, Institution2)"
        # Pattern 2: Lines with university/institute/lab keywords at end of abstract
        inst_patterns = [
            r'(?:University|Institute|College|School)\s+of\s+[\w\s]+',
            r'(?:MIT|CMU|ETH|EPFL|NYU|UCLA|UC\s+\w+|Caltech)',
            r'[\w\s]+(?:University|Institute|College|Laboratory|Lab|Research|Inc\.|Ltd\.)',
            r'(?:Google|Microsoft|Meta|Apple|Amazon|OpenAI|DeepMind|Anthropic|NVIDIA|Intel|IBM)\s+(?:Research|AI|DeepMind)?',
        ]

        found_affs = set()
        for pattern in inst_patterns:
            matches = re.findall(pattern, abstract, re.IGNORECASE)
            for m in matches:
                cleaned = m.strip().rstrip(',').rstrip('.').strip()
                if len(cleaned) > 4:
                    found_affs.add(cleaned)

        # Also check last few lines of abstract (common for affiliation footnotes)
        lines = abstract.split('.')
        last_lines = [l.strip() for l in lines[-5:] if len(l.strip()) > 20]
        for line in last_lines:
            for pattern in inst_patterns:
                matches = re.findall(pattern, line, re.IGNORECASE)
                for m in matches:
                    cleaned = m.strip().rstrip(',').rstrip('.').strip()
                    if len(cleaned) > 4:
                        found_affs.add(cleaned)

        if found_affs:
            # Assign to first author (best effort)
            first_author = p["authors"][0] if p["authors"] else "Unknown"
            for aff in list(found_affs)[:3]:
                affs_from_text.append({"author": first_author, "affiliation": aff})
            p["affiliations"] = affs_from_text
            enriched += 1

    return enriched


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
