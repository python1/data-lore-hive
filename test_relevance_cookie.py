import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import hive,policy_binding,relevance_cookie as candidate
SOURCE='If calibration is overdue, the resulting status is inspection_required.'
class CandidateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.db=Path(self.tmp.name)/'db';hive.initialize(self.db)
  self.rule=policy_binding.rules(SOURCE)[0];self.identity={'tag':'test','digest':'a'*64,'family':'synthetic','runtime':'test'}
 def run_case(self,outputs):
  with patch('relevance_cookie.identity',return_value=self.identity),patch('relevance_cookie.ask',side_effect=[(v,{}) for v in outputs]) as calls:
   result=candidate.review(self.db,'run','What happens when calibration has expired?',SOURCE,'test',11,0)
  return result,calls
 def test_clean_abstention_needs_only_one_field_and_call(self):
  for decision in ['abstain','ambiguous']:
   r,c=self.run_case([{'decision':decision}]);self.assertFalse(r['accepted']);self.assertEqual(c.call_count,1)
 def test_bound_fields_come_from_source_not_model_transcription(self):
  r,c=self.run_case([{'decision':'bound'},{'rule_id':self.rule['id']}])
  self.assertTrue(r['accepted']);self.assertEqual(r['rule'],self.rule);self.assertEqual(r['qualification'],self.rule['condition'])
  self.assertNotEqual(r['decision_event_id'],r['event_id']);self.assertEqual(c.call_count,2)
  self.assertEqual(c.call_args_list[0].args[2],c.call_args_list[1].args[2])
  self.assertEqual(set(c.call_args_list[1].args[2]),{'question','source_context','rules'})
 def test_second_stage_can_abstain(self):
  r,c=self.run_case([{'decision':'bound'},{'rule_id':''}]);self.assertFalse(r['accepted'])
 def test_bad_fields_never_normalized(self):
  for outputs in [[{'decision':'abstain','outcome':'N/A'}],[{'decision':'maybe'}],[{'decision':'bound'},{'rule_id':'invented'}],[{'decision':'bound'},{'rule_id':123}]]:
   with self.subTest(outputs=outputs):
    with self.assertRaises(ValueError):self.run_case(outputs)
 def test_identity_change_fails_closed(self):
  with patch('relevance_cookie.identity',side_effect=[self.identity,{**self.identity,'digest':'b'*64}]),patch('relevance_cookie.ask',return_value=({'decision':'abstain'},{})):
   with self.assertRaises(ValueError):candidate.review(self.db,'run','question',SOURCE,'test',11,0)
if __name__=='__main__':unittest.main()
