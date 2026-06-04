"""
ArXiv paper fetcher.

The RSS feed is used for the daily paper list. Author affiliations are only
attached when they are explicitly present in arXiv metadata; they are never
inferred from abstract text because that creates false institution labels.
"""

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from config import (
    ARXIV_QUERY,
    ARXIV_API_BASE,
    get_followed_authors,
    get_followed_institutions,
)


def get_latest_papers(categories: str = None) -> list[dict]:
    """
    Fetch today's new ArXiv papers.

    Step 1: RSS Atom feed for the daily paper list.
    Step 2: Best-effort API query by id_list for explicit author affiliations.
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

    api_enriched = _enrich_affiliations_from_arxiv_api(papers)
    enriched = sum(1 for p in papers if p.get("affiliations"))
    print(
        f"[INFO] Enriched affiliations from arXiv API for {api_enriched}/{len(papers)} papers "
        f"(total with affs: {enriched})"
    )

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


def _parse_api_affiliations(xml_data: str) -> dict[str, list[dict]]:
    """Parse author affiliations that are explicitly present in arXiv API XML."""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_data)
    by_id: dict[str, list[dict]] = {}
    for entry in root.findall("atom:entry", ns):
        id_el = entry.find("atom:id", ns)
        if id_el is None or not id_el.text:
            continue

        arxiv_id = _normalize_arxiv_id(id_el.text)
        affiliations = []
        for author_el in entry.findall("atom:author", ns):
            name_el = author_el.find("atom:name", ns)
            aff_el = author_el.find("arxiv:affiliation", ns)
            name = _clean_text(name_el.text if name_el is not None else "")
            aff = _clean_text(aff_el.text if aff_el is not None else "")
            if aff:
                affiliations.append({"author": name, "affiliation": aff})

        if affiliations:
            by_id[arxiv_id] = _dedupe_affiliations(affiliations)
    return by_id


def _fetch_arxiv_api_affiliations(arxiv_ids: list[str]) -> dict[str, list[dict]]:
    """Fetch explicit author affiliations from arXiv API, if available."""
    ids = [_normalize_arxiv_id(arxiv_id) for arxiv_id in arxiv_ids if arxiv_id]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}

    affiliations_by_id: dict[str, list[dict]] = {}
    batch_size = 50
    for start in range(0, len(ids), batch_size):
        batch = ids[start : start + batch_size]
        query = urllib.parse.urlencode({"id_list": ",".join(batch)})
        url = f"{ARXIV_API_BASE}?{query}"
        print(f"[INFO] Fetching arXiv API metadata: batch {start // batch_size + 1}")
        req = urllib.request.Request(url, headers={"User-Agent": "arXivDaily/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                xml_data = resp.read().decode("utf-8")
        except Exception as e:
            print(f"[WARN] arXiv API affiliation request failed: {e}")
            continue

        try:
            affiliations_by_id.update(_parse_api_affiliations(xml_data))
        except ET.ParseError as e:
            print(f"[WARN] arXiv API affiliation response parse failed: {e}")
            continue

    return affiliations_by_id


def _enrich_affiliations_from_arxiv_api(papers: list[dict]) -> int:
    """Attach explicit arXiv API affiliations to papers that lack them."""
    affiliations_by_id = _fetch_arxiv_api_affiliations(
        [paper.get("arxiv_id", "") for paper in papers]
    )
    enriched = 0
    for paper in papers:
        if paper.get("affiliations"):
            paper["affiliations"] = _dedupe_affiliations(paper["affiliations"])
            continue

        affiliations = affiliations_by_id.get(_normalize_arxiv_id(paper.get("arxiv_id", "")))
        if affiliations:
            paper["affiliations"] = affiliations
            enriched += 1

    return enriched


def _parse_atom_feed(xml_data: str) -> list[dict]:
    """Parse ArXiv Atom feed XML into paper dicts."""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
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
            author_list.append(name)
            if aff:
                affiliations.append({"author": name, "affiliation": aff})

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
