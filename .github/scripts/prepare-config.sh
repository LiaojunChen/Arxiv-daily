#!/usr/bin/env bash
set -euo pipefail

config_path="config/custom.yaml"
custom_config="${CUSTOM_CONFIG:-}"

if [[ -n "${custom_config//[[:space:]]/}" ]]; then
  printf "%b\n" "$custom_config" > "$config_path"
  echo "Loaded $config_path from CUSTOM_CONFIG."
else
  echo "CUSTOM_CONFIG is empty; using checked-in $config_path."
fi

if [[ ! -s "$config_path" ]]; then
  echo "::error file=$config_path::$config_path is empty. Set the CUSTOM_CONFIG repository variable or keep a non-empty checked-in custom config."
  exit 1
fi

echo "Effective $config_path (sensitive scalar values redacted):"
sed -E 's/^([[:space:]]*(api_key|key|sender_password|password|token|secret):[[:space:]]*).+$/\1***redacted***/I' "$config_path"
