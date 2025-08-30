#!/usr/bin/env bash
set -euo pipefail

# Reproducible runner for WWE and AEW rosters
# Usage: ./run_rosters.sh [out_dir] [rate] [max_pages] [profiles:true|false] [profile_limit]
# Defaults: out_dir=./data/rosters, rate=1.0, max_pages=0 (all), profiles=true, profile_limit=0 (all)

OUT_DIR=${1:-./data/rosters}
RATE=${2:-1.0}
MAX_PAGES=${3:-0}
PROFILES=${4:-true}
PROFILE_LIMIT=${5:-0}

# Ensure we run from the project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

uv run cagematch-scraper rosters \
  --promotions wwe --promotions aew \
  --out-dir "$OUT_DIR" \
  --rate "$RATE" \
  --max-pages "$MAX_PAGES" \
  $( [ "$PROFILES" = "true" ] && echo "--profiles" || echo "--no-profiles" ) \
  --profile-limit "$PROFILE_LIMIT"