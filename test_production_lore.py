"""Production mode must never create or consume learned authority."""
from unittest.mock import patch
import lore, policy_relevance as gate
import test_policy_lore as fixtures
Q, SOURCE = fixtures.Q, fixtures.SOURCE

class ProductionLoreTests(fixtures.LoreTests):
 def setUp(self):
  super().setUp()
  production=patch('lore.EXPERIMENTAL_PROMOTION',False)
  production.start();self.addCleanup(production.stop)
 def test_enough_votes_and_traps_stay_provisional(self):
  mid=self.observe();self.traps(mid,'gemma');self.traps(mid,'llama')
  for seed,family in [(12,'gemma'),(13,'gemma'),(14,'llama'),(15,'llama')]:self.observe(seed,family)
  self.assertTrue(lore.eligible(lore.inventory(self.db)[mid]))
  self.assertEqual(lore.inventory(self.db)[mid]['state'],'provisional')
 def test_imported_promotion_requires_fresh_fallback(self):
  with patch('lore.EXPERIMENTAL_PROMOTION',True):mid=self.promoted()
  self.assertFalse(lore.active(lore.inventory(self.db)[mid]))
  self.assertIsNone(lore.lookup(self.db,Q,self.source))
  pair={k:self.rule[k] for k in ('condition','outcome')}
  with patch('relevance_cookie.review',return_value=self.review(99)) as worker,patch('lore.run_traps') as traps:
   r=gate.assess(self.db,'fresh',Q,self.source,SOURCE,pair,pair,'test',99,0)
   self.assertTrue(r['accepted']);self.assertEqual(r['path'],'fallback');worker.assert_called_once()
   self.assertEqual(gate.finalize(self.db,'fresh',Q,self.source,SOURCE,r,'test'),mid);traps.assert_not_called()
  self.assertFalse(lore.refresh(self.db,mid,self.review(99)))
  forged={'status':'supported_answer','binding_path':'promoted','mapping_id':mid,'answer':'inspection_required'}
  lore.deliver(self.db,'forged',forged);self.assertEqual(forged['status'],'needs_review')
 def test_provisional_delivery_revoke_and_future_block(self):
  mid=self.observe();r={'status':'supported_answer','binding_path':'fallback','mapping_id':mid,'answer':'inspection_required'}
  lore.deliver(self.db,'accepted',r);lore.revoke(self.db,mid,'audit found error')
  self.assertTrue(lore.affected(self.db,mid)[0]['flagged']);self.assertEqual(lore.trusted_answers(self.db),[])
  with patch('relevance_cookie.review') as worker:
   r=gate.assess(self.db,'blocked',Q,self.source,SOURCE,{}, {},'test',11,0)
   self.assertFalse(r['accepted']);worker.assert_not_called()

 def test_calibration_seal_wrong_row_is_blocked_in_production(self):
  fixtures.LoreTests.test_end_to_end_trap_and_good_prose(self)
 def test_existing_promotion_cannot_mask_fallback_failure(self):
  with patch('lore.EXPERIMENTAL_PROMOTION',True):mid=self.promoted()
  pair={k:self.rule[k] for k in ('condition','outcome')}
  with patch('relevance_cookie.review',side_effect=ValueError('malformed')) as worker:
   r=gate.assess(self.db,'fresh',Q,self.source,SOURCE,pair,pair,'test',99,0)
   self.assertFalse(r['accepted']);worker.assert_called_once()
  self.assertTrue(lore.inventory(self.db)[mid]['audit_due'])

# Reuse fixture helpers, not the experimental test methods.
for name in dir(fixtures.LoreTests):
 if name.startswith('test_') and name not in ProductionLoreTests.__dict__:
  setattr(ProductionLoreTests,name,None)

class ProductionDefaultTests(fixtures.unittest.TestCase):
 def test_production_default_is_disabled(self):
  self.assertIs(lore.EXPERIMENTAL_PROMOTION,False)
