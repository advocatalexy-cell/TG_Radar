"""
Синхронизация sources/channels.json с текущим составом папок Telegram.

В отличие от import-tg-folders.py (интерактивный, только добавляет новые
каналы), этот скрипт:
  - не интерактивный — папки передаются аргументом, можно звать по cron;
  - помимо добавления новых каналов ещё и деактивирует (active: false) те,
    что были ранее импортированы из папки и с тех пор пропали из неё —
    запись не удаляется, чтобы не терять историю обработанных данных;
  - помечает управляемые записи полем "source_folder", чтобы отличать их
    от каналов с тем же тегом, добавленных вручную (их синк не трогает);
  - при первом запуске один раз проставляет "source_folder" старым записям,
    у которых он ещё не заполнен, но notes содержит текст
    "Импортирован из папки «...»" от прежнего ручного импорта.

Требует: pip install telethon python-dotenv
Переменные окружения: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE,
(на VPS) TELEGRAM_SESSION_STRING — иначе используется локальный файл
radar_session.session (тот же принцип, что в fetch-posts.py).

Использование:
  python scripts/sync-tg-folders.py --folders "Lawyer,Ai"
  python scripts/sync-tg-folders.py --folders "Lawyer,Ai" --dry-run
"""

import argparse
import asyncio
import json
import re
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import os

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import DialogFilter

load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE = os.environ["TELEGRAM_PHONE"]

SESSION = StringSession(os.environ["TELEGRAM_SESSION_STRING"]) if os.environ.get("TELEGRAM_SESSION_STRING") else "radar_session"

ROOT = Path(__file__).parent.parent
SOURCES_FILE = ROOT / "sources" / "channels.json"

LEGACY_NOTE_RE = re.compile(r"Импортирован из папки «(.+?)»")


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
        f.write("\n")


def folder_title(folder: DialogFilter) -> str:
    return folder.title.text if hasattr(folder.title, "text") else str(folder.title)


def backfill_legacy_source_folder(data: dict) -> int:
    """Проставляет source_folder старым записям по тексту notes. Возвращает число изменений."""
    updated = 0
    for ch in data["channels"]:
        if ch.get("source_folder"):
            continue
        m = LEGACY_NOTE_RE.search(ch.get("notes") or "")
        if m:
            ch["source_folder"] = m.group(1)
            updated += 1
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folders", required=True,
                         help="Названия папок Telegram через запятую, например: 'Lawyer,Ai'")
    parser.add_argument("--dry-run", action="store_true",
                         help="Показать, что изменится, но не писать channels.json")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    requested = [f.strip() for f in args.folders.split(",") if f.strip()]

    data = load_channels_json()
    backfilled = backfill_legacy_source_folder(data)
    if backfilled:
        print(f"Проставлен source_folder у {backfilled} старых записей (по тексту notes).")

    by_id = {ch["id"]: ch for ch in data["channels"]}

    async with TelegramClient(SESSION, API_ID, API_HASH) as client:
        await client.start(phone=PHONE)

        filters = await client(GetDialogFiltersRequest())
        folders_by_title = {
            folder_title(f).lower(): f for f in filters.filters if isinstance(f, DialogFilter)
        }

        added, reactivated, deactivated, untouched_new = [], [], [], []

        for requested_name in requested:
            folder = folders_by_title.get(requested_name.lower())
            if not folder:
                print(f"[ПРОПУЩЕНО] Папка «{requested_name}» не найдена в аккаунте Telegram.")
                continue

            title_text = folder_title(folder)
            folder_tag = slugify(title_text)
            current_ids = set()

            for peer in folder.include_peers:
                try:
                    entity = await client.get_entity(peer)
                except Exception as e:
                    print(f"  [пропущен] {peer}: {e}")
                    continue

                if not hasattr(entity, "username") or not entity.username:
                    continue
                if not hasattr(entity, "broadcast") and not hasattr(entity, "megagroup"):
                    continue

                channel_id = entity.username.lower()
                current_ids.add(channel_id)
                title = getattr(entity, "title", entity.username)

                existing = by_id.get(channel_id)
                if existing is None:
                    new_entry = {
                        "id": channel_id,
                        "name": title,
                        "url": f"https://t.me/{entity.username}",
                        "type": "telegram",
                        "priority": "medium",
                        "tags": [folder_tag],
                        "active": True,
                        "signal_ratio": None,
                        "source_folder": title_text,
                        "notes": f"Импортирован из папки «{title_text}» (sync)",
                    }
                    data["channels"].append(new_entry)
                    by_id[channel_id] = new_entry
                    added.append(channel_id)
                elif existing.get("source_folder") == title_text and not existing.get("active", True):
                    existing["active"] = True
                    reactivated.append(channel_id)
                elif existing.get("source_folder") is None:
                    # Канал уже есть (например, добавлен вручную), но теперь также
                    # входит в эту папку — не трогаем его active/notes, только берём
                    # под управление синка на будущее.
                    existing["source_folder"] = title_text
                    untouched_new.append(channel_id)

            for ch in data["channels"]:
                if (ch.get("source_folder") == title_text
                        and ch["id"] not in current_ids
                        and ch.get("active", True)):
                    ch["active"] = False
                    today = date.today().isoformat()
                    ch["notes"] = (ch.get("notes") or "").rstrip()
                    ch["notes"] += f" [пропал из папки «{title_text}», деактивирован {today}]"
                    deactivated.append(ch["id"])

    print(f"\nДобавлено новых: {len(added)} {added}")
    print(f"Реактивировано (вернулись в папку): {len(reactivated)} {reactivated}")
    print(f"Деактивировано (пропали из папки): {len(deactivated)} {deactivated}")
    if untouched_new:
        print(f"Взято под управление синка (уже были в channels.json): {len(untouched_new)} {untouched_new}")

    changed = bool(added or reactivated or deactivated or untouched_new or backfilled)
    if not changed:
        print("Изменений нет.")
        return

    if args.dry_run:
        print("\n--dry-run: channels.json НЕ изменён.")
    else:
        save_channels_json(data)
        print(f"\nФайл обновлён: {SOURCES_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
