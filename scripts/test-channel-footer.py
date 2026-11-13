"""Check complete empty-source coverage and separation of absent data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('subscription', Path(__file__).with_name('run-subscription-analysis.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FooterTests(unittest.TestCase):
    def test_empty_sources_grouped_by_folder_and_missing_data_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sources').mkdir()
            (root / 'data/processed').mkdir(parents=True)
            channels = [dict(id='posts', name='Active source', active=True, source_folder='Ai'),
                        dict(id='empty', name='Empty source', active=True, source_folder='Ai'),
                        dict(id='missing', name='Missing [source]', active=True, source_folder='Lawyer'),
                        dict(id='off', name='Disabled source', active=False, source_folder='Ai')]
            (root / 'sources/channels.json').write_text(json.dumps({'channels': channels}))
            (root / 'data/processed/2026-11-13-posts-processed.json').write_text('[{"id":1}]')
            (root / 'data/processed/2026-11-13-empty-processed.json').write_text('[]')
            text = module.empty_channels_footer(root, '2026-11-13')
            self.assertIn('Активных каналов: 3 | С публикациями: 1 | Без публикаций в данных: 1 | Нет данных: 1', text)
            self.assertIn('### Папка «Ai» (1)', text)
            self.assertIn('### Папка «Lawyer» (1)', text)
            self.assertIn('Empty source', text)
            self.assertIn('Missing [source]', text)
            self.assertIn('нет данных за дату', text)
            self.assertNotIn('Disabled source', text)
            self.assertNotIn('Active source', text)
            self.assertEqual(text.count('https://t.me/'), 2)

    def test_all_channels_have_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sources').mkdir()
            (root / 'data/processed').mkdir(parents=True)
            (root / 'sources/channels.json').write_text(json.dumps({'channels': [dict(id='ai', active=True)]}))
            (root / 'data/processed/2026-11-13-ai-processed.json').write_text('[{"id":1}]')
            text = module.empty_channels_footer(root, '2026-11-13')
            self.assertIn('У всех активных каналов есть публикации', text)
            self.assertNotIn('### Папка', text)


if __name__ == '__main__':
    unittest.main()
