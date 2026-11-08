"""Offline regression checks for full-post classification and model selection."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_filter(environment):
    client = Mock()
    openai = ModuleType('openai')
    openai.OpenAI = Mock(return_value=client)
    dotenv = ModuleType('dotenv')
    dotenv.load_dotenv = Mock()
    spec = importlib.util.spec_from_file_location('filter_test', Path(__file__).with_name('filter-signals.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'openai': openai, 'dotenv': dotenv}), patch.dict(os.environ, environment, clear=True):
        spec.loader.exec_module(module)
    return module, client


class FilterTests(unittest.TestCase):
    def test_full_post_including_decisive_tail_is_sent(self):
        module, client = load_filter({'OPENAI_MODEL': 'old-model', 'OPENAI_FILTER_MODEL': 'gpt-6-luna'})
        body = {'signal': True, 'score': 0.8, 'category': 'tech', 'summary': 'Tail matters', 'keywords': ['test']}
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason='stop', message=SimpleNamespace(content=json.dumps(body)))])
        post = 'Вводная часть. ' * 250 + 'ВАЖНО: запуск отменен, это опровержение.'
        self.assertGreater(len(post), 2000)
        self.assertEqual(module.classify_post(post), body)
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request['messages'][1]['content'], post)
        self.assertEqual(request['model'], 'gpt-6-luna')
        self.assertEqual(request['reasoning_effort'], 'none')
        self.assertNotIn('max_tokens', request)

    def test_incomplete_json_is_not_accepted_as_success(self):
        module, client = load_filter({})
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason='length', message=SimpleNamespace(content='{"signal": true}'))])
        with patch('sys.stderr'):
            result = module.classify_post('post')
        self.assertFalse(result['signal'])
        self.assertEqual(result['summary'], '')

    def test_old_model_override_keeps_compatible_parameters(self):
        module, client = load_filter({'OPENAI_MODEL': 'gpt-4o-mini'})
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason='stop', message=SimpleNamespace(content='{}'))])
        module.classify_post('post')
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request['model'], 'gpt-4o-mini')
        self.assertIn('max_tokens', request)
        self.assertNotIn('reasoning_effort', request)


if __name__ == '__main__':
    unittest.main()
