"""Compose deterministic binding, snapshot-bound lore, and an isolated fallback."""
import hive
import lore
import policy_binding as binding
import relevance_cookie


def assess(db, run, question, source, text, solver, support, model, seed, temperature, requalify=False):
    decision = binding.bind(question, text)
    result = {'accepted': False, 'path': 'deterministic', 'decision': decision}
    mid = lore.key(question, source)
    existing = lore.inventory(db).get(mid)
    if decision['state'] in {'mismatch','conflict'}:
        result['reason'] = decision['reason']
    elif existing and existing['state'] in {'revoked','quarantined'}:
        result['reason'] = 'mapping_disabled'
    else:
        rule = decision.get('rule')
        if rule is None and existing and lore.active(existing) and not requalify:
            result.update(path='promoted', mapping_id=mid)
            rule = existing['rule']
            if not any(rule == r for r in decision['rules']):
                rule = None;result['reason']='promoted_rule_not_in_snapshot'
        elif rule is None:
            result['path']='fallback'
            try:
                review = relevance_cookie.review(db,run,question,text,model,seed,temperature,
                    lore.next_purpose(db,question,source,model))
                result['review']=review
                rule=review['rule'] if review['accepted'] else None
                if rule is None:result['reason']='relevance_abstention_ambiguity_or_invalid_selection'
            except Exception as error:
                hive.append(db,run,'cookie-relevance','relevance_error',{'error':str(error)})
                result['reason']='relevance_call_failed'
        if rule:
            result.update(rule=rule,accepted=binding.agrees(rule,solver) and binding.agrees(rule,support))
            if not result['accepted']:result['reason']='cookie_rule_disagreement'
        if existing and (not result['accepted'] or existing['rule'] != result.get('rule')):
            if result.get('reason')=='relevance_call_failed':
                lore.require_audit(db,mid,'Relevance audit could not complete')
            else:
                lore.quarantine(db,mid,result.get('reason','Binding changed'))
            result['accepted']=False
    event = hive.append(db,run,'cookie-relevance','policy_binding',{
        **result,'question':question,'source_id':source['source_id'],'sha256':source['sha256'],
        'context_sha256':hive.digest(text)})
    result['event_id']=event
    return result


def finalize(db, run, question, source, text, result, model):
    """Only called after all old checks plus final freshness succeeded."""
    mid=result.get('mapping_id')
    if result['path']=='fallback':
        mid=lore.observe(db,run,question,source,result['review'])
        if mid and lore.EXPERIMENTAL_PROMOTION:
            m=lore.inventory(db)[mid]
            digest=result['review']['identity']['digest']
            if m['state']=='promoted':
                lore.run_traps(db,mid,text,model)
                lore.refresh(db,mid,result['review'])
            elif lore.eligible(m):
                from datetime import datetime, timedelta
                if m['audit_due'] or not any(t['passed'] and t['identity']['digest']==digest and lore.now()-datetime.fromisoformat(t['recorded_at'])<timedelta(days=lore.AUDIT_DAYS) for t in m['trap_reports']):
                    lore.run_traps(db,mid,text,model)
    return mid
