"""
Импорт каналов из папок Telegram в sources/channels.json.

Показывает список папок — пользователь выбирает нужные.
Добавляет только новые каналы (без дублей).

Требует: pip install telethon python-dotenv
Переменные окружения: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE

Использование:
  python scripts/import-tg-folders.py
"""

import asyncio
import json
import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import os

from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import DialogFilter, InputPeerChannel, InputPeerChat

load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE = os.environ["TELEGRAM_PHONE"]

ROOT = Path(__file__).parent.parent
SOURCES_FILE = ROOT / "sources" / "channels.json"


def slugify(name: str) -> str:
    """Превращает название папки в тег: 'Legal Tech' → 'legal-tech'."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    return name


def load_channels_json() -> dict:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_channels_json(data: dict) -> None:
    data["updated"] = date.today().isoformat()
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def main() -> None:
    async with TelegramClient("radar_session", API_ID, API_HASH) as client:
        await client.start(phone=PHONE)

        # Получаем папки
        filters = await client(GetDialogFiltersRequest())
        folders = [f for f in filters.filters if isinstance(f, DialogFilter)]

        if not folders:
            print("Папок не найдено.")
            return

        # Показываем список
        print("\nДоступные папки Telegram:\n")
        for i, folder in enumerate(folders, 1):
            print(f"  {i}. {folder.title}")

        # Выбор пользователя
        print("\nВведи номера папок через запятую (например: 1,3) или 'all' для всех:")
        raw = input("> ").strip()

        if raw.lower() == "all":
            selected = folders
        else:
            indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
            selected = [folders[i] for i in indices if 0 <= i < len(folders)]

        if not selected:
            print("Ничего не выбрано.")
            return

        # Загружаем текущий channels.json
        data = load_channels_json()
        existing_ids = {ch["id"] for ch in data["channels"]}
        added = 0
        skipped = 0

        print()
        for folder in selected:
            title_text = folder.title.text if hasattr(folder.title, "text") else str(folder.title)
            folder_tag = slugify(title_text)
            print(f"Папка «{title_text}» (тег: {folder_tag}):")

            for peer in folder.include_peers:
                try:
                    entity = await client.get_entity(peer)
                except Exception as e:
                    print(f"  [пропущен] {peer}: {e}")
                    continue

                # Только каналы и супергруппы, не боты и не лички
                if not hasattr(entity, "username") or not entity.username:
                    continue
                if not hasattr(entity, "broadcast") and not hasattr(entity, "megagroup"):
                    continue

                channel_id = entity.username.lower()
                title = getattr(entity, "title", entity.username)

                if channel_id in existing_ids:
                    print(f"  · {title} (@{entity.username}) — уже есть")
                    skipped += 1
                    continue

                data["channels"].append({
                    "id": channel_id,
                    "name": title,
                    "url": f"https://t.me/{entity.username}",
                    "type": "telegram",
                    "priority": "medium",
                    "tags": [folder_tag],
                    "active": True,
                    "signal_ratio": None,
                    "notes": f"Импортирован из папки «{title_text}»",
                })
                existing_ids.add(channel_id)
                print(f"  + {title} (@{entity.username})")
                added += 1

        save_channels_json(data)
        print(f"\nГотово: добавлено {added}, пропущено дублей {skipped}.")
        print(f"Файл обновлён: {SOURCES_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
