"""
Main entry point: fetch papers from ArXiv, HuggingFace, compute Zotero similarity,
filter by followed authors/institutions, and output papers.json.
"""

import json
import os
import sys
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

    # 1. Fetch latest ArXiv papers
    print("\n[Step 1] Fetching ArXiv papers...")
    arxiv_papers = get_latest_papers(categories=ARXIV_QUERY)
    if not arxiv_papers:
        print("[ERROR] No papers fetched from ArXiv. Exiting.")
        output_result([], [], [])
        return

    # 2. Compute Zotero-based similar paper recommendations
    print("\n[Step 2] Computing Zotero similarity...")
    zotero_items = fetch_zotero_items()
    similar_papers = []
    if zotero_items:
        similar_papers = compute_similarity(zotero_items, arxiv_papers, top_n=MAX_PAPER_NUM)
    else:
        print("[WARN] No Zotero items to base similarity on, falling back to top N latest papers.")
        similar_papers = [
            {**p, "similarity_score": 0.0, "source": "zotero_similar"}
            for p in arxiv_papers[:MAX_PAPER_NUM]
        ]

    # 3. Filter by followed authors and institutions
    print("\n[Step 3] Filtering followed authors/institutions...")
    author_papers = filter_by_authors(arxiv_papers)
    institution_papers = filter_by_institutions(arxiv_papers)

    seen_ids = set()
    followed_papers = []
    for p in author_papers + institution_papers:
        if p["arxiv_id"] not in seen_ids:
            seen_ids.add(p["arxiv_id"])
            followed_papers.append(p)
    print(f"[INFO] Found {len(followed_papers)} papers from followed authors/institutions")

    # 4. Fetch HuggingFace daily papers
    print("\n[Step 4] Fetching HuggingFace daily papers...")
    hf_papers = fetch_hf_daily_papers()

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
