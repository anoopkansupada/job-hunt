#!/bin/bash
# Daily Job Hunt Cron Wrapper
# Runs daily Mon-Fri 8 AM EST
# Fetches, ranks, and posts top job matches to #job-hunt

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRAPER_DIR="$SCRIPT_DIR/scraper"
LOG_FILE="$SCRIPT_DIR/logs/daily_job_hunt_$(date +%Y%m%d).log"

# Ensure log dir exists
mkdir -p "$SCRIPT_DIR/logs"

{
  echo "=== Daily Job Hunt Cron Start: $(date) ==="
  
  # Activate venv if it exists
  if [ -d "$SCRIPT_DIR/.venv" ]; then
    echo "Activating venv..."
    source "$SCRIPT_DIR/.venv/bin/activate"
  fi
  
  # Run orchestrator
  echo "Running daily job hunt orchestrator..."
  cd "$SCRAPER_DIR"
  
  python3 daily_job_hunt_cron.py --limit 20
  
  echo "=== Daily Job Hunt Cron Complete: $(date) ==="
} 2>&1 | tee -a "$LOG_FILE"
