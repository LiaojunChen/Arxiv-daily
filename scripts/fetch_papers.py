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
from affiliation_extractor import enrich_affiliations_for_display_papers
from interest_state import load_interest_state
from config import (
    MAX_PAPER_NUM,
    load_user_config,
    ARXIV_QUERY,
    get_followed_institutions,
)


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

    # 2. Use the arXiv RSS service as the broad daily candidate source.
    print("\n[Step 2] Fetching arXiv RSS papers (supplementary)...")
    arxiv_papers = []
    try:
        arxiv_papers = get_latest_papers(categories=ARXIV_QUERY)
    except Exception as e:
        print(f"[WARN] arXiv RSS unavailable: {e}")

    # Preserve any explicit affiliations supplied by older Atom feeds.
    arxiv_affiliations = {}
    for p in arxiv_papers:
        if p.get("arxiv_id") and p.get("affiliations"):
            arxiv_affiliations[p["arxiv_id"]] = p["affiliations"]

    # Enrich HF papers with ArXiv affiliations
    for p in hf_papers:
        if not p.get("affiliations") and p.get("arxiv_id") in arxiv_affiliations:
            p["affiliations"] = arxiv_affiliations[p["arxiv_id"]]

    print(f"[INFO] ArXiv: {len(arxiv_papers)} papers, HF: {len(hf_papers)} papers")

    # 3. Use the same persisted interest profile as the email recommender.
    # Zotero remains a compatibility fallback for profiles that have no terms.
    print("\n[Step 3] Computing interest-profile similarity on ArXiv papers...")
    similar_papers = []
    if not arxiv_papers:
        # Fallback: use HF papers if ArXiv is empty
        print("[WARN] No ArXiv papers, falling back to HF papers for similarity.")
        arxiv_papers = hf_papers

    profile_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "interest_profile.json")
    interest_keywords, suppressed_keywords = load_interest_state(profile_path)
    try:
        if interest_keywords:
            print(f"[INFO] Using shared interest profile: {interest_keywords}")
            if suppressed_keywords:
                print(f"[INFO] Suppressing profile themes: {suppressed_keywords}")
            similar_papers = compute_similarity(
                [],
                arxiv_papers,
                top_n=MAX_PAPER_NUM,
                interest_keywords=interest_keywords,
                suppressed_keywords=suppressed_keywords,
            )
        else:
            zotero_items = fetch_zotero_items()
            if zotero_items:
                similar_papers = compute_similarity(zotero_items, arxiv_papers, top_n=MAX_PAPER_NUM)
            else:
                print("[WARN] No profile or Zotero items; using top N latest ArXiv papers.")
                similar_papers = [
                    {**p, "similarity_score": 0.0, "source": "zotero_similar"}
                    for p in arxiv_papers[:MAX_PAPER_NUM]
                ]
    except Exception as e:
        print(f"[ERROR] Interest-profile similarity failed: {e}")
        similar_papers = [
            {**p, "similarity_score": 0.0, "source": "interest_profile"}
            for p in arxiv_papers[:MAX_PAPER_NUM]
        ]

    # 4. Followed authors can be filtered immediately. Institution matching
    # must wait until explicit affiliations have been extracted.
    print("\n[Step 4] Filtering followed authors...")
    author_papers = []
    try:
        author_papers = filter_by_authors(arxiv_papers)
        print(f"[INFO] Found {len(author_papers)} papers from followed authors")
    except Exception as e:
        print(f"[ERROR] Followed-author filtering failed: {e}")

    # 5. Enrich affiliations for papers shown on the web page
    print("\n[Step 5] Enriching affiliations for displayed papers...")
    try:
        affiliation_groups = [similar_papers, author_papers, hf_papers]
        if get_followed_institutions():
            # Institution subscriptions require affiliation metadata for the
            # whole candidate set. AFFILIATION_MAX_PAPERS can cap this work.
            affiliation_groups.append(arxiv_papers)
        enriched = enrich_affiliations_for_display_papers(affiliation_groups)
        print(f"[INFO] Affiliation extraction enriched {enriched} papers")
    except Exception as e:
        print(f"[ERROR] Affiliation enrichment failed: {e}")

    # 6. Complete followed-paper filtering now that affiliations are available.
    print("\n[Step 6] Filtering followed institutions...")
    followed_papers = []
    try:
        institution_papers = filter_by_institutions(arxiv_papers)
        followed_ids = set()
        for paper in author_papers + institution_papers:
            if paper["arxiv_id"] not in followed_ids:
                followed_ids.add(paper["arxiv_id"])
                followed_papers.append(paper)
        print(
            f"[INFO] Found {len(followed_papers)} papers from followed "
            "authors/institutions"
        )
    except Exception as e:
        print(f"[ERROR] Followed-institution filtering failed: {e}")
        followed_papers = author_papers

    # 7. Output
    output_result(similar_papers, followed_papers, hf_papers)


def output_result(similar_papers: list[dict], followed_papers: list[dict], hf_papers: list[dict]):
    """Write papers.json to the data directory."""
    _validate_display_data(similar_papers, followed_papers, hf_papers)
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "papers.json",
    )

    generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    updated_at = generated_at.isoformat()
    result = {
        "date": generated_at.strftime("%Y-%m-%d"),
        "updated_at": updated_at,
        # A single stable marker for all cards in this Pages build. It lets the
        # feedback service deduplicate a repeated click without conflating
        # separate daily recommendation runs.
        "run_id": f"pages-{generated_at.strftime('%Y%m%dT%H%M%SZ')}",
        "similar_papers": similar_papers,
        "followed_papers": followed_papers,
        "hf_papers": hf_papers,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] Output written to {output_path}")
    print(f"  - Interest-profile recommendations: {len(similar_papers)}")
    print(f"  - Followed papers: {len(followed_papers)}")
    print(f"  - HF raw papers: {len(hf_papers)}")


def _validate_display_data(
    similar_papers: list[dict], followed_papers: list[dict], hf_papers: list[dict]
) -> None:
    """Reject empty or structurally broken data before a Pages deployment."""
    display_papers = similar_papers + followed_papers + hf_papers
    if not display_papers:
        raise RuntimeError(
            "No papers were fetched from either arXiv RSS or Hugging Face; "
            "refusing to replace the deployed page with empty/sample data."
        )

    invalid = [
        paper
        for paper in display_papers
        if not paper.get("arxiv_id") or not paper.get("title")
    ]
    if invalid:
        raise ValueError(
            f"{len(invalid)} displayed papers are missing arxiv_id/title metadata"
        )

    malformed = [
        paper
        for paper in display_papers
        if not isinstance(paper.get("authors"), list)
        or not isinstance(paper.get("affiliations"), list)
        or not isinstance(paper.get("categories"), list)
        or not isinstance(paper.get("abstract"), str)
    ]
    if malformed:
        raise ValueError(
            f"{len(malformed)} displayed papers have malformed list/text fields"
        )

    primary_group = similar_papers or hf_papers
    if primary_group and all(not paper.get("authors") for paper in primary_group):
        raise ValueError(
            "All primary papers are missing authors; the upstream RSS/API schema "
            "likely changed, so deployment was stopped."
        )


if __name__ == "__main__":
    main()
