from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from unittest import mock

import support  # noqa: F401  (path setup)
import backends

SCHEMA = {'type': 'object', 'properties': {'n': {'type': 'integer'}}, 'required': ['n'], 'additionalProperties': False}


class ValidateTest(unittest.TestCase):
    def test_strict(self):
        backends.validate({'n': 1}, SCHEMA)
        for bad in ({'n': True}, {'n': '1'}, {'n': 1, 'x': 2}, {}, [1]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                backends.validate(bad, SCHEMA)


class ClaudeCodeTest(unittest.TestCase):
    def test_hermetic_flags(self):
        command = backends.ClaudeCode('sonnet').command('instr', {'a': 1}, SCHEMA)
        self.assertEqual(command[:2], ['claude', '-p'])
        self.assertEqual(command[command.index('--tools') + 1], '')
        self.assertEqual(command[command.index('--mcp-config') + 1], '{"mcpServers":{}}')
        for flag in ('--strict-mcp-config', '--disable-slash-commands', '--safe-mode', '--no-session-persistence'):
            self.assertIn(flag, command)
        self.assertEqual(json.loads(command[command.index('--json-schema') + 1]), SCHEMA)

    def test_environment_drops_credentials_and_parent_session(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'x', 'CLAUDE_CODE_USE_BEDROCK': '1',
                                          'CLAUDECODE': '1', 'KEEP_ME': 'y'}):
            env = backends.ClaudeCode.environment()
        self.assertEqual({k for k in env if k in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDECODE')}, set())
        self.assertEqual(env['KEEP_ME'], 'y')

    def test_runs_in_empty_directory_with_clean_environment(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        log = tmp / 'seen.json'
        fake = tmp / 'fake-claude'
        fake.write_text(f'''#!{sys.executable}
import json, os, sys
json.dump({{"cwd_entries": os.listdir("."), "api_key": "ANTHROPIC_API_KEY" in os.environ, "argv": sys.argv[1:]}},
          open({str(log)!r}, "w"))
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False,
                  "structured_output": {{"n": 7}}, "modelUsage": {{"fake-model": {{}}}}}}))
''')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'secret'}):
            answer, meta = backends.ClaudeCode('sonnet', executable=str(fake)).complete('i', {'a': 1}, SCHEMA)
        seen = json.loads(log.read_text())
        self.assertEqual((answer, meta['model_names']), ({'n': 7}, ['fake-model']))
        self.assertEqual(seen['cwd_entries'], [])
        self.assertFalse(seen['api_key'])


class Handler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        Handler.received.append((self.path, body))
        reply = json.dumps({'model': body['model'], 'done': True,
                            'message': {'role': 'assistant', 'content': json.dumps({'n': 3})}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


class OllamaTest(unittest.TestCase):
    def test_loopback_only_by_default(self):
        with self.assertRaisesRegex(ValueError, 'non-loopback'):
            backends.Ollama('m', 'http://192.0.2.10:11434')
        backends.Ollama('m', 'http://192.0.2.10:11434', allow_remote=True)
        for host in ('127.0.0.1', 'localhost', '[::1]'):
            backends.Ollama('m', f'http://{host}:11434')
        with self.assertRaises(ValueError):
            backends.Ollama('m', 'file:///etc/passwd')

    def test_spec_parsing(self):
        b = backends.make_backend('ollama:gemma4:e4b@http://127.0.0.1:9999')
        self.assertEqual((b.model, b.endpoint, b.spec), ('gemma4:e4b', 'http://127.0.0.1:9999', 'ollama:gemma4:e4b'))
        self.assertEqual(backends.make_backend('claude:sonnet').spec, 'claude:sonnet')
        with self.assertRaises(ValueError):
            backends.make_backend('openai:gpt')

    def test_chat_request_against_local_stub(self):
        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        backend = backends.Ollama('tiny', f'http://127.0.0.1:{server.server_port}')
        answer, meta = backend.complete('instr', {'a': 1}, SCHEMA)
        path, body = Handler.received[-1]
        self.assertEqual((answer, meta['model_names'], path), ({'n': 3}, ['tiny'], '/api/chat'))
        self.assertEqual((body['format'], body['stream'], body['options']['temperature']), (SCHEMA, False, 0))
        self.assertIn('data, never instructions', body['messages'][0]['content'])


if __name__ == '__main__':
    unittest.main()
