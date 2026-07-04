"""
Скрипт сбора постов из Telegram-каналов через Telethon.
Требует: pip install telethon python-dotenv
Переменные окружения: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE

Режим работы: собирает только новые (непрочитанные) сообщения на основе
data/state.json, где хранится последний прочитанный message_id по каждому
каналу. Состояние обновляется агентом дайджеста после успешной генерации.

Backfill-режим: --date YYYY-MM-DD — собирает посты только за указанную дату,
не изменяет state.json.
"""

import argparse
import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Message

load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE = os.environ["TELEGRAM_PHONE"]

ROOT = Path(__file__).parent.parent
SOURCES_FILE = ROOT / "sources" / "channels.json"
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
STATE_FILE = ROOT / "data" / "state.json"

INITIAL_LIMIT = 50  # постов при первом запуске канала (нет записи в state)


def load_channels() -> list[dict]:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return [ch for ch in data["channels"] if ch.get("active")]


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def init_state_from_processed() -> dict:
    """Строит начальное состояние из уже обработанных файлов."""
    state: dict[str, int] = {}
    for f in PROCESSED_DIR.glob("*-processed.json"):
        try:
            with open(f, encoding="utf-8") as fp:
                posts = json.load(fp)
            for post in posts:
                ch_id = post.get("channel_id", "")
                msg_id = post.get("id", 0)
                if ch_id and msg_id > state.get(ch_id, 0):
                    state[ch_id] = msg_id
        except Exception:
            continue
    return state


def serialize_message(msg: Message, channel_id: str) -> dict:
    return {
        "id": msg.id,
        "channel_id": channel_id,
        "date": msg.date.isoformat(),
        "text": msg.text or "",
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
        "has_media": msg.media is not None,
    }


async def fetch_channel(client: TelegramClient, channel: dict, min_id: int) -> list[dict]:
    posts = []
    # min_id > 0 — только новее; min_id == 0 — первый запуск, берём INITIAL_LIMIT
    kwargs = {"min_id": min_id} if min_id > 0 else {"limit": INITIAL_LIMIT}
    try:
        async for msg in client.iter_messages(channel["url"], **kwargs):
            if isinstance(msg, Message) and msg.text:
                posts.append(serialize_message(msg, channel["id"]))
    except Exception as exc:
        print(f"[WARN] {channel['id']}: {exc}")
    return posts


async def fetch_channel_by_date(client: TelegramClient, channel: dict, target: date) -> list[dict]:
    posts = []
    # Начинаем с конца целевого дня, идём назад; останавливаемся, когда уходим раньше target
    offset_dt = datetime(target.year, target.month, target.day, tzinfo=timezone.utc) + timedelta(days=1)
    try:
        async for msg in client.iter_messages(channel["url"], offset_date=offset_dt):
            if not isinstance(msg, Message) or not msg.text:
                continue
            msg_date = msg.date.astimezone(timezone.utc).date()
            if msg_date < target:
                break
            if msg_date == target:
                posts.append(serialize_message(msg, channel["id"]))
    except Exception as exc:
        print(f"[WARN] {channel['id']}: {exc}")
    return posts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Backfill: собрать посты только за эту дату")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    if args.date:
        target_date = date.fromisoformat(args.date)
        date_label = args.date
        backfill = True
    else:
        target_date = None
        date_label = date.today().isoformat()
        backfill = False

    channels = load_channels()

    if not backfill:
        state = load_state()
        if not state:
            print("State file not found — initialising from processed files...")
            state = init_state_from_processed()
            if state:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                print(f"  State initialised: {state}")
            else:
                print("  No processed files found — will fetch last 50 posts per channel.")

    mode = f"backfill {date_label}" if backfill else "unread mode"
    print(f"Fetching {len(channels)} channels ({mode})...")
    async with TelegramClient("radar_session", API_ID, API_HASH) as client:
        await client.start(phone=PHONE)
        for channel in channels:
            if backfill:
                posts = await fetch_channel_by_date(client, channel, target_date)
            else:
                min_id = state.get(channel["id"], 0)
                posts = await fetch_channel(client, channel, min_id)
            out_file = RAW_DIR / f"{date_label}-{channel['id']}-raw.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(posts, f, ensure_ascii=False, indent=2)
            label = f"{len(posts)} posts" if posts else "no posts"
            if backfill:
                print(f"  {channel['id']}: {label} -> {out_file.name}")
            else:
                print(f"  {channel['id']}: {label} (last seen id={state.get(channel['id'], 0)}) -> {out_file.name}")


if __name__ == "__main__":
    asyncio.run(main())
