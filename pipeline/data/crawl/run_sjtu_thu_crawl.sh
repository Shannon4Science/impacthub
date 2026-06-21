#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/dhwfile/raise/user/linhonglin/impacthub"
cd "$ROOT/pipeline"

export SEMANTIC_SCHOLAR_RPS="${SEMANTIC_SCHOLAR_RPS:-0.05}"

python crawl/05_ss_match.py \
  --auto-match \
  --input ../pipeline/data/crawl/ss_match_上交.json \
  --output ../pipeline/data/crawl/ss_results_validated_上交_plain_full.json \
  --min-score 82 \
  --search-limit 3 \
  --max-queries 1 \
  --plain-first \
  --concurrency 2

python crawl/06_user_portfolios.py \
  --input ../pipeline/data/crawl/ss_results_validated_上交_plain_full.json

python crawl/05_ss_match.py \
  --auto-match \
  --input ../pipeline/data/crawl/ss_match_清华.json \
  --output ../pipeline/data/crawl/ss_results_validated_清华_plain_full.json \
  --min-score 82 \
  --search-limit 3 \
  --max-queries 1 \
  --plain-first \
  --concurrency 2

python crawl/06_user_portfolios.py \
  --input ../pipeline/data/crawl/ss_results_validated_清华_plain_full.json
