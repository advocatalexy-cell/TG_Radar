#!/bin/bash
# Публикация готового дайджеста в Telegram-канал Radar.
# Запускается на VPS после того, как облачный Routine (claude.ai) закоммитил
# дайджест обратно в репозиторий — облачная песочница не имеет сетевого
# доступа к api.telegram.org, поэтому публикация вынесена сюда.
set -e

cd /opt/radar
source venv/bin/activate

set -a; source <(sed 's/\r$//' .env); set +a
source scripts/vps-common.sh
trap alert_on_error ERR

git_pull_retry

DATE=$(date -u +%Y-%m-%d)
DIGEST_FILE="digests/${DATE}-digest.md"

# Облачный Routine иногда коммитит дайджест позже, чем срабатывает этот cron —
# ждём до 3 часов, перепроверяя каждые 10 минут, вместо того чтобы молча
# сдаться при первом же "файла ещё нет".
MAX_WAIT=10800
INTERVAL=600
elapsed=0
while [ ! -f "$DIGEST_FILE" ] && [ "$elapsed" -lt "$MAX_WAIT" ]; do
  sleep "$INTERVAL"
  elapsed=$((elapsed + INTERVAL))
  git_pull_retry
done

if [ ! -f "$DIGEST_FILE" ]; then
  send_alert "🔴 Radar: дайджест за ${DATE} не появился за $((MAX_WAIT / 3600)) ч ожидания — публикация в Telegram пропущена"
  exit 0
fi

python agents/digest-agent.py --send-only --date "${DATE}"
