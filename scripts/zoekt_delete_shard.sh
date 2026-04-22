#!/usr/bin/env env bash
# zoekt_delete_shard.sh — Manual fallback to delete a Zoekt shard for a repo.
#
# Usage: scripts/zoekt_delete_shard.sh <repo_name>
#
# Zoekt stores shards under ZOEKT_INDEX_DIR (default /data/index).
# Shard files follow the pattern: <repo_name>.*.zoekt
#
# Run this script on the host that runs the zoekt-indexserver container,
# or exec into the container and run it there.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <repo_name>" >&2
  exit 1
fi

REPO="$1"
INDEX_DIR="${ZOEKT_INDEX_DIR:-/data/index}"

if [[ ! -d "$INDEX_DIR" ]]; then
  echo "Index directory not found: $INDEX_DIR" >&2
  echo "Set ZOEKT_INDEX_DIR to the correct path." >&2
  exit 1
fi

SHARDS=("$INDEX_DIR"/${REPO}.*.zoekt 2>/dev/null || true)

if [[ ${#SHARDS[@]} -eq 0 ]] || [[ ! -e "${SHARDS[0]}" ]]; then
  echo "No shards found for repo: $REPO in $INDEX_DIR" >&2
  exit 1
fi

for shard in "${SHARDS[@]}"; do
  echo "Deleting shard: $shard"
  rm -f "$shard"
done

echo "Done. Zoekt will pick up the deletion within its next poll cycle."
