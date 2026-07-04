"""
Публикация адаптированного поста из posts/*.json в Telegram-канал Radar.

Читает JSON-файл, созданный скиллом post-adapter (agents/post-adapter.md),
достает контент нужной площадки и отправляет его через Telegram Bot API
в TELEGRAM_CHAT_ID (тот же бот и та же переменная, что использует
agents/digest-agent.py — переключить публикацию с чата на канал можно
одной правкой .env, без изменений в коде).

Поддерживает обе схемы, которые встречаются в posts/:
  {"source": {...}, "platforms": {"telegram": {"content": "..."}}}
  {"source": {...}, "telegram": {"content": "..."}}

Требует: pip install python-dotenv
Использование:
  python scripts/publish-post.py posts/2026-07-02-legaltech-hub-map-social-content.json telegram
  python scripts/publish-post.py posts/2026-07-02-legaltech-hub-map-social-content.json telegram --dry-run
"""

import argparse
import json
import os
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
TG_MAX = 4096


def load_content(post_file: Path, platform: str) -> tuple[str, dict]:
    with open(post_file, encoding="utf-8") as f:
        data = json.load(f)

    source = data.get("source", {})
    platform_data = data.get("platforms", {}).get(platform) or data.get(platform)

    if not platform_data or not platform_data.get("content"):
        available = list(data.get("platforms", {}).keys()) or [
            k for k in data.keys() if k != "source"
        ]
        raise ValueError(
            f"В файле {post_file.name} нет площадки '{platform}'. "
            f"Доступные площадки: {available}"
        )

    return platform_data["content"], source


def send_telegram(text: str) -> None:
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    if len(text) > TG_MAX:
        raise ValueError(
            f"Текст поста длиннее {TG_MAX} символов ({len(text)}) — Telegram не примет одним сообщением."
        )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")


def parse_args():
    parser = argparse.ArgumentParser(description="Опубликовать пост из posts/ в Telegram-канал Radar.")
    parser.add_argument("post_file", type=Path, help="Путь к JSON-файлу в posts/ (или post/)")
    parser.add_argument("platform", nargs="?", default="telegram", help="Площадка внутри JSON (по умолчанию telegram)")
    parser.add_argument("--dry-run", action="store_true", help="Показать текст поста, но не отправлять")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    post_file = args.post_file if args.post_file.is_absolute() else ROOT / args.post_file

    content, source = load_content(post_file, args.platform)

    print(f"Файл: {post_file.name}")
    if source:
        print(f"Источник: {source.get('title', '[без названия]')} ({source.get('url', '')})")
    print(f"Площадка: {args.platform}")
    print("--- Текст поста ---")
    print(content)
    print("--------------------")

    if args.dry_run:
        print("Dry-run: сообщение не отправлено.")
        return

    send_telegram(content)
    print("Опубликовано в Telegram.")


if __name__ == "__main__":
    main()
