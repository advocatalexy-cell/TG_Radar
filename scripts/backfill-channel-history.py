"""
Разовая классификация истории для только что добавленных каналов.

Нужен для случая, когда sync-tg-folders.py/import-tg-folders.py добавляет в
sources/channels.json новый канал: fetch-posts.py уже собрал по нему до 50
последних постов в ОДИН raw-файл, дата которого — день сбора, а не даты самих
постов. Ни `filter-signals.py --mode date` (берёт только посты с датой ==
дате запуска), ни `--mode undigested` (при большом множестве raw-файлов у
старых каналов перезаписывает data/processed/<сегодня>-<канал>-processed.json
последним просканированным raw-файлом, а не корректно по дате поста) для
этого не годятся.

Этот скрипт: для каждого указанного канала читает ВСЕ его raw-файлы,
классифицирует каждый пост через OpenAI и раскладывает результат по
data/processed/<дата поста>-<канал>-processed.json — с домержем в
уже существующий файл за эту дату, если он есть (дедуп по id поста).

Требует: pip install openai python-dotenv
Использование:
  python scripts/backfill-channel-history.py --channels id1,id2,id3
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

openai_client = OpenAI(timeout=30.0, max_retries=2)
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
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=256,
            messages=messages,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"  classify_post: запрос к LLM не удался ({e}) — пост помечен как non-signal",
              file=sys.stderr)
        return {"signal": False, "score": 0.0, "category": "other", "summary": "", "keywords": []}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", required=True,
                         help="channel_id через запятую, например: chan1,chan2")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    channel_ids = [c.strip() for c in args.channels.split(",") if c.strip()]

    for channel_id in channel_ids:
        raw_files = sorted(RAW_DIR.glob(f"*-{channel_id}-raw.json"))
        if not raw_files:
            print(f"[{channel_id}] raw-файлов не найдено — пропущен.")
            continue

        by_date: dict[str, list[dict]] = defaultdict(list)
        total_posts = 0
        for raw_file in raw_files:
            with open(raw_file, encoding="utf-8") as f:
                posts = json.load(f)
            for post in posts:
                if not post.get("text"):
                    continue
                post_date = post.get("date", "")[:10]
                if not post_date:
                    continue
                classification = classify_post(post["text"])
                by_date[post_date].append({**post, "classification": classification})
                total_posts += 1

        for post_date, posts in by_date.items():
            out_file = PROCESSED_DIR / f"{post_date}-{channel_id}-processed.json"
            existing = []
            if out_file.exists():
                with open(out_file, encoding="utf-8") as f:
                    existing = json.load(f)
            by_id = {p["id"]: p for p in existing}
            for p in posts:
                by_id[p["id"]] = p
            merged = sorted(by_id.values(), key=lambda p: p["id"])
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)

        print(f"[{channel_id}] {total_posts} постов классифицировано, "
              f"разложено по {len(by_date)} датам.")


if __name__ == "__main__":
    main()
