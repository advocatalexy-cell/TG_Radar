"""Offline checks of Moscow day boundaries in collection and processing."""
import ast
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def load_function(script, name, env):
    tree = ast.parse((ROOT / 'scripts' / script).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), script, 'exec'), env)
    return env[name]


class CalendarTests(unittest.TestCase):
    def test_fetch_window_includes_early_moscow_hours(self):
        class Message(SimpleNamespace):
            pass

        class Client:
            async def iter_messages(self, url, **kwargs):
                self.offset = kwargs['offset_date']
                for mid, stamp in [(4, '2026-11-12T21:00:00+00:00'),
                                   (3, '2026-11-12T20:59:59+00:00'),
                                   (2, '2026-11-11T21:00:00+00:00'),
                                   (1, '2026-11-11T20:59:59+00:00')]:
                    moment = datetime.fromisoformat(stamp)
                    if moment < self.offset:
                        yield Message(id=mid, date=moment, text='post')

        env = dict(datetime=datetime, date=date, timedelta=timedelta, timezone=timezone,
                   ZoneInfo=ZoneInfo, TelegramClient=object, Message=Message,
                   serialize_message=lambda msg, cid: {'id': msg.id})
        fetch = load_function('fetch-posts.py', 'fetch_channel_by_date', env)
        client = Client()
        rows = asyncio.run(fetch(client, {'id': 'test', 'url': 'test'}, date(2026, 11, 12)))
        self.assertEqual([row['id'] for row in rows], [3, 2])
        self.assertEqual(client.offset.astimezone(timezone.utc).isoformat(), '2026-11-12T21:00:00+00:00')

    def test_filter_uses_same_moscow_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / '2026-11-12-test-raw.json'
            stamps = ['2026-11-11T20:59:59+00:00', '2026-11-11T21:00:00+00:00',
                      '2026-11-12T20:59:59+00:00', '2026-11-12T21:00:00+00:00']
            raw.write_text(json.dumps([dict(id=i, date=s, text='post') for i, s in enumerate(stamps)]))
            written = []
            env = dict(Path=Path, json=json, datetime=datetime, ZoneInfo=ZoneInfo,
                       PROCESSED_DIR=root, classify_post=lambda text: {'signal': False},
                       write_processed=lambda path, rows: written.extend(rows))
            process = load_function('filter-signals.py', 'process_file', env)
            process(raw, '2026-11-12', 'date', {})
            self.assertEqual([row['id'] for row in written], [1, 2])


if __name__ == '__main__':
    unittest.main()
