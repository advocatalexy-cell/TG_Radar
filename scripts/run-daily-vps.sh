#!/bin/bash
# Nightly collection for the previous Moscow calendar day.
set -euo pipefail
cd /opt/radar
source venv/bin/activate
mkdir -p data/raw
set -a; source <(sed 's/\r$//' .env); set +a
source scripts/vps-common.sh
trap alert_on_error ERR
git_pull_retry --rebase
DATE=$(TZ=Europe/Moscow date -d yesterday +%F)
# The November 12 issue was already published before the schedule migration.
if [[ "$DATE" < "2026-11-13" ]]; then
  echo "Skipping previously published transition day: $DATE"
  exit 0
fi
if [ -f "digests/${DATE}-digest.md" ]; then
  echo "Digest already exists for $DATE; preserving collected data."
  exit 0
fi
python scripts/fetch-posts.py --date "$DATE"
python scripts/filter-signals.py --date "$DATE"
git add data/processed sources/channels.json
if ! git diff --cached --quiet; then
  git commit -m "Nightly Moscow calendar data for $DATE"
  git_pull_retry --rebase
  git push
else
  echo "No new processed data to commit."
fi
