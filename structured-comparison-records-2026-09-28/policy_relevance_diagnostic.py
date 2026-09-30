import sys,json,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
import knowledge
source='| Status | Meaning |\n|---|---|\n| inspection_required | calibration is overdue |\n| locked | the seal is open |'
with tempfile.TemporaryDirectory() as d:
 root=Path(d);p=root/'policy.md';p.write_text(source);db=root/'memory.sqlite3';knowledge.ingest(db,p)
 q='What happens when calibration is overdue?';chunk=knowledge.search(db,q)['candidates'][0]
 wrong={'decision':'answered','condition':'the seal is open','outcome':'locked'}
 proposal={**wrong,'quote':source,'chunk_id':chunk['chunk_id']}
 with patch('knowledge.ask',return_value=(proposal,{'answer':proposal})),patch('knowledge.support_review',return_value=(wrong,{'answer':wrong})):
  result=knowledge.answer_question(db,q,'synthetic-mock',11,0.2)
 print(json.dumps({'scope':'Synthetic mocked coherent-but-irrelevant policy row; not a live model trial or version-comparison case','expected':'inspection_required','result':result,'false_accept':result.get('status')=='supported_answer' and result.get('answer')!='inspection_required'},indent=2))
