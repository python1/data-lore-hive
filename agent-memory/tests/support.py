"""Shared fixtures: the invented sample export and a scripted, offline model backend."""
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import pipeline  # noqa: E402

SAMPLE = HERE.parent / 'sample' / 'telegram-export.json'
USER_ID, AGENT_ID = 'user1000001', 'user2000002'
SECRET = 'kiln-glaze-4471'


class Scripted:
    """Answers from a function of (instruction, context); records every context it was sent."""

    def __init__(self, spec, answer):
        self.spec, self.answer, self.sent = spec, answer, []

    def complete(self, instruction, context, schema):
        self.sent.append(context)
        answer = self.answer(instruction, context)
        import backends
        backends.validate(answer, schema)
        return answer, {'model_names': [self.spec]}


class RunCase:
    """Mixin: a fresh run directory over a private copy of the sample export."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='agent-memory-test-'))
        self.export = self.tmp / 'result.json'
        shutil.copy(SAMPLE, self.export)
        self.root = self.tmp / 'run'
        pipeline.init(self.root, self.export, 0, USER_ID, AGENT_ID, 'Juniper', 'Wren')
        self.run = pipeline.Run(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp)
