#!/usr/bin/env bash
# End-to-end pipeline: extract mentions from collected URLs → import to DB.
# Reads `wechat_links.jsonl` (or whatever --in arg given), writes `wechat_mentions.jsonl`,
# then runs import script.
#
# Usage:
#   bash backend/scripts/mentions/run_wechat_pipeline.sh
#   bash backend/scripts/mentions/run_wechat_pipeline.sh path/to/links.jsonl
set -euo pipefail
cd "$(dirname "$0")/../.."

LINKS=${1:-scripts/mentions/wechat_links.jsonl}
MENTIONS=${MENTIONS_OUT:-scripts/mentions/wechat_mentions.jsonl}

if [ ! -s "$LINKS" ]; then
  echo "ERROR: links file empty or missing: $LINKS" >&2
  exit 1
fi

echo "=== Step 1/2: extract mentions ($LINKS → $MENTIONS) ==="
python scripts/mentions/extract_mentions.py --in "$LINKS" --out "$MENTIONS"

echo
echo "=== Step 2/2: import to DB ==="
python scripts/import_advisor_mentions.py "$MENTIONS" --dedup-by-url

echo "=== Done ==="
