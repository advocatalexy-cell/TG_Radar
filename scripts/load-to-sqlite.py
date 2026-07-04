import json
import sqlite3
import glob
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'radar.db')
PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')

def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id          INTEGER,
            channel_id  TEXT,
            date        TEXT,
            text        TEXT,
            views       INTEGER,
            forwards    INTEGER,
            has_media   INTEGER,
            signal      INTEGER,
            score       REAL,
            category    TEXT,
            summary     TEXT,
            date_label  TEXT,
            PRIMARY KEY (id, channel_id)
        );

        CREATE TABLE IF NOT EXISTS keywords (
            post_id     INTEGER,
            channel_id  TEXT,
            keyword     TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_posts_date    ON posts(date_label);
        CREATE INDEX IF NOT EXISTS idx_posts_signal  ON posts(signal);
        CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel_id);
        CREATE INDEX IF NOT EXISTS idx_kw_keyword    ON keywords(keyword);
    """)

def load_files(conn):
    pattern = os.path.join(PROCESSED_DIR, '*-processed.json')
    files = glob.glob(pattern)
    inserted = 0
    skipped = 0

    for fpath in files:
        fname = os.path.basename(fpath)
        # extract date label: first 10 chars (YYYY-MM-DD)
        date_label = fname[:10]

        with open(fpath, encoding='utf-8') as f:
            try:
                posts = json.load(f)
            except json.JSONDecodeError:
                continue

        if not isinstance(posts, list):
            continue

        for p in posts:
            clf = p.get('classification') or {}
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO posts
                       (id, channel_id, date, text, views, forwards, has_media,
                        signal, score, category, summary, date_label)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        p.get('id'),
                        p.get('channel_id'),
                        p.get('date'),
                        p.get('text'),
                        p.get('views'),
                        p.get('forwards'),
                        int(bool(p.get('has_media'))),
                        int(bool(clf.get('signal'))),
                        clf.get('score'),
                        clf.get('category'),
                        clf.get('summary'),
                        date_label,
                    )
                )
                inserted += conn.execute("SELECT changes()").fetchone()[0]

                for kw in (clf.get('keywords') or []):
                    conn.execute(
                        "INSERT INTO keywords (post_id, channel_id, keyword) VALUES (?,?,?)",
                        (p.get('id'), p.get('channel_id'), kw)
                    )
            except Exception as e:
                skipped += 1

    conn.commit()
    return inserted, skipped

def print_stats(conn):
    print("\n=== Radar SQLite — статистика ===\n")

    total = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    signals = conn.execute("SELECT COUNT(*) FROM posts WHERE signal=1").fetchone()[0]
    dates = conn.execute("SELECT COUNT(DISTINCT date_label) FROM posts").fetchone()[0]
    channels = conn.execute("SELECT COUNT(DISTINCT channel_id) FROM posts").fetchone()[0]
    print(f"Постов всего:   {total}")
    print(f"Сигналов:       {signals}  ({signals*100//total if total else 0}%)")
    print(f"Дней данных:    {dates}")
    print(f"Каналов:        {channels}")

    print("\n--- Топ-10 каналов по числу постов ---")
    rows = conn.execute("""
        SELECT channel_id, COUNT(*) as cnt,
               ROUND(AVG(score),2) as avg_score,
               SUM(signal) as signals
        FROM posts
        GROUP BY channel_id
        ORDER BY cnt DESC
        LIMIT 10
    """).fetchall()
    print(f"{'Канал':<35} {'Постов':>7} {'Сигн.':>6} {'Ср.скор':>8}")
    print("-"*60)
    for r in rows:
        print(f"{r[0]:<35} {r[1]:>7} {r[3]:>6} {r[2]:>8}")

    print("\n--- Сигналы по датам ---")
    rows = conn.execute("""
        SELECT date_label, COUNT(*) as total, SUM(signal) as sigs
        FROM posts
        GROUP BY date_label
        ORDER BY date_label
    """).fetchall()
    print(f"{'Дата':<12} {'Постов':>7} {'Сигналов':>9}")
    print("-"*32)
    for r in rows:
        print(f"{r[0]:<12} {r[1]:>7} {r[2]:>9}")

    print("\n--- Топ-15 ключевых слов ---")
    rows = conn.execute("""
        SELECT keyword, COUNT(*) as cnt
        FROM keywords
        GROUP BY keyword
        ORDER BY cnt DESC
        LIMIT 15
    """).fetchall()
    for r in rows:
        print(f"  {r[0]:<30} {r[1]}")

    print("\n--- Лучшие сигналы (score >= 0.7) ---")
    rows = conn.execute("""
        SELECT date_label, channel_id, score, summary
        FROM posts
        WHERE signal=1 AND score >= 0.7
        ORDER BY score DESC, date_label DESC
        LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"  [{r[0]}] {r[1]} ({r[2]}) — {r[3][:80]}")

    print(f"\nБаза сохранена: {os.path.abspath(DB_PATH)}\n")

if __name__ == '__main__':
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    inserted, skipped = load_files(conn)
    print(f"Загружено: {inserted} постов, пропущено: {skipped}")
    print_stats(conn)
    conn.close()
