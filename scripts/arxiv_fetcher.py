"""
ArXiv paper fetcher.

The RSS feed is used for the daily paper list. The current arXiv RSS schema
publishes authors in ``dc:creator`` (as a comma-separated string), while some
older/test feeds use Atom ``author`` elements. Both forms are supported.

Affiliations are only attached when they are explicitly present in metadata;
they are never inferred from abstract text because that creates false labels.
"""

import re
import urllib.request
import xml.etree.ElementTree as ET

from config import (
    ARXIV_QUERY,
    get_followed_authors,
    get_followed_institutions,
)


def get_latest_papers(categories: str = None) -> list[dict]:
    """
    Fetch today's new ArXiv papers.

    The RSS endpoint is deliberately used instead of the rate-limited search
    API. Affiliation enrichment for the papers that are actually displayed is
    handled later by ``affiliation_extractor``.
    """
    if categories is None:
        categories = ARXIV_QUERY

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

    missing_authors = sum(1 for paper in papers if not paper.get("authors"))
    if missing_authors:
        print(f"[WARN] RSS feed omitted authors for {missing_authors}/{len(papers)} papers")

    return papers


def _normalize_arxiv_id(arxiv_id: str) -> str:
    """Return an arXiv id without URL/prefix/version noise."""
    arxiv_id = (arxiv_id or "").strip()
    if "/abs/" in arxiv_id:
        arxiv_id = arxiv_id.rsplit("/abs/", 1)[-1]
    arxiv_id = arxiv_id.removeprefix("oai:arXiv.org:")
    arxiv_id = arxiv_id.removeprefix("arXiv:").removeprefix("arxiv:")
    return re.sub(r"v\d+$", "", arxiv_id)


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _dedupe_affiliations(affiliations: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for item in affiliations:
        author = _clean_text(item.get("author"))
        affiliation = _clean_text(item.get("affiliation"))
        if not affiliation:
            continue
        key = (author.casefold(), affiliation.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"author": author, "affiliation": affiliation})
    return deduped


def _parse_atom_feed(xml_data: str) -> list[dict]:
    """Parse ArXiv Atom feed XML into paper dicts."""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    root = ET.fromstring(xml_data)

    title_el = root.find("atom:title", ns)
    if title_el is not None and "Feed error" in (title_el.text or ""):
        print(f"[ERROR] RSS feed error: {title_el.text}")
        return []

    papers = []
    for entry in root.findall("atom:entry", ns):
        id_el = entry.find("atom:id", ns)
        id_full = id_el.text.strip() if id_el is not None and id_el.text else ""
        arxiv_id = _normalize_arxiv_id(id_full)

        title_el = entry.find("atom:title", ns)
        title = _clean_text(title_el.text if title_el is not None else "")

        summary_el = entry.find("atom:summary", ns)
        abstract = _clean_text(summary_el.text if summary_el is not None else "")

        author_list = []
        affiliations = []
        for author_el in entry.findall("atom:author", ns):
            name_el = author_el.find("atom:name", ns)
            aff_el = author_el.find("arxiv:affiliation", ns)
            name = _clean_text(name_el.text if name_el is not None else "")
            aff = _clean_text(aff_el.text if aff_el is not None else "")
            if name:
                author_list.append(name)
            if aff:
                affiliations.append({"author": name, "affiliation": aff})

        # rss.arxiv.org currently emits one dc:creator element containing all
        # names separated by commas, and no Atom author elements.
        if not author_list:
            for creator_el in entry.findall("dc:creator", ns):
                creator = _clean_text(creator_el.text)
                author_list.extend(
                    name for name in re.split(r"\s*,\s*", creator) if name
                )

        categories = [
            category.get("term")
            for category in entry.findall("atom:category", ns)
            if category.get("term")
        ]

        pub_el = entry.find("atom:published", ns)
        published = pub_el.text.strip() if pub_el is not None and pub_el.text else ""

        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": author_list,
                "affiliations": _dedupe_affiliations(affiliations),
                "abstract": abstract,
                "categories": categories,
                "published": published,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "abstract_url": f"https://arxiv.org/abs/{arxiv_id}",
                "source": "arxiv",
            }
        )

    return papers


def filter_by_authors(papers: list[dict]) -> list[dict]:
    followed = [a.lower() for a in get_followed_authors()]
    if not followed:
        return []

    matched = []
    for paper in papers:
        paper_authors_lower = [a.lower() for a in paper.get("authors", [])]
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
        for inst in followed:
            if any(inst in aff for aff in paper_affs):
                matched.append({**paper, "matched_by": f"institution:{inst}", "source": "followed"})
                break
    return matched
