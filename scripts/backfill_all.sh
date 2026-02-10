#!/usr/bin/env bash
# Parallel backfill for all target categories.
# Runs 4 streams to reduce ~26h → ~6h (conservative) or ~3h (optimistic).
#
# Usage:
#   ./scripts/backfill_all.sh              # default 0.5s delay
#   ./scripts/backfill_all.sh --delay 1.0  # safer, slower
#
# Logs go to data/logs/<category>.log
# Monitor: tail -f data/logs/*.log
# Dashboard: na-etl status --summary

set -euo pipefail
cd "$(dirname "$0")/.."

DELAY="${1:-0.5}"
if [[ "$1" == "--delay" ]]; then DELAY="${2:-0.5}"; fi

LOGDIR="data/logs"
mkdir -p "$LOGDIR"

NAETL=".venv/bin/na-etl"
START_DATE="2020-01-01"

echo "=== Parallel Backfill ==="
echo "  Delay: ${DELAY}s per request"
echo "  Logs:  ${LOGDIR}/"
echo "  Monitor: tail -f ${LOGDIR}/*.log"
echo ""

# Stream 1: oilseeds (20 indicators — soja, algodao, amendoim)
echo "Starting OILSEEDS (20 indicators)..."
$NAETL backfill --category oilseeds --start-date "$START_DATE" --delay "$DELAY" \
  > "$LOGDIR/oilseeds.log" 2>&1 &
PID_OILSEEDS=$!

# Stream 2: grains (30 indicators — milho, trigo, arroz, sorgo, feijao)
echo "Starting GRAINS (30 indicators)..."
$NAETL backfill --category grains --start-date "$START_DATE" --delay "$DELAY" \
  > "$LOGDIR/grains.log" 2>&1 &
PID_GRAINS=$!

# Stream 3: sugar + biofuels (11 indicators — sucroenergetico)
echo "Starting SUGAR (6 indicators)..."
$NAETL backfill --category sugar --start-date "$START_DATE" --delay "$DELAY" \
  > "$LOGDIR/sugar.log" 2>&1 &
PID_SUGAR=$!

# Wait a bit to stagger the initial burst, then start biofuels
sleep 5
echo "Starting BIOFUELS (5 indicators)..."
$NAETL backfill --category biofuels --start-date "$START_DATE" --delay "$DELAY" \
  > "$LOGDIR/biofuels.log" 2>&1 &
PID_BIOFUELS=$!

echo ""
echo "All streams launched. PIDs:"
echo "  oilseeds:  $PID_OILSEEDS"
echo "  grains:    $PID_GRAINS"
echo "  sugar:     $PID_SUGAR"
echo "  biofuels:  $PID_BIOFUELS"
echo ""
echo "Waiting for all to finish..."
echo "  Check progress: na-etl status --summary"
echo "  Check logs:     tail -f $LOGDIR/grains.log"
echo ""

# Wait for all and report
FAILED=0
for PID in $PID_OILSEEDS $PID_GRAINS $PID_SUGAR $PID_BIOFUELS; do
  if ! wait $PID; then
    echo "WARNING: PID $PID exited with error"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "=== Backfill Complete ==="
if [ $FAILED -gt 0 ]; then
  echo "  $FAILED stream(s) had errors — check logs."
else
  echo "  All 4 streams finished successfully."
fi
echo ""
$NAETL status --summary
