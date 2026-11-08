"""Offline checks for subscription-only execution and data completeness."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('subscription', ROOT / 'scripts/run-subscription-analysis.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SubscriptionTests(unittest.TestCase):
    def test_folder_selection_does_not_filter_signals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'sources').mkdir()
            (root / 'data/processed').mkdir(parents=True)
            config = {'channels': [{'id': 'law', 'name': 'Law', 'active': True, 'source_folder': 'Lawyer'},
                                   {'id': 'ai', 'active': True, 'source_folder': 'Ai'},
                                   {'id': 'off', 'active': False, 'source_folder': 'Lawyer'}]}
            (root / 'sources/channels.json').write_text(json.dumps(config), encoding='utf-8')
            for name in ('law', 'ai', 'off'):
                posts = [{'id': 1, 'channel_id': name, 'text': 'post', 'classification': {'signal': False, 'score': 0}}]
                (root / f'data/processed/2026-11-07-{name}-processed.json').write_text(json.dumps(posts), encoding='utf-8')
            groups, urls = module.group_payload(root, '2026-11-07', 'source_folder == "Lawyer"')
            self.assertEqual([group['id'] for group in groups], ['law'])
            self.assertEqual(urls, {'https://t.me/law/1'})

    def test_unknown_links_and_wrong_heading_rejected(self):
        with self.assertRaises(ValueError):
            module.check_markdown('## Section\n[x](https://t.me/invented/1)', set(), '## ')
        with self.assertRaises(ValueError):
            module.check_markdown('Failed to read data', set(), '## ')

    def test_api_credentials_removed_and_tools_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'output.md'
            output.write_text('## Result', encoding='utf-8')
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-secret', 'CODEX_API_KEY': 'test-secret', 'GH_TOKEN': 'test-secret'}), \
                 patch.object(module.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='')) as run, \
                 patch.object(module, 'log'):
                module.invoke('test', 'prompt', Path(temporary), output)
            args, kwargs = run.call_args
            self.assertIn('forced_login_method="chatgpt"', args[0])
            self.assertIn('shell_tool', args[0])
            self.assertIn('unified_exec', args[0])
            self.assertTrue(all(key not in kwargs['env'] for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'GH_TOKEN')))

    def test_test_result_never_delivered(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = Path(temporary) / 'result.json'
            result.write_text(json.dumps({'date': '2026-11-07', 'dry_run': True}), encoding='utf-8')
            with patch.object(module, 'RESULT', result), patch.object(module, 'ZoneInfo', return_value=timezone.utc), patch.object(module, 'git') as git:
                with self.assertRaisesRegex(RuntimeError, 'test or historical'):
                    module.save()
                git.assert_not_called()

    def test_delivery_to_local_bare_master(self):
        """Exercise commit, rebase, push and remote verification without GitHub."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bare, delivery, home = root / 'remote.git', root / 'delivery', root / 'private'
            subprocess.run(['git', 'init', '--bare', '--initial-branch=master', str(bare)], check=True, capture_output=True)
            subprocess.run(['git', 'clone', str(bare), str(delivery)], check=True, capture_output=True)
            module.git(delivery, 'config', 'user.name', 'Test')
            module.git(delivery, 'config', 'user.email', 'test@localhost')
            (delivery / 'seed.txt').write_text('seed', encoding='utf-8')
            module.git(delivery, 'add', 'seed.txt')
            module.git(delivery, 'commit', '-m', 'seed')
            module.git(delivery, 'push', 'origin', 'HEAD:master')
            commit = module.git(delivery, 'rev-parse', 'HEAD').stdout.strip()
            day = datetime.now(timezone.utc).date().isoformat()
            workspace = home / 'runs' / 'test' / 'context'
            plan = {'analysts': [{'path': f'data/analysis/{day}-legal.md'}], 'digest': f'digests/{day}-digest.md'}
            paths = [plan['analysts'][0]['path'], plan['digest']]
            for relative, heading in zip(paths, ['## Section', f'# Дайджест {day}']):
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(heading + '\n[x](https://t.me/law/1)', encoding='utf-8')
            result = home / 'result.json'
            result.write_text(json.dumps({'date': day, 'dry_run': False, 'status': 'ready', 'auth': 'chatgpt',
                                          'workspace': str(workspace), 'paths': paths, 'source_commit': commit,
                                          'model': module.MODEL, 'counts': {'analyst-legal': 1}}), encoding='utf-8')
            with patch.object(module, 'HOME', home), patch.object(module, 'RESULT', result), \
                 patch.object(module, 'DELIVERY', delivery), patch.object(module, 'ZoneInfo', return_value=timezone.utc), \
                 patch.object(module, 'load_plan', return_value=plan), \
                 patch.object(module, 'source_urls', return_value={'https://t.me/law/1'}), patch.object(module, 'log'):
                module.save()
            self.assertEqual(module.git(delivery, 'show', f'origin/master:{plan["digest"]}').returncode, 0)
            self.assertEqual(module.git(delivery, 'log', '-1', '--format=%s').stdout.strip(), f'Analysis and digest for {day}')


if __name__ == '__main__':
    unittest.main()
