#!/usr/bin/env bash
set -euo pipefail

missing=()
for name in SENDER RECEIVER SENDER_PASSWORD; do
  if [[ -z "${!name:-}" ]]; then
    missing+=("$name")
  fi
done

if ((${#missing[@]})); then
  echo "enabled=false" >> "$GITHUB_OUTPUT"
  joined="$(IFS=', '; echo "${missing[*]}")"
  echo "::notice title=Email workflow skipped::Missing repository secrets: $joined"
  {
    echo "### Email workflow skipped"
    echo
    echo "Configure these repository secrets to enable email delivery: \`$joined\`."
    echo "The GitHub Pages paper feed is handled by the separate Daily ArXiv Paper Fetch workflow."
  } >> "$GITHUB_STEP_SUMMARY"
  exit 0
fi

echo "enabled=true" >> "$GITHUB_OUTPUT"
echo "Email configuration is present."
