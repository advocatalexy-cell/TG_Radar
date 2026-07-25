#!/bin/bash
# Общие функции для cron-скриптов VPS (run-daily-vps.sh, publish-daily-vps.sh):
# retry для git pull при временных сетевых/DNS сбоях и алерт в Telegram при падении шага.
# Использование: `source scripts/vps-common.sh` после `cd /opt/radar` и загрузки .env.

# git_pull_retry [аргументы для git pull] — до 3 попыток с паузой 15с между ними.
git_pull_retry() {
  local attempts=3
  local delay=15
  local i
  for ((i = 1; i <= attempts; i++)); do
    if git pull "$@"; then
      return 0
    fi
    echo "git pull $* не удался (попытка ${i}/${attempts})" >&2
    [ "$i" -lt "$attempts" ] && sleep "$delay"
  done
  return 1
}

# send_alert "текст" — отправляет сообщение в Telegram через TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID.
# Тихо пропускает отправку, если токен/чат не заданы или Telegram недоступен — не должна
# сама уронить вызывающий скрипт.
send_alert() {
  local message="$1"
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "send_alert: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы, алерт не отправлен" >&2
    return 0
  fi
  curl -s -m 10 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${message}" \
    > /dev/null || echo "send_alert: не удалось отправить алерт в Telegram" >&2
}

# alert_on_error — обработчик для `trap alert_on_error ERR`. Собирает сообщение
# из имени упавшего скрипта, команды и даты и шлёт через send_alert.
alert_on_error() {
  local exit_code=$?
  send_alert "🔴 Radar: сбой в $(basename "$0") — шаг «${BASH_COMMAND}», дата $(date -u +%Y-%m-%d), exit=${exit_code}"
}
