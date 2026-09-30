"""Reported recovery host strings + synthetic source fixtures; no fabricated raw response."""
import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import knowledge
import version_comparison as v
Q='What is the minimum Python version required?'
QUOTE='Requires Python 3.10 or newer. The scripted mode needs no services, packages, weights, or network connections.'
class VersionTests(unittest.TestCase):
 def test_reported_seed11_pair(self):
  r=v.compare(Q,QUOTE,'Python 3.10 or newer','Python 3.10')
  self.assertEqual(r['verdict'],'equivalent');self.assertEqual(r['source']['version'],[3,10])
  self.assertEqual(r['support']['interpretation'],'minimum_value_from_question_and_source')
 def test_positive_grammar(self):
  for source in ['Requires Python 3.10 or newer.','Python >=3.10 is required.','Minimum Python version is 3.10.']:
   with self.subTest(source=source):self.assertEqual(v.compare(Q,source,'Python 3.10 or newer','python >=3.10')['verdict'],'equivalent')
 def test_near_misses(self):
  for answer in ['Python >3.10','Python 3.10 only','Python exactly 3.10','Python 3.1','Python 3.9','Python 3.11','Node.js 3.10','Python 3.10.0','Python 3.10rc1','Python <=3.10','Python 3.10 or older']:
   with self.subTest(answer=answer):self.assertNotEqual(v.compare(Q,QUOTE,answer,'Python 3.10 or newer')['verdict'],'equivalent')
 def test_agreement_is_not_enough(self):
  for answer in ['Python 3.1','Python 3.11','Node.js 3.10','Python exactly 3.10']:
   with self.subTest(answer=answer):self.assertNotEqual(v.compare(Q,QUOTE,answer,answer)['verdict'],'equivalent')
 def test_unknown_source_question_and_contradictions(self):
  sources=['Requires Python >3.10.','Python 3.10 is recommended.','Python 3.10 is not required.',
   'Requires Python 3.10 or newer, unless compatibility mode is enabled.',
   'Requires Python 3.10 or newer. Requires Python 3.11 or newer.',
   'Requires Python 3.10 or newer. Node.js 3.12 is also required.',
   'Requires Python 3.10rc1 or newer.','Python 3.10 is required.',
   'Requires Python 3.10 or newer. This requirement is optional.',
   'Requires Python 3.10 or newer. This requirement does not apply on Linux.']
  for source in sources:
   with self.subTest(source=source):self.assertNotEqual(v.compare(Q,source,'Python 3.10','Python 3.10')['verdict'],'equivalent')
  self.assertNotEqual(v.compare('What exact Python version is required?',QUOTE,'Python 3.10','Python 3.10')['verdict'],'equivalent')
  self.assertNotEqual(v.compare('Which minimum Python version should I use?',QUOTE,'Python 3.10','Python 3.10')['verdict'],'equivalent')
 def run_case(self,solver,support,source=QUOTE,question=Q,mutate=None):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);path=root/'source.md';path.write_text(source);db=root/'memory.sqlite3';knowledge.ingest(db,path)
   chunk=knowledge.search(db,question)['candidates'][0]
   proposal={'outcome':'answered','answer':solver,'chunk_id':chunk['chunk_id'],'quote':source}
   def review(*a,**k):
    if mutate:mutate(path)
    return {'outcome':'answered','answer':support},{'answer':{'outcome':'answered','answer':support}}
   with patch('knowledge.ask',return_value=(proposal,{'answer':proposal})),patch('knowledge.support_review',side_effect=review):r=knowledge.answer_question(db,question,'test',11,0.2)
   with knowledge.hive.connect(db) as c:events=[(e['kind'],json.loads(e['payload'])) for e in c.execute('SELECT * FROM events ORDER BY sequence')]
   return r,events
 def test_end_to_end_reported_pair_and_audit(self):
  r,events=self.run_case('Python 3.10 or newer','Python 3.10')
  self.assertEqual(r['status'],'supported_answer');self.assertTrue(r['checks']['answers_agree'])
  comparison=next(p for k,p in events if k=='answer_comparison')
  self.assertEqual(comparison['verdict'],'equivalent');self.assertTrue(comparison['source_id'])
  self.assertTrue(comparison['solver_event_id']);self.assertTrue(comparison['support_event_id'])
 def test_equivalence_never_bypasses_anchor(self):
  r,_=self.run_case('Python >=3.10','Python 3.10')
  self.assertEqual(r['status'],'needs_review');self.assertFalse(r['checks']['solver_answer_anchored'])
 def test_equivalence_never_bypasses_freshness(self):
  r,_=self.run_case('Python 3.10 or newer','Python 3.10',mutate=lambda p:p.write_text('Changed'))
  self.assertEqual(r['status'],'stale_source')
 def test_identical_unknown_constraint_is_withheld(self):
  r,_=self.run_case('Python 3.10','Python 3.10',source='Python 3.10 is recommended.')
  self.assertEqual(r['status'],'needs_review');self.assertNotIn('answer',r)
 def test_unknown_minimum_question_is_review(self):
  r,_=self.run_case('Python 3.10','Python 3.10',question='Which minimum Python version should I use?')
  self.assertEqual(r['status'],'needs_review')

class AdditionalGateTests(unittest.TestCase):
 run_case = VersionTests.run_case
 def test_absence_of_minimum_constraint_stays_review(self):
  absent={'outcome':'not_found_in_source','answer':''}
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source.md';p.write_text('Python has no stated minimum version in this source.');db=Path(d)/'db.sqlite3';knowledge.ingest(db,p)
   with patch('knowledge.ask',return_value=({**absent,'chunk_id':'','quote':''},{})),patch('knowledge.support_review',return_value=(absent,{})):
    r=knowledge.answer_question(db,Q,'test',11,0.2)
   self.assertEqual(r['status'],'needs_review');self.assertNotIn('finding_id',r)
 def test_unknown_question_does_not_call_models(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source.md';p.write_text(QUOTE);db=Path(d)/'db.sqlite3';knowledge.ingest(db,p)
   with patch('knowledge.ask') as ask:
    r=knowledge.answer_question(db,'Which minimum Python version should I use?','test')
   self.assertEqual(r['status'],'needs_review');ask.assert_not_called()
 def test_answer_supported_by_quote_still_needs_valid_citation(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source.md';p.write_text(QUOTE);db=Path(d)/'db.sqlite3';knowledge.ingest(db,p)
   response={'outcome':'answered','answer':'Python 3.10','chunk_id':'invented','quote':QUOTE}
   with patch('knowledge.ask',return_value=(response,{})),patch('knowledge.support_review') as support:
    r=knowledge.answer_question(db,Q,'test')
   self.assertEqual(r['status'],'unsupported_output');support.assert_not_called()
 def test_supported_grammar_preserves_exact_span_offsets(self):
  r=v.compare(Q,QUOTE,'Python 3.10','Python 3.10 or newer')
  for span in r['source']['spans'].values():self.assertEqual(QUOTE[span['start']:span['end']],span['text'])

