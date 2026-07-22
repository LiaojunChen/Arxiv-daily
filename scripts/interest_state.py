"""Read the persisted interest profile for the lightweight Pages workflow.

The email service owns writes to ``data/interest_profile.json``.  The Pages
workflow only needs the stable, public subset of that state, so this reader is
kept dependency-free and deliberately does not import the mail application.
"""

from __future__ import annotations

import json
from pathlib import Path


def _terms(items: object, *, limit: int = 10) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        term = item.get("term") if isinstance(item, dict) else item
        if not isinstance(term, str):
            continue
        term = " ".join(term.strip().lower().split())
        if term and term not in seen:
            result.append(term)
            seen.add(term)
        if len(result) >= limit:
            break
    return result


def load_interest_state(path: str | Path) -> tuple[list[str], list[str]]:
    """Return positive and suppressed terms from the shared profile state."""
    profile_path = Path(path)
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[WARN] Could not read interest profile {profile_path}: {exc}")
        return [], []
    if not isinstance(data, dict):
        print(f"[WARN] Interest profile {profile_path} is not a JSON object.")
        return [], []
    return _terms(data.get("keywords")), _terms(data.get("negative_keywords"))
