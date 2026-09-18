"""Bound the active profile without losing the snapshots used by old feedback."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile


MAX_ACTIVE_RUNS = 3
MAX_ACTIVE_RUN_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024


def archive_directory(state_path: str | Path) -> Path:
    path = Path(state_path)
    return path.with_name(path.stem + ".runs")


def archive_path(state_path: str | Path, run_id: str) -> Path:
    # Feedback supplies run IDs; never use them directly as filesystem paths.
    name = hashlib.sha256(run_id.encode("utf-8")).hexdigest() + ".json.gz"
    return archive_directory(state_path) / name


def load_archived_run(state_path: str | Path, run_id: str | None) -> dict:
    if not run_id:
        return {}
    path = archive_path(state_path, run_id)
    if not path.exists():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return json.load(source)


def _atomic_write(path: Path, content: bytes) -> None:
    if len(content) >= MAX_FILE_BYTES:
        raise ValueError(f"{path} exceeds the {MAX_FILE_BYTES // 1024 // 1024} MiB profile file budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_profile(state_path: str | Path, data: dict) -> None:
    """Archive oldest runs first, then atomically replace the active profile.

    Archives remain in Git alongside the profile. Preferences, exposure IDs and
    feedback idempotency keys are never pruned. A failed write leaves the old
    profile intact, so archive/profile persistence can safely be retried.
    """
    runs = data.get("runs", {})
    retained = {}
    active_bytes = 0
    active_full = False
    ordered = sorted(runs, key=lambda key: (runs[key].get("generated_at", ""), key), reverse=True)
    for run_id in ordered:
        run = runs[run_id]
        encoded = json.dumps(run, ensure_ascii=False, indent=2).encode("utf-8")
        # Account for the additional indentation inside the profile's runs map.
        size = len(encoded) + 4 * (encoded.count(b"\n") + 1)
        if not active_full and len(retained) < MAX_ACTIVE_RUNS and active_bytes + size <= MAX_ACTIVE_RUN_BYTES:
            retained[run_id] = run
            active_bytes += size
        else:
            # Keep a contiguous newest window, not small but arbitrarily old runs.
            active_full = True
            compact = json.dumps(run, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            _atomic_write(archive_path(state_path, run_id), gzip.compress(compact, mtime=0))

    # Preserve insertion order for stable diffs and existing consumers.
    retained = {key: value for key, value in runs.items() if key in retained}
    saved = {**data, "runs": retained}
    encoded = (json.dumps(saved, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(Path(state_path), encoded)
    data["runs"] = retained


def check_profile_files(state_path: str | Path) -> None:
    path = Path(state_path)
    for candidate in [path, *archive_directory(path).glob("*.json.gz")]:
        if candidate.stat().st_size >= MAX_FILE_BYTES:
            raise ValueError(f"{candidate} exceeds the 50 MiB profile file budget; refusing to commit")


if __name__ == "__main__":
    check_profile_files("data/interest_profile.json")
