"""Subscription matching shared with the browser through one alias registry."""
import json
import re
import unicodedata
from pathlib import Path

ALIASES = json.loads((Path(__file__).resolve().parents[1] / "data/institution_aliases.json").read_text(encoding="utf-8"))


def normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+|_", " ", unicodedata.normalize("NFKC", value).lower()).split())


def matches_author(value: str, subscription: str) -> bool:
    return bool(normalize(subscription)) and normalize(value) == normalize(subscription)


def matches_institution(value: str, subscription: str) -> bool:
    query = normalize(subscription)
    if not query:
        return False
    names = [query]
    for canonical, aliases in ALIASES.items():
        group = [normalize(name) for name in [canonical, *aliases]]
        if query in group:
            names = group
            break
    # Directional match: a department may contain an institution, not vice versa.
    return any(f" {name} " in f" {normalize(value)} " for name in names)
