#!/bin/bash
# Еженедельная синхронизация sources/channels.json с папками Telegram
# "Lawyer" и "Ai" — добавляет новые каналы, деактивирует пропавшие из папок.
set -e

cd /opt/radar
source venv/bin/activate

set -a; source <(sed 's/\r$//' .env); set +a
source scripts/vps-common.sh
trap alert_on_error ERR

git_pull_retry --rebase

python scripts/sync-tg-folders.py --folders "Lawyer,Ai"

git add sources/channels.json
if ! git diff --cached --quiet; then
  git commit -m "Sync channels.json with Telegram folders Lawyer/Ai"
  git_pull_retry --rebase
  git push
else
  echo "No changes to channels.json."
fi
