"""Offline evaluation: python scripts/evaluate_recommendations.py snapshot.json labels.json."""
import argparse
import json
import math
from pathlib import Path


def evaluate(snapshot, labels, k=10):
    """Labels map arxiv_id to relevance (0..3), topics and optional negative=True."""
    if k <= 0:
        raise ValueError("k must be positive")
    selected = snapshot["similar_papers"][:k]
    missing = [p["arxiv_id"] for p in selected if p["arxiv_id"] not in labels]
    if missing:
        raise ValueError(f"Label every evaluated result first: {missing}")
    gains = [float(labels[p["arxiv_id"]]["relevance"]) for p in selected]
    ideal = sorted((float(v["relevance"]) for v in labels.values()), reverse=True)[:k]
    dcg = lambda values: sum((2 ** value - 1) / math.log2(i + 2) for i, value in enumerate(values))
    return {
        "precision_at_k": sum(g > 0 for g in gains) / k,
        "ndcg_at_k": dcg(gains) / dcg(ideal) if dcg(ideal) else 0,
        "negative_rate": sum(bool(labels[p["arxiv_id"]].get("negative")) for p in selected) / max(1, len(selected)),
        "topic_count": len({t for p in selected for t in labels[p["arxiv_id"]].get("topics", [])}),
        "evaluated": len(selected), "k": k,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(evaluate(json.loads(args.snapshot.read_text(encoding="utf-8")),
        json.loads(args.labels.read_text(encoding="utf-8")), args.k), indent=2))
