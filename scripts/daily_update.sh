#!/usr/bin/env bash
# Daily update script for Noticias Agricolas ETL.
#
# Usage:
#   ./scripts/daily_update.sh           # full update (all commodities)
#   ./scripts/daily_update.sh soja      # single commodity
#
# Cron example (run at 7pm BRT every weekday):
#   0 19 * * 1-5 /Users/francylisboacharuto/noticiasagricolas_etl/scripts/daily_update.sh >> /tmp/na-etl-daily.log 2>&1
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv/bin/activate"
LOG_DATE=$(date +%Y-%m-%d_%H%M)

# Activate venv
if [ -f "$VENV" ]; then
    source "$VENV"
else
    echo "ERROR: Virtual environment not found at $VENV"
    exit 1
fi

echo "=== na-etl daily update — $LOG_DATE ==="

# Build the command
CMD="na-etl daily"
if [ "${1:-}" != "" ]; then
    CMD="$CMD -c $1"
    echo "Commodity filter: $1"
fi

# Run
$CMD

echo "=== Done — $(date +%Y-%m-%d_%H%M) ==="
