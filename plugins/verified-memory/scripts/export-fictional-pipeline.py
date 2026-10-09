"""Exercise the real exporter with existing fictional, scripted pipeline fixtures.

No model call, credentials or private inputs. The argument is a NEW output directory.
Approval is test automation only, never a claim of human approval.
"""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parents[1] / 'agent-memory/tests'))
from test_pipeline import PipelineTest
import export_memory
import pipeline

case = PipelineTest()
case.setUp()
try:
    case.full()  # scripted proposal/audit -> exact source quote checks -> review
    pipeline.approve(case.run, 'fictional scripted fixture (not human approval)', all_pending=True)
    export_memory.export(case.run, Path(sys.argv[1]))
    print('Exported 3 fictional pipeline records; scripted audit and approval only.')
finally:
    case.tearDown()
