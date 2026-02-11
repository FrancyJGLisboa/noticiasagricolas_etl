#!/usr/bin/env bash
# One-time script: uploads current Parquet + state data as the initial
# GitHub Release so the daily workflow has data to start from.
#
# Run this ONCE after your first backfill is done:
#   ./scripts/seed_github_release.sh
#
# Requires: gh CLI authenticated (gh auth login)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "Packing data/parquet + data/parquet_basis + data/state..."
tar czf /tmp/etl-data.tar.gz \
  data/parquet/ \
  data/parquet_basis/ \
  data/state/
ls -lh /tmp/etl-data.tar.gz

echo ""
echo "Uploading to GitHub Release 'data-latest'..."
gh release delete data-latest --yes 2>/dev/null || true
gh release create data-latest /tmp/etl-data.tar.gz \
  --title "ETL Data (auto-updated)" \
  --notes "Initial seed: $(date -u +%Y-%m-%d %H:%M UTC)" \
  --latest=false

echo ""
echo "Done. The daily workflow will now pick up this data."
