"""Deterministic relevance traps, before implementation."""
import unittest
import policy_binding as b

SOURCE='| Status | Meaning |\n|---|---|\n| inspection_required | calibration is overdue |\n| locked | the seal is open |'
class BindingTests(unittest.TestCase):
 def test_calibration_seal_trap(self):
  r=b.bind('What happens when calibration is overdue?',SOURCE)
  self.assertEqual(r['state'],'bound');self.assertEqual(r['rule']['outcome'],'inspection_required')
  self.assertFalse(b.agrees(r['rule'],{'condition':'the seal is open','outcome':'locked'}))
 def test_negation_and_unknown(self):
  self.assertEqual(b.bind('What happens when calibration is not overdue?',SOURCE)['state'],'mismatch')
  self.assertEqual(b.bind('What happens when calibration has expired?',SOURCE)['state'],'unclassified')
 def test_conflict_reverse_and_reordering(self):
  self.assertEqual(b.bind('Under what condition is the status locked?',SOURCE)['rule']['condition'],'the seal is open')
  self.assertEqual(b.bind('What happens when calibration is overdue?',SOURCE+'\n| locked | calibration is overdue |')['state'],'conflict')
  reordered='\n'.join(SOURCE.splitlines()[:2]+list(reversed(SOURCE.splitlines()[2:])))
  self.assertEqual(b.bind('What happens when calibration is overdue?',reordered)['rule']['outcome'],'inspection_required')
 def test_prose_and_operators(self):
  for a,c in [('pressure >10','pressure >=10'),('A and B','A or B')]:
   self.assertEqual(b.bind('What happens when '+a+'?',f'If {c}, locked.')['state'],'mismatch')
  self.assertEqual(b.bind('What happens when calibration is overdue?','If calibration is overdue, the resulting status is inspection_required.')['state'],'bound')
 def test_exception_blocks_even_literal(self):
  self.assertEqual(b.bind('What happens when calibration is overdue?',SOURCE+'\n\nExcept during maintenance.')['state'],'conflict')
 def test_spans_and_empty_context(self):
  r=b.bind('What happens when calibration is overdue?',SOURCE)['rule']
  for k in ['condition','outcome']:
   span=r['spans'][k];self.assertEqual(SOURCE[span[0]:span[1]],r[k])
  self.assertNotEqual(b.bind('What happens when calibration is overdue?','No policy here.')['state'],'bound')
 def test_spans_reference_the_selected_row_not_earlier_mentions(self):
  text='The word locked appears here first.\n\n'+SOURCE
  r=b.bind('What happens when the seal is open?',text)['rule']
  self.assertGreater(r['spans']['outcome'][0],text.index('| locked'))
 def test_size_budget_is_bytes_and_never_truncates(self):
  text=SOURCE+'\n'+('é'*6000)
  self.assertEqual(b.bind('What happens when calibration is overdue?',text)['state'],'conflict')
