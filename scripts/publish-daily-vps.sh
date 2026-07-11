#!/bin/bash
# Публикация готового дайджеста в Telegram-канал Radar.
# Запускается на VPS после того, как облачный Routine (claude.ai) закоммитил
# дайджест обратно в репозиторий — облачная песочница не имеет сетевого
# доступа к api.telegram.org, поэтому публикация вынесена сюда.
set -e

cd /opt/radar
source venv/bin/activate

git pull

DATE=$(date -u +%Y-%m-%d)
if [ ! -f "digests/${DATE}-digest.md" ]; then
  echo "Digest for ${DATE} not found yet — nothing to publish."
  exit 0
fi

python agents/digest-agent.py --send-only --date "${DATE}"
