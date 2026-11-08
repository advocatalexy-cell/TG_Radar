"""Offline checks; no API calls and no production Git operations."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('cloud', Path(__file__).with_name('run-cloud-analysis.py'))
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)
ROOT = Path(__file__).resolve().parents[1]


class CloudTests(unittest.TestCase):
    def test_actual_plan_and_new_analyst(self):
        command = (ROOT / cloud.COMMAND).read_text(encoding='utf-8')
        plan = cloud.plan_for('2026-11-08', command)
        self.assertEqual(len(plan['analysts']), 3)
        extended = command.replace('## Шаг 2:', '**Задание для analyst-legal-extra:**\n> Сохрани data/analysis/ДАТА-extra.md\n\n## Шаг 2:', 1)
        with patch.object(Path, 'is_file', return_value=True):
            self.assertEqual(len(cloud.plan_for('2026-11-08', extended)['analysts']), 4)

    def test_missing_task_output_fails(self):
        with self.assertRaises(ValueError):
            cloud.plan_for('2026-11-08', '## Шаг 1:\n**Задание для analyst-legal:**\n> no output\n## Шаг 2:')

    def test_validation_and_unexpected_edit(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                cloud.RUN.mkdir()
                plan = {'date': '2026-11-08', 'base': 'base',
                        'analysts': [{'name': 'analyst-legal', 'path': 'data/analysis/2026-11-08-legal.md'}],
                        'digest': 'digests/2026-11-08-digest.md'}
                (cloud.RUN / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
                for path in cloud.paths_for(plan):
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text('[Post](https://t.me/channel/1)', encoding='utf-8')
                def fake_git(*args, **kwargs):
                    return SimpleNamespace(stdout='base' if args[0] == 'rev-parse' else '', returncode=0)
                with patch.object(cloud, 'git', side_effect=fake_git):
                    cloud.validate()
                saved = json.loads((cloud.RUN / 'validated.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['counts']['analyst-legal'], 1)
                self.assertTrue((cloud.RUN / 'result' / plan['digest']).is_file())
                with patch.object(cloud, 'git', side_effect=[SimpleNamespace(stdout='base'), SimpleNamespace(stdout='scripts/publish-post.py\n'), SimpleNamespace(stdout='')]):
                    with self.assertRaisesRegex(RuntimeError, 'Unexpected changes'):
                        cloud.validate()
                Path(plan['digest']).write_text('', encoding='utf-8')
                with patch.object(cloud, 'git', side_effect=fake_git):
                    with self.assertRaisesRegex(RuntimeError, 'Missing, empty'):
                        cloud.validate()
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
