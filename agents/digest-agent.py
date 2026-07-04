"""
Агент формирования дайджеста.
Читает data/processed/*.json за сегодня, генерирует Markdown-дайджест,
после успешного сохранения обновляет data/state.json (отмечает сообщения
как прочитанные по максимальному message_id на канал).
Требует: pip install groq python-dotenv
Использование: python digest-agent.py [--date YYYY-MM-DD] [--publish] [--send-only]
"""

import argparse
import json
import os
import re
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
DIGESTS_DIR = ROOT / "digests"
STATE_FILE = ROOT / "data" / "state.json"

openai_client = OpenAI()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

DIGEST_SYSTEM = """Ты — редактор аналитического дайджеста.
Получаешь список сигналов (JSON) и формируешь структурированный Markdown-дайджест на русском языке.

Структура дайджеста:
# Дайджест [дата]

## Главное
- 3-5 ключевых событий дня одной строкой каждое

## По темам
### ИИ и технологии
### Бизнес и экономика
### Финансы и рынки

## Тренды
Краткий абзац о прослеживаемых трендах.

## Требует внимания
Аномалии, срочные события, неожиданные сигналы.

Будь лаконичен. Без воды. Каждый пункт — конкретный факт или вывод.
В конце каждого пункта добавляй ссылку на источник в формате Markdown: [channel_name](post_url)
Используй точные значения полей channel_name и post_url из соответствующего сигнала. Не изменяй URL."""


def load_channel_meta() -> dict[str, dict]:
    sources_file = ROOT / "sources" / "channels.json"
    with open(sources_file, encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for ch in data["channels"]:
        username = ch["url"].rstrip("/").rsplit("/", 1)[-1]
        result[ch["id"]] = {"name": ch["name"], "username": username}
    return result


def load_signals(date_str: str) -> list[dict]:
    channel_meta = load_channel_meta()
    signals = []
    for f in PROCESSED_DIR.glob(f"{date_str}-*-processed.json"):
        with open(f, encoding="utf-8") as fp:
            posts = json.load(fp)
        for post in posts:
            if post.get("classification", {}).get("signal"):
                ch_id = post.get("channel_id", "")
                meta = channel_meta.get(ch_id, {"name": ch_id, "username": ch_id})
                msg_id = post.get("id", "")
                post_url = f"https://t.me/{meta['username']}/{msg_id}" if msg_id else f"https://t.me/{meta['username']}"
                signals.append({
                    "id": post.get("id", 0),
                    "channel": ch_id,
                    "channel_name": meta["name"],
                    "post_url": post_url,
                    "date": post.get("date"),
                    "summary": post["classification"].get("summary"),
                    "category": post["classification"].get("category"),
                    "score": post["classification"].get("score"),
                    "keywords": post["classification"].get("keywords", []),
                    "text": post.get("text", "")[:500],
                })
    return sorted(signals, key=lambda x: x.get("score", 0), reverse=True)


def load_all_posts(date_str: str) -> dict[str, list[dict]]:
    """Загружает все посты за date_str, сгруппированные по каналу."""
    channel_meta = load_channel_meta()
    by_channel: dict[str, list[dict]] = {}
    for f in sorted(PROCESSED_DIR.glob(f"{date_str}-*-processed.json")):
        with open(f, encoding="utf-8") as fp:
            posts = json.load(fp)
        for post in posts:
            ch_id = post.get("channel_id", "")
            summary = post.get("classification", {}).get("summary", "")
            if not summary:
                continue
            meta = channel_meta.get(ch_id, {"name": ch_id, "username": ch_id})
            msg_id = post.get("id", "")
            post_url = f"https://t.me/{meta['username']}/{msg_id}" if msg_id else f"https://t.me/{meta['username']}"
            by_channel.setdefault(ch_id, []).append({
                "channel_name": meta["name"],
                "post_url": post_url,
                "summary": summary,
                "signal": post.get("classification", {}).get("signal", False),
            })
    return by_channel


def format_all_posts_section(by_channel: dict[str, list[dict]]) -> str:
    lines = ["\n\n---\n\n## Все материалы"]
    for ch_id, posts in by_channel.items():
        if not posts:
            continue
        lines.append(f"\n### {posts[0]['channel_name']}")
        for p in posts:
            marker = "★" if p["signal"] else "·"
            lines.append(f"- {marker} [{p['summary']}]({p['post_url']})")
    return "\n".join(lines)


def update_state(date_str: str) -> None:
    """Обновляет state.json: записывает максимальный message_id по каждому каналу
    из всех обработанных постов за date_str (не только сигналов)."""
    state: dict[str, int] = {}
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)

    updated: dict[str, int] = {}
    for f in PROCESSED_DIR.glob(f"{date_str}-*-processed.json"):
        with open(f, encoding="utf-8") as fp:
            posts = json.load(fp)
        for post in posts:
            ch_id = post.get("channel_id", "")
            msg_id = post.get("id", 0)
            if ch_id and msg_id > state.get(ch_id, 0):
                state[ch_id] = msg_id
                updated[ch_id] = msg_id

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    if updated:
        print(f"State updated: {updated}")
    else:
        print("State unchanged (no new max IDs found).")


def generate_digest(signals: list[dict], date_str: str) -> str:
    payload = json.dumps(signals[:100], ensure_ascii=False)
    messages = [
        {"role": "system", "content": DIGEST_SYSTEM},
        {"role": "user", "content": f"Дата: {date_str}\n\nСигналы:\n{payload}"},
    ]
    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=2048,
        messages=messages,
    )
    return response.choices[0].message.content


TG_MAX = 4096


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_to_html(text: str) -> str:
    """Convert basic Markdown to Telegram HTML."""
    lines = []
    for line in text.splitlines():
        if line.startswith("### "):
            line = f"<b>{_escape(line[4:])}</b>"
        elif line.startswith("## "):
            line = f"\n<b>{_escape(line[3:])}</b>"
        elif line.startswith("# "):
            line = f"\n<b>{_escape(line[2:])}</b>"
        else:
            links = {}
            def stash_link(m):
                key = f"\x00LINK{len(links)}\x00"
                links[key] = f'<a href="{m.group(2)}">{_escape(m.group(1))}</a>'
                return key
            line = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", stash_link, line)
            line = _escape(line)
            line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
            line = re.sub(r"\*(.+?)\*", r"<i>\1</i>", line)
            for key, val in links.items():
                line = line.replace(_escape(key), val)
        lines.append(line)
    return "\n".join(lines)


def send_telegram(text: str) -> None:
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    html = md_to_html(text)
    chunks = []
    while html:
        if len(html) <= TG_MAX:
            chunks.append(html)
            break
        split_at = html.rfind("\n", 0, TG_MAX)
        if split_at == -1:
            split_at = TG_MAX
        chunks.append(html[:split_at])
        html = html[split_at:].lstrip("\n")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for i, chunk in enumerate(chunks, 1):
        payload = json.dumps({
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        if not result.get("ok"):
            raise RuntimeError(f"Telegram error: {result}")
        print(f"  sent chunk {i}/{len(chunks)}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(),
                        help="Дата дайджеста YYYY-MM-DD (по умолчанию — сегодня)")
    parser.add_argument("--publish", action="store_true",
                        help="Опубликовать дайджест в Telegram после генерации")
    parser.add_argument("--send-only", action="store_true",
                        help="Только отправить уже готовый дайджест в Telegram")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    date_str = args.date.isoformat()

    if args.send_only:
        digest_file = DIGESTS_DIR / f"{date_str}-digest.md"
        text = digest_file.read_text(encoding="utf-8")
        print(f"Sending existing digest: {digest_file.name}")
        send_telegram(text)
        print("Done.")
        return

    signals = load_signals(date_str)
    all_posts = load_all_posts(date_str)
    total = sum(len(v) for v in all_posts.values())
    print(f"Loaded {len(signals)} signals, {total} total posts for {date_str}")

    if not total:
        print("No posts found — updating state anyway to mark as read.")
        update_state(date_str)
        return

    if signals:
        digest = generate_digest(signals, date_str)
    else:
        digest = f"# Дайджест {date_str}\n\nНовых значимых сигналов нет."

    digest += format_all_posts_section(all_posts)

    out_file = DIGESTS_DIR / f"{date_str}-digest.md"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(digest)
    print(f"Digest saved: {out_file.name}")

    update_state(date_str)

    if args.publish:
        print("Publishing to Telegram...")
        send_telegram(digest)
        print("Done.")
    else:
        print("Digest saved (use --publish to send to Telegram).")


if __name__ == "__main__":
    main()
