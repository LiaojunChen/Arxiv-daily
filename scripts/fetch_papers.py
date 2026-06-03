"""
Main entry point: fetch papers from ArXiv, HuggingFace, compute Zotero similarity,
filter by followed authors/institutions, and output papers.json.

Each data source is independent — failure of one does not block the others.
"""

import json
import os
import time
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

    # Load user config (followed authors/institutions)
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "config.json",
    )
    load_user_config(config_path)

    # 1. Fetch latest ArXiv papers (non-fatal on failure)
    print("\n[Step 1] Fetching ArXiv papers...")
    arxiv_papers = []
    try:
        arxiv_papers = get_latest_papers(categories=ARXIV_QUERY)
    except Exception as e:
        print(f"[ERROR] ArXiv fetch failed: {e}")

    # 2. Compute Zotero-based similar paper recommendations
    print("\n[Step 2] Computing Zotero similarity...")
    similar_papers = []
    zotero_items = []
    if arxiv_papers:
        try:
            zotero_items = fetch_zotero_items()
            similar_papers = compute_similarity(zotero_items, arxiv_papers, top_n=MAX_PAPER_NUM)
        except Exception as e:
            print(f"[ERROR] Zotero similarity failed: {e}, falling back to top N latest.")
            similar_papers = [
                {**p, "similarity_score": 0.0, "source": "zotero_similar"}
                for p in arxiv_papers[:MAX_PAPER_NUM]
            ]
    else:
        try:
            zotero_items = fetch_zotero_items()
        except Exception:
            pass
        print("[WARN] No ArXiv papers available, skipping similarity computation.")

    # 3. Filter by followed authors and institutions
    print("\n[Step 3] Filtering followed authors/institutions...")
    followed_papers = []
    try:
        author_papers = filter_by_authors(arxiv_papers)
        institution_papers = filter_by_institutions(arxiv_papers)
        seen_ids = set()
        for p in author_papers + institution_papers:
            if p["arxiv_id"] not in seen_ids:
                seen_ids.add(p["arxiv_id"])
                followed_papers.append(p)
        print(f"[INFO] Found {len(followed_papers)} papers from followed authors/institutions")
    except Exception as e:
        print(f"[ERROR] Followed filtering failed: {e}")

    # 4. Fetch HuggingFace daily papers (independent of ArXiv)
    print("\n[Step 4] Fetching HuggingFace daily papers...")
    hf_papers = []
    try:
        hf_papers = fetch_hf_daily_papers()
    except Exception as e:
        print(f"[ERROR] HF daily papers fetch failed: {e}")

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
    print(f"  - Similar papers: {len(similar_papers)}")
    print(f"  - Followed papers: {len(followed_papers)}")
    print(f"  - HF daily papers: {len(hf_papers)}")


if __name__ == "__main__":
    main()
