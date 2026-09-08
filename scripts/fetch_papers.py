"""
Main entry point: fetch papers from HuggingFace (primary) and ArXiv (fallback),
compute Zotero similarity, filter by followed authors/institutions, and output papers.json.

HuggingFace daily papers are ArXiv papers curated by the HF community,
providing the same metadata without ArXiv API rate limiting issues.
"""

import os
from datetime import datetime, timezone
from pipeline_state import write_json



def main():
    from daily_pipeline import generate
    return generate()


def output_result(similar_papers: list[dict], followed_papers: list[dict], hf_papers: list[dict], *, candidate_papers=None, metadata=None):
    """Write papers.json to the data directory."""
    _validate_display_data(similar_papers, followed_papers, hf_papers or candidate_papers or [])
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
        "candidate_papers": candidate_papers or [],
        **(metadata or {}),
    }

    write_json(output_path, result)

    print(f"\n[DONE] Output written to {output_path}")
    print(f"  - Interest-profile recommendations: {len(similar_papers)}")
    print(f"  - Followed papers: {len(followed_papers)}")
    print(f"  - HF raw papers: {len(hf_papers)}")

    return result

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
