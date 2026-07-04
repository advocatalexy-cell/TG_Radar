#!/bin/bash
# Ежедневный сбор и подготовка данных Radar на VPS.
# Мультиагентный анализ выполняется отдельно облачным Routine (claude.ai),
# который коммитит готовый дайджест обратно в этот репозиторий.
set -e

cd /opt/radar
source venv/bin/activate
mkdir -p data/raw

python scripts/fetch-posts.py
python scripts/filter-signals.py
python agents/digest-agent.py

# digest-agent.py пишет свой упрощённый дайджест как побочный эффект обновления
# state.json — не нужен, авторитетную версию собирает облачный Routine.
rm -f "digests/$(date -u +%Y-%m-%d)-digest.md"

git add data/processed data/state.json
if ! git diff --cached --quiet; then
  git commit -m "Daily data collection $(date -u +%Y-%m-%d)"
  git push
else
  echo "No new processed data to commit."
fi
