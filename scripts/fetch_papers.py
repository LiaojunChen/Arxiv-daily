"""
Main entry point: fetch papers from HuggingFace (primary) and ArXiv (fallback),
compute Zotero similarity, filter by followed authors/institutions, and output papers.json.

HuggingFace daily papers are ArXiv papers curated by the HF community,
providing the same metadata without ArXiv API rate limiting issues.
"""

import json
import os
from datetime import datetime, timezone

from arxiv_fetcher import (
    get_latest_papers,
    filter_by_authors,
    filter_by_institutions,
)
from zotero_similar import fetch_zotero_items, compute_similarity
from hf_fetcher import fetch_hf_daily_papers
from config import MAX_PAPER_NUM, load_user_config, ARXIV_QUERY


def main():
    print("=" * 60)
    print(f"ArXiv Daily Fetch — {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "config.json",
    )
    load_user_config(config_path)

    # 1. Fetch HF daily papers (primary ArXiv paper source)
    print("\n[Step 1] Fetching HuggingFace daily papers...")
    hf_papers = []
    try:
        hf_papers = fetch_hf_daily_papers()
    except Exception as e:
        print(f"[ERROR] HF papers fetch failed: {e}")

    # 2. Try ArXiv API as supplementary source (GitHub Actions IP often rate-limited)
    print("\n[Step 2] Fetching ArXiv papers (supplementary)...")
    arxiv_papers = []
    try:
        arxiv_papers = get_latest_papers(categories=ARXIV_QUERY)
    except Exception as e:
        print(f"[WARN] ArXiv API unavailable (expected on CI): {e}")

    # Merge papers, preferring HF as primary
    seen_ids = set()
    all_papers = []
    # Build lookup for ArXiv affiliations (ArXiv API provides <arxiv:affiliation>)
    arxiv_affiliations = {}
    for p in arxiv_papers:
        if p.get("arxiv_id") and p.get("affiliations"):
            arxiv_affiliations[p["arxiv_id"]] = p["affiliations"]

    # HF papers first (start with what works reliably)
    for p in hf_papers:
        if p.get("arxiv_id"):
            seen_ids.add(p["arxiv_id"])
            # Cross-reference affiliations from ArXiv data
            if not p.get("affiliations") and p["arxiv_id"] in arxiv_affiliations:
                p["affiliations"] = arxiv_affiliations[p["arxiv_id"]]
            all_papers.append(p)

    # Add ArXiv papers not already in HF list
    arxiv_only = 0
    for p in arxiv_papers:
        if p["arxiv_id"] not in seen_ids:
            seen_ids.add(p["arxiv_id"])
            all_papers.append(p)
            arxiv_only += 1

    print(f"[INFO] Total unique papers: {len(all_papers)} (HF: {len(hf_papers)}, ArXiv additional: {arxiv_only})")

    if not all_papers:
        print("[ERROR] No papers available from any source. Outputting empty result.")
        output_result([], [], [])
        return

    # 3. Compute Zotero-based similar paper recommendations
    print("\n[Step 3] Computing Zotero similarity...")
    similar_papers = []
    try:
        zotero_items = fetch_zotero_items()
        if zotero_items:
            similar_papers = compute_similarity(zotero_items, all_papers, top_n=MAX_PAPER_NUM)
        else:
            print("[WARN] No Zotero items, using top N latest papers.")
            similar_papers = [
                {**p, "similarity_score": 0.0, "source": "zotero_similar"}
                for p in all_papers[:MAX_PAPER_NUM]
            ]
    except Exception as e:
        print(f"[ERROR] Zotero similarity failed: {e}")
        similar_papers = [
            {**p, "similarity_score": 0.0, "source": "zotero_similar"}
            for p in all_papers[:MAX_PAPER_NUM]
        ]

    # 4. Filter by followed authors and institutions (from all papers)
    print("\n[Step 4] Filtering followed authors/institutions...")
    followed_papers = []
    try:
        author_papers = filter_by_authors(all_papers)
        institution_papers = filter_by_institutions(all_papers)
        followed_ids = set()
        for p in author_papers + institution_papers:
            if p["arxiv_id"] not in followed_ids:
                followed_ids.add(p["arxiv_id"])
                followed_papers.append(p)
        print(f"[INFO] Found {len(followed_papers)} papers from followed authors/institutions")
    except Exception as e:
        print(f"[ERROR] Followed filtering failed: {e}")

    # 5. Output
    output_result(similar_papers, followed_papers, hf_papers)


def output_result(similar_papers: list[dict], followed_papers: list[dict], hf_papers: list[dict]):
    """Write papers.json to the data directory."""
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "papers.json",
    )

    result = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "similar_papers": similar_papers,
        "followed_papers": followed_papers,
        "hf_papers": hf_papers,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] Output written to {output_path}")
    print(f"  - Similar papers (Zotero reranked): {len(similar_papers)}")
    print(f"  - Followed papers: {len(followed_papers)}")
    print(f"  - HF raw papers: {len(hf_papers)}")


if __name__ == "__main__":
    main()
