#!/bin/bash
# Ежедневный сбор и подготовка данных Radar на VPS.
# Публикация и мультиагентный анализ выполняются отдельно облачным Routine (claude.ai).
set -e

cd /opt/radar
source venv/bin/activate
mkdir -p data/raw

python scripts/fetch-posts.py
python scripts/filter-signals.py
python agents/digest-agent.py

git add data/processed data/state.json
if ! git diff --cached --quiet; then
  git commit -m "Daily data collection $(date -u +%Y-%m-%d)"
  git push
else
  echo "No new processed data to commit."
fi
