"""Synthetic lifecycle tests: no live models or remote nodes."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import hive, knowledge, lore, policy_binding as b, policy_relevance as gate
from test_policy_binding import SOURCE

Q='What happens when calibration has expired?'
class LoreTests(unittest.TestCase):
 def setUp(self):
  experimental=patch("lore.EXPERIMENTAL_PROMOTION",True);experimental.start();self.addCleanup(experimental.stop)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.db=Path(self.tmp.name)/'memory.sqlite3';self.path=Path(self.tmp.name)/'source.md';self.path.write_text(SOURCE)
  s=knowledge.ingest(self.db,self.path);self.source={'source_id':s['source_id'],'sha256':s['sha256']};self.rule=b.rules(SOURCE)[0]
 def review(self,seed=11,family='gemma',purpose='prerequisite_audit',rule=None):
  return {'accepted':True,'rule':rule or self.rule,'event_id':'synthetic-'+str(seed),
          'identity':{'digest':('a' if family=='gemma' else 'b')*64,'family':family,'runtime':'synthetic'},
          'seed':seed,'purpose':purpose}
 def observe(self,seed=11,family='gemma',purpose='prerequisite_audit',rule=None):
  return lore.observe(self.db,'run-'+str(seed),Q,self.source,self.review(seed,family,purpose,rule))
 def traps(self,mid,family):
  with hive.connect(self.db) as c:
   lore.emit(c,'test','lore_traps',{'mapping_id':mid,'passed':True,'identity':self.review(family=family)['identity'],'cases':[{'synthetic':True}]})
 def promoted(self):
  mid=self.observe(11);self.traps(mid,'gemma');self.traps(mid,'llama')
  for seed,family in [(12,'gemma'),(13,'gemma'),(14,'llama'),(15,'llama')]:self.observe(seed,family)
  self.assertTrue(lore.active(lore.inventory(self.db)[mid]));return mid
 def test_five_same_family_never_promotes(self):
  for seed in range(10):mid=self.observe(seed)
  self.traps(mid,'gemma');self.observe(10)
  self.assertEqual(lore.inventory(self.db)[mid]['state'],'provisional')
 def test_duplicate_confirmations_and_missing_traps_do_not_promote(self):
  for _ in range(8):mid=self.observe()
  self.assertEqual(len(lore.recent(lore.inventory(self.db)[mid])),1)
  for seed,family in [(12,'gemma'),(13,'gemma'),(14,'llama'),(15,'llama')]:self.observe(seed,family)
  self.assertTrue(lore.eligible(lore.inventory(self.db)[mid]));self.assertFalse(lore.active(lore.inventory(self.db)[mid]))
 def test_promotion_expiry_and_snapshot_scope(self):
  mid=self.promoted();self.assertEqual(lore.lookup(self.db,Q,self.source)['mapping_id'],mid)
  self.assertIsNone(lore.lookup(self.db,Q,{**self.source,'sha256':'changed'}))
  self.assertIsNone(lore.lookup(self.db,Q+' please',self.source))
  with patch('lore.now',return_value=lore.now()+timedelta(days=31)):
   self.assertFalse(lore.active(lore.inventory(self.db)[mid]))
 def test_revoke_flags_all_and_blocks_delivery_race(self):
  mid=self.promoted()
  result={'status':'supported_answer','answer':'inspection_required','mapping_id':mid,'binding_path':'promoted'}
  lore.deliver(self.db,'old',dict(result));self.assertEqual(len(lore.trusted_answers(self.db)),1)
  lore.revoke(self.db,mid,'Wrong interpretation')
  self.assertTrue(all(x['flagged'] for x in lore.affected(self.db,mid)))
  self.assertEqual(lore.trusted_answers(self.db),[])
  lore.deliver(self.db,'late',result);self.assertEqual(result['status'],'needs_review');self.assertNotIn('answer',result)
  self.assertIsNone(self.observe(90))
 def test_conflict_quarantines_not_majority_vote(self):
  mid=self.observe();self.assertIsNone(self.observe(12,rule=b.rules(SOURCE)[1]))
  self.assertEqual(lore.inventory(self.db)[mid]['state'],'quarantined')
  self.assertIsNone(self.observe(13))
 def test_promoted_binding_and_mismatch_never_call_model(self):
  mid=self.promoted()
  pair={k:self.rule[k] for k in ('condition','outcome')}
  with patch('relevance_cookie.review') as worker:
   r=gate.assess(self.db,'r',Q,self.source,SOURCE,pair,pair,'test',11,0)
   self.assertTrue(r['accepted']);self.assertEqual(r['path'],'promoted');worker.assert_not_called()
   r=gate.assess(self.db,'r','What happens when calibration is not overdue?',self.source,SOURCE,pair,pair,'test',11,0)
   self.assertFalse(r['accepted']);worker.assert_not_called()
 def test_fallback_is_isolated_and_disagreement_quarantines(self):
  mid=self.observe();pair={k:self.rule[k] for k in ('condition','outcome')}
  with patch('relevance_cookie.review',return_value=self.review(rule=b.rules(SOURCE)[1])) as worker:
   r=gate.assess(self.db,'r',Q,self.source,SOURCE,pair,pair,'test',11,0)
   self.assertFalse(r['accepted']);self.assertEqual(worker.call_args.args[2:4],(Q,SOURCE))
  self.assertEqual(lore.inventory(self.db)[mid]['state'],'quarantined')
 def test_unavailable_model_fails_closed(self):
  with patch('relevance_cookie.review',side_effect=ValueError('malformed')):
   r=gate.assess(self.db,'r',Q,self.source,SOURCE,{}, {},'test',11,0)
  self.assertFalse(r['accepted']);self.assertEqual(lore.inventory(self.db),{})
 def test_end_to_end_trap_and_good_prose(self):
  for wrong in [True,False]:
   rule=b.rules(SOURCE)[int(wrong)];pair={'decision':'answered',**{k:rule[k] for k in ('condition','outcome')}}
   q='What happens when calibration is overdue?';chunk=knowledge.search(self.db,q)['candidates'][0]
   proposal={**pair,'chunk_id':chunk['chunk_id'],'quote':SOURCE}
   with patch('knowledge.ask',return_value=(proposal,{})),patch('knowledge.support_review',return_value=(pair,{})),patch('relevance_cookie.review') as relevance:
    r=knowledge.answer_question(self.db,q,'test',11)
   self.assertEqual(r['status'],'needs_review' if wrong else 'supported_answer');relevance.assert_not_called()
 def test_fallback_delivery_and_revoke(self):
  pair={'decision':'answered',**{k:self.rule[k] for k in ('condition','outcome')}}
  chunk=knowledge.search(self.db,Q)['candidates'][0];proposal={**pair,'quote':SOURCE,'chunk_id':chunk['chunk_id']}
  with patch('knowledge.ask',return_value=(proposal,{})),patch('knowledge.support_review',return_value=(pair,{})),patch('relevance_cookie.review',return_value=self.review()):
   r=knowledge.answer_question(self.db,Q,'test',11)
  self.assertEqual(r['status'],'supported_answer');self.assertIn(self.rule['condition'],r['qualified_answer'])
  mid=r['mapping_id'];lore.revoke(self.db,mid,'test');self.assertTrue(lore.affected(self.db,mid)[0]['flagged'])
 def test_usage_audit_and_refresh_without_five_new_votes(self):
  mid=self.promoted();m=lore.inventory(self.db)[mid];original=m['promotion']['confirmation_ids']
  result={'status':'supported_answer','answer':'inspection_required','mapping_id':mid,'binding_path':'promoted'}
  for i in range(lore.AUDIT_USES):lore.deliver(self.db,str(i),dict(result))
  self.assertFalse(lore.active(lore.inventory(self.db)[mid]))
  review=self.review(900);self.traps(mid,'gemma')
  self.assertTrue(lore.refresh(self.db,mid,review));m=lore.inventory(self.db)[mid]
  self.assertTrue(lore.active(m));self.assertEqual(m['promotion']['confirmation_ids'],original)
 def test_unknown_question_does_not_bypass_revocation(self):
  mid=self.observe();lore.revoke(self.db,mid,'test')
  with patch('relevance_cookie.review') as call:
   r=gate.assess(self.db,'run',Q,self.source,SOURCE,{}, {},'test',11,0)
  self.assertFalse(r['accepted']);call.assert_not_called()
 def test_conflict_flags_prior_provisional_answers(self):
  mid=self.observe();lore.deliver(self.db,'prior',{'status':'supported_answer','mapping_id':mid,'answer':'inspection_required'})
  self.observe(12,rule=b.rules(SOURCE)[1]);self.assertTrue(lore.affected(self.db,mid)[0]['flagged'])
 def test_same_digest_seed_cannot_double_count_different_purpose(self):
  mid=self.observe(11,purpose='binding');self.observe(11,purpose='prerequisite_audit')
  self.assertEqual(len(lore.recent(lore.inventory(self.db)[mid])),1)
 def test_trap_failure_quarantines_and_flags(self):
  mid=self.observe();lore.deliver(self.db,'old',{'status':'supported_answer','answer':'inspection_required','mapping_id':mid})
  with patch('relevance_cookie.review',return_value=self.review()),patch('relevance_cookie.identity',return_value=self.review()['identity']):
   results=lore.run_traps(self.db,mid,SOURCE,'synthetic')
  self.assertFalse(all(v['passed'] for v in results));self.assertEqual(lore.inventory(self.db)[mid]['state'],'quarantined')
  self.assertTrue(lore.affected(self.db,mid)[0]['flagged'])
 def test_stale_source_during_finalize_withholds(self):
  pair={'decision':'answered',**{k:self.rule[k] for k in ('condition','outcome')}}
  q='What happens when calibration is overdue?';chunk=knowledge.search(self.db,q)['candidates'][0]
  proposal={**pair,'quote':SOURCE,'chunk_id':chunk['chunk_id']}
  def mutate(*args):self.path.write_text('changed');return None
  with patch('knowledge.ask',return_value=(proposal,{})),patch('knowledge.support_review',return_value=(pair,{})),patch('policy_relevance.finalize',side_effect=mutate):
   r=knowledge.answer_question(self.db,q,'test',11)
  self.assertEqual(r['status'],'stale_source');self.assertNotIn('answer',r)
 def test_promotion_needs_audits_from_both_families(self):
  mid=self.observe(11);self.traps(mid,'gemma');self.traps(mid,'llama')
  for seed,family in [(12,'gemma'),(13,'gemma'),(14,'llama'),(15,'llama')]:self.observe(seed,family,purpose='binding')
  self.assertFalse(lore.eligible(lore.inventory(self.db)[mid]));self.assertFalse(lore.active(lore.inventory(self.db)[mid]))
  self.observe(16,'llama',purpose='prerequisite_audit');self.assertTrue(lore.active(lore.inventory(self.db)[mid]))
 def test_fewer_than_five_confirmations_cannot_promote(self):
  mid=self.observe(11);self.traps(mid,'gemma');self.traps(mid,'llama')
  for seed,family in [(12,'gemma'),(14,'llama'),(15,'llama')]:self.observe(seed,family)
  self.assertFalse(lore.active(lore.inventory(self.db)[mid]))
 def test_operational_audit_failure_disables_reuse_without_revoking(self):
  mid=self.promoted();pair={k:self.rule[k] for k in ('condition','outcome')}
  with patch('relevance_cookie.review',side_effect=OSError('offline')):
   r=gate.assess(self.db,'run',Q,self.source,SOURCE,pair,pair,'test',11,0,requalify=True)
  m=lore.inventory(self.db)[mid];self.assertFalse(r['accepted']);self.assertFalse(lore.active(m))
  self.assertEqual(m['state'],'promoted');self.assertTrue(m['audit_due'])
 def test_audit_due_requires_fresh_audit_not_repromotion_from_old_votes(self):
  mid=self.promoted();original=lore.inventory(self.db)[mid]['promotion']
  lore.require_audit(self.db,mid,'due')
  self.observe(90,'gemma')
  m=lore.inventory(self.db)[mid]
  self.assertFalse(lore.active(m));self.assertEqual(m['promotion'],original)
 def test_alias_tag_same_digest_and_seed_is_one_confirmation(self):
  first=self.review();first['identity']['tag']='gemma4:e4b'
  mid=lore.observe(self.db,'first',Q,self.source,first)
  second=self.review();second['identity']['tag']='zoro:latest'
  lore.observe(self.db,'alias',Q,self.source,second)
  self.assertEqual(len(lore.recent(lore.inventory(self.db)[mid])),1)
