"""
Фильтрация сигналов из сырых данных.
Читает data/raw/*.json, классифицирует посты, сохраняет в data/processed/.
Требует: pip install openai python-dotenv

Режимы:
  --mode date        (по умолчанию) — только посты за указанную --date
  --mode undigested  — посты, не попавшие ни в один предыдущий processed-файл
                       (по channel_id + message_id); обрабатывает все raw-файлы

Использование:
  python filter-signals.py [--date YYYY-MM-DD] [--mode date|undigested]
"""

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
CHANNELS_FILE = ROOT / "sources" / "channels.json"

openai_client = OpenAI()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """Ты — аналитический фильтр для новостного радара.
Получаешь текст поста из Telegram-канала и возвращаешь JSON:
{
  "signal": true/false,        // является ли пост значимым сигналом
  "score": 0.0-1.0,            // релевантность (1 = максимальная)
  "category": "...",           // ai | tech | business | finance | politics | other
  "summary": "...",            // одна фраза — суть поста (на русском)
  "keywords": ["..."]          // 3-5 ключевых слова
}
Шум: реклама, поздравления, опросы без содержания, репосты без комментария.
Сигнал: новости, аналитика, данные, события, прогнозы."""


def classify_post(text: str) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text[:2000]},
    ]
    response = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=256,
        messages=messages,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        return {"signal": False, "score": 0.0, "category": "other", "summary": "", "keywords": []}


def build_processed_max_ids() -> dict[str, int]:
    """Возвращает {channel_id: max_message_id} по всем существующим processed-файлам."""
    max_ids: dict[str, int] = {}
    for f in PROCESSED_DIR.glob("*-processed.json"):
        try:
            with open(f, encoding="utf-8") as fp:
                posts = json.load(fp)
            for post in posts:
                ch_id = post.get("channel_id", "")
                msg_id = post.get("id", 0)
                if ch_id and msg_id > max_ids.get(ch_id, 0):
                    max_ids[ch_id] = msg_id
        except Exception:
            continue
    return max_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(),
                        help="Дата в формате YYYY-MM-DD (по умолчанию — сегодня)")
    parser.add_argument("--mode", choices=["date", "undigested"], default="date",
                        help="date: только за указанную дату; undigested: посты не из предыдущих дайджестов")
    return parser.parse_args()


def process_file(raw_file: Path, date_str: str, mode: str, processed_max_ids: dict) -> tuple[str, int, int]:
    with open(raw_file, encoding="utf-8") as f:
        posts = json.load(f)

    results = []
    for post in posts:
        if not post.get("text"):
            continue

        if mode == "date":
            post_date = post.get("date", "")[:10]  # "YYYY-MM-DD"
            if post_date and post_date != date_str:
                continue
        else:  # undigested
            ch_id = post.get("channel_id", "")
            msg_id = post.get("id", 0)
            if msg_id <= processed_max_ids.get(ch_id, 0):
                continue

        classification = classify_post(post["text"])
        results.append({**post, "classification": classification})

    # Имя выходного файла: для undigested используем дату raw-файла из его имени
    raw_date = raw_file.name.split("-")[0] + "-" + raw_file.name.split("-")[1] + "-" + raw_file.name.split("-")[2]
    channel_id = raw_file.stem.replace(f"{raw_date}-", "").replace("-raw", "")
    out_file = PROCESSED_DIR / f"{date_str}-{channel_id}-processed.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    signals = sum(1 for r in results if r["classification"].get("signal"))
    print(f"  {channel_id}: {signals}/{len(results)} signals -> {out_file.name}")
    return channel_id, signals, len(results)


def update_signal_ratios(channel_stats: dict[str, tuple[int, int]]) -> None:
    """Пересчитывает signal_ratio по каждому обработанному каналу и сохраняет в channels.json.

    channel_stats: {channel_id: (signals, total)} — накоплено по всем processed-файлам
    канала за весь прогон (может объединять несколько дат одного канала).
    """
    if not channel_stats or not CHANNELS_FILE.exists():
        return

    with open(CHANNELS_FILE, encoding="utf-8") as f:
        config = json.load(f)

    changed = False
    for channel in config.get("channels", []):
        ch_id = channel.get("id")
        if ch_id in channel_stats:
            signals, total = channel_stats[ch_id]
            channel["signal_ratio"] = round(signals / total, 2) if total > 0 else None
            changed = True

    if changed:
        config["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"\nsignal_ratio обновлён для {len(channel_stats)} канал(ов) в {CHANNELS_FILE.name}")


def main() -> None:
    args = parse_args()
    date_str = args.date.isoformat()

    if args.mode == "undigested":
        processed_max_ids = build_processed_max_ids()
        raw_files = list(RAW_DIR.glob("*-raw.json"))
        print(f"Mode: undigested — scanning {len(raw_files)} raw files, "
              f"tracking {len(processed_max_ids)} channels...")
    else:
        processed_max_ids = {}
        raw_files = list(RAW_DIR.glob(f"{date_str}-*-raw.json"))
        print(f"Mode: date={date_str} — processing {len(raw_files)} raw files...")

    channel_stats: dict[str, tuple[int, int]] = {}
    for f in raw_files:
        channel_id, signals, total = process_file(f, date_str, args.mode, processed_max_ids)
        prev_signals, prev_total = channel_stats.get(channel_id, (0, 0))
        channel_stats[channel_id] = (prev_signals + signals, prev_total + total)

    update_signal_ratios(channel_stats)


if __name__ == "__main__":
    main()
