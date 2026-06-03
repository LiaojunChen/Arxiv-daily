"""
Zotero integration: fetch user's Zotero library and compute similarity
with new ArXiv papers using TF-IDF + cosine similarity.
"""

import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from config import ZOTERO_ID, ZOTERO_KEY, ZOTERO_API_BASE, MAX_PAPER_NUM

ZOTERO_TIMEOUT = 15


def _zotero_headers() -> dict:
    return {"Zotero-API-Key": ZOTERO_KEY, "User-Agent": "arXivDaily/1.0"}


def fetch_zotero_items() -> list[dict]:
    """
    Fetch all items from the user's Zotero library.
    Returns a list of items with title, abstract, and tags.
    """
    if not ZOTERO_ID or not ZOTERO_KEY:
        print("[WARN] ZOTERO_ID or ZOTERO_KEY not set, skipping Zotero fetch.")
        return []

    all_items = []
    url = f"{ZOTERO_API_BASE}/users/{ZOTERO_ID}/items"
    params = {"limit": 100, "format": "json"}

    while url:
        try:
            resp = requests.get(
                url, headers=_zotero_headers(), params=params if "?" not in url else None, timeout=ZOTERO_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            all_items.extend(data)

            # Handle pagination via Link header
            url = None
            link_header = resp.headers.get("Link")
            if link_header:
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        url = part.split(";")[0].strip(" <>")
                        break
        except requests.RequestException as e:
            print(f"[ERROR] Zotero API request failed: {e}")
            break

    # Filter to items that have titles and abstracts (journal articles, conference papers, preprints)
    papers = []
    for item in all_items:
        data = item.get("data", {})
        title = data.get("title", "").strip()
        abstract = data.get("abstractNote", "").strip() or data.get("abstract", "").strip()
        if title:
            papers.append(
                {
                    "title": title,
                    "abstract": abstract,
                    "tags": [t.get("tag", "") for t in data.get("tags", [])],
                }
            )

    print(f"[INFO] Fetched {len(papers)} items from Zotero library")
    return papers


def compute_similarity(
    zotero_papers: list[dict], arxiv_papers: list[dict], top_n: int = None
) -> list[dict]:
    """
    Compute TF-IDF cosine similarity between Zotero library papers and ArXiv papers.
    For each ArXiv paper, the max similarity to any Zotero paper is used as its score.
    Returns ArXiv papers sorted by similarity score (descending), top N.
    """
    if top_n is None:
        top_n = MAX_PAPER_NUM
    if not zotero_papers or not arxiv_papers:
        print("[WARN] No papers to compare for similarity.")
        return []

    # Build text corpus: title + " " + abstract for each paper
    zotero_texts = [
        (p.get("title", "") + " " + p.get("abstract", "")) for p in zotero_papers
    ]
    arxiv_texts = [
        (p.get("title", "") + " " + p.get("abstract", "")) for p in arxiv_papers
    ]

    # TF-IDF vectorization
    vectorizer = TfidfVectorizer(
        max_features=10000,
        stop_words="english",
        ngram_range=(1, 2),
    )
    all_texts = zotero_texts + arxiv_texts
    tfidf_matrix = vectorizer.fit_transform(all_texts)

    zotero_vecs = tfidf_matrix[: len(zotero_texts)]
    arxiv_vecs = tfidf_matrix[len(zotero_texts):]

    # For each ArXiv paper, find max similarity to any Zotero paper
    sim_matrix = cosine_similarity(arxiv_vecs, zotero_vecs)
    max_sim_scores = sim_matrix.max(axis=1)

    # Attach scores and sort
    scored = []
    for i, paper in enumerate(arxiv_papers):
        scored.append({**paper, "similarity_score": round(float(max_sim_scores[i]), 4)})

    scored.sort(key=lambda x: x["similarity_score"], reverse=True)

    # Mark source
    for p in scored:
        p["source"] = "zotero_similar"

    result = scored[:top_n]
    print(f"[INFO] Top {len(result)} similar papers computed (max score: {result[0]['similarity_score'] if result else 'N/A'})")
    return result
