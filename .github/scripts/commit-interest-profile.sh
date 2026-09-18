#!/usr/bin/env bash
set -euo pipefail

# Stage archives with the profile before acknowledging any external feedback.
PYTHONPATH=src python -m zotero_arxiv_daily.profile_storage
git add data/interest_profile.json
if [[ -d data/interest_profile.runs ]]; then
  git add data/interest_profile.runs/
fi
if ! git diff --cached --quiet; then
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git commit -m "$1"
  git push
fi
