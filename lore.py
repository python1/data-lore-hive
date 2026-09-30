"""Append-only, snapshot-bound policy interpretations. No background jobs or remote access."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import uuid
import hive
import policy_binding as binding
import relevance_cookie

# Production has no CLI/environment opt-in. Experiments live on a separate branch.
EXPERIMENTAL_PROMOTION = False

N = 5
AUDIT_DAYS = 30
AUDIT_USES = 100
WINDOW_DAYS = 7
VERSION = 'lore-v1'

def now():
    return datetime.now(timezone.utc)

def key(question, source):
    return hive.digest({'question': ' '.join(question.casefold().split()), 'source_id': source['source_id'],
                        'sha256': source['sha256'], 'binding': binding.VERSION, 'relevance': relevance_cookie.VERSION,
                        'lore': VERSION})

def emit(connection, run, kind, payload):
    event_id = str(uuid.uuid4())
    connection.execute('INSERT INTO events(id,run_id,cookie,kind,recorded_at,payload) VALUES(?,?,?,?,?,?)',
        (event_id, run, 'cookie-lore', kind, now().isoformat(), hive.canonical(payload)))
    return event_id

def events(connection):
    return [{**dict(r), 'payload': json.loads(r['payload'])} for r in connection.execute(
        "SELECT * FROM events WHERE kind LIKE 'lore_%' OR kind='knowledge_query' ORDER BY sequence")]

def materialize(rows):
    mappings = {}
    for e in rows:
        p = e['payload']; mid = p.get('mapping_id')
        if e['kind'] == 'lore_provisional':
            mappings[mid] = {**p, 'state': 'provisional', 'confirmations': [], 'trap_reports': [], 'promotion': None, 'audit': None, 'uses_since_audit': 0, 'audit_due': False}
        elif mid in mappings:
            m = mappings[mid]
            if e['kind'] == 'lore_confirmation':m['confirmations'].append({**p, 'id': e['id'], 'recorded_at': e['recorded_at']})
            elif e['kind'] == 'lore_traps':m['trap_reports'].append({**p, 'recorded_at': e['recorded_at']})
            elif e['kind'] == 'lore_promoted' and m['state'] not in {'revoked', 'quarantined'}:
                m['state'] = 'promoted';m['promotion'] = {**p, 'recorded_at': e['recorded_at']}
                m['audit'] = m['promotion'];m['uses_since_audit'] = 0;m['audit_due'] = False
            elif e['kind'] == 'lore_audit_passed' and m['state'] == 'promoted':
                m['audit'] = {**p, 'recorded_at': e['recorded_at']};m['uses_since_audit'] = 0;m['audit_due'] = False
            elif e['kind']=='lore_audit_due':m['audit_due']=True
            elif e['kind'] == 'knowledge_query' and p.get('status') == 'supported_answer' and p.get('binding_path') == 'promoted':
                m['uses_since_audit'] += 1
            elif e['kind'] in {'lore_revoked', 'lore_quarantined'}:
                m['state'] = e['kind'][5:];m['reason'] = p['reason']
    return mappings

def inventory(db):
    with hive.connect(db) as c:return materialize(events(c))

def active(m):
    return (EXPERIMENTAL_PROMOTION and m['state'] == 'promoted' and not m['audit_due'] and
            m['uses_since_audit'] < AUDIT_USES and
            now() - datetime.fromisoformat(m['audit']['recorded_at']) < timedelta(days=AUDIT_DAYS))

def lookup(db, question, source):
    m = inventory(db).get(key(question, source))
    return m if m and (active(m) or m['state'] in {'revoked', 'quarantined'}) else None

def recent(m):
    cutoff = now() - timedelta(days=WINDOW_DAYS)
    unique = {}
    for c in m['confirmations']:
        if datetime.fromisoformat(c['recorded_at']) >= cutoff:
            i = c['identity']; unique.setdefault((i['digest'], c['seed']), c)
    return list(unique.values())

def eligible(m):
    confirmations = recent(m)
    families = Counter(c['identity']['family'] for c in confirmations)
    return (len(confirmations) >= N and sum(n >= 2 for n in families.values()) >= 2 and
            len({c['identity']['family'] for c in confirmations if c['purpose']=='prerequisite_audit'}) >= 2)

def promote_if_ready(c, mid, run):
    if not EXPERIMENTAL_PROMOTION:return
    m = materialize(events(c))[mid]
    if m['state'] in {'revoked', 'quarantined', 'promoted'} or not eligible(m):return
    cutoff = now() - timedelta(days=AUDIT_DAYS)
    passed = {t['identity']['digest'] for t in m['trap_reports'] if t['passed'] and datetime.fromisoformat(t['recorded_at']) >= cutoff}
    confirmations = recent(m)
    qualifying = [v for v in confirmations if v['identity']['digest'] in passed]
    families = Counter(v['identity']['family'] for v in qualifying)
    if len(qualifying) >= N and sum(v >= 2 for v in families.values()) >= 2 and len({v['identity']['family'] for v in qualifying if v['purpose']=='prerequisite_audit'})>=2:
        emit(c, run, 'lore_promoted', {'mapping_id': mid, 'confirmation_ids': [v['id'] for v in qualifying],
            'policy': VERSION, 'audit_after_days': AUDIT_DAYS, 'audit_after_uses': AUDIT_USES, 'meaning': 'Meets promotion policy, not proof of truth'})

def observe(db, run, question, source, review):
    """Called only after every answer gate and a fresh source check passed."""
    mid = key(question, source)
    with hive.connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        m = materialize(events(c)).get(mid)
        if m and m['state'] in {'revoked','quarantined'}:return None
        if m and m['rule'] != review['rule']:
            emit(c, run, 'lore_quarantined', {'mapping_id': mid, 'reason': 'Conflicting independently selected rule'})
            flag_dependents(c, mid, 'Conflicting independently selected rule')
            return None
        if not m:
            emit(c, run, 'lore_provisional', {'mapping_id': mid, 'question': question, 'source_id': source['source_id'],
                'sha256': source['sha256'], 'rule': review['rule'], 'qualification': review['rule']['condition'],
                'versions': [VERSION, binding.VERSION, relevance_cookie.VERSION]})
        emit(c, run, 'lore_confirmation', {'mapping_id': mid, 'identity': review['identity'], 'seed': review['seed'],
             'purpose': review['purpose'], 'model_event_id': review['event_id'], 'run_id': run})
        promote_if_ready(c, mid, run)
    return mid

def require_audit(db, mid, reason):
    with hive.connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        if mid in materialize(events(c)):
            emit(c,str(uuid.uuid4()),'lore_audit_due',{'mapping_id':mid,'reason':reason})

def quarantine(db, mid, reason):
    with hive.connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        m = materialize(events(c)).get(mid)
        if m and m['state'] not in {'revoked','quarantined'}:
            emit(c, str(uuid.uuid4()), 'lore_quarantined', {'mapping_id': mid, 'reason': reason})
            flag_dependents(c, mid, reason)

def flag_dependents(c, mid, reason):
    for e in events(c):
        if e['kind'] == 'knowledge_query' and e['payload'].get('mapping_id') == mid and e['payload'].get('status') == 'supported_answer':
            emit(c, str(uuid.uuid4()), 'lore_answer_flagged', {'mapping_id': mid, 'answer_event_id': e['id'],
                'finding_id': e['payload'].get('finding_id'), 'reason': reason})

def revoke(db, mid, reason):
    if not reason.strip():raise ValueError('Revocation requires a reason')
    with hive.connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        if mid not in materialize(events(c)):raise ValueError('Unknown mapping')
        emit(c, str(uuid.uuid4()), 'lore_revoked', {'mapping_id': mid, 'reason': reason})
        flag_dependents(c, mid, reason)
    return {'mapping_id': mid, 'state': 'revoked', 'affected': affected(db, mid)}

def affected(db, mid):
    with hive.connect(db) as c:
        rows = events(c)
    flagged = {e['payload']['answer_event_id'] for e in rows if e['kind'] == 'lore_answer_flagged'}
    return [{'event_id': e['id'], 'flagged': e['id'] in flagged, 'result': e['payload']} for e in rows
            if e['kind'] == 'knowledge_query' and e['payload'].get('mapping_id') == mid and e['payload'].get('status') == 'supported_answer']

def trusted_answers(db):
    with hive.connect(db) as c:rows = events(c)
    mappings = materialize(rows)
    return [{**e['payload'], 'event_id': e['id']} for e in rows if e['kind']=='knowledge_query'
        and e['payload'].get('status')=='supported_answer' and (not e['payload'].get('mapping_id') or
        mappings.get(e['payload']['mapping_id'],{}).get('state') not in {'revoked','quarantined'})]

def deliver(db, run, result):
    """Serialize delivery with revoke so no newly delivered answer escapes its flag."""
    with hive.connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        mid = result.get('mapping_id')
        if mid and result['status'] == 'supported_answer':
            m = materialize(events(c)).get(mid)
            if not m or m['state'] in {'revoked','quarantined'} or m['audit_due'] or (result.get('binding_path')=='promoted' and not active(m)):
                for k in ('answer','qualified_answer','qualification','quote','citation'):result.pop(k,None)
                result.update(status='needs_review', reason='mapping_unavailable_at_delivery')
        return emit(c, run, 'knowledge_query', result)

def next_purpose(db, question, source, model=None):
    m = inventory(db).get(key(question,source))
    return 'prerequisite_audit' if not m or m['state']=='promoted' or not any(v['purpose']=='prerequisite_audit' and v['identity'].get('tag')==model for v in recent(m)) or sum(v['purpose']=='prerequisite_audit' for v in recent(m))<2 else 'binding'

def run_traps(db, mid, text, model, seed=101):
    m = inventory(db)[mid];rule = m['rule'];reports=[]
    # Expected rule ids come from exact source selectors, not from the model under test.
    cases = [(m['question'],rule['id']), ('What happens when '+rule['condition']+'?', rule['id'])]
    cases += [('What happens when '+r['condition']+'?',r['id']) for r in binding.rules(text) if r['id']!=rule['id']]
    cases += [('What happens when it is not true that '+rule['condition']+'?',None),
              ('What happens when an unspecified different prerequisite holds?',None)]
    for index,(question,expected) in enumerate(cases):
        run=str(uuid.uuid4())
        try:
            review=relevance_cookie.review(db,run,question,text,model,seed+index,0,'prerequisite_audit')
            actual=review['rule']['id'] if review['accepted'] else None
            reports.append({'question':question,'expected':expected,'actual':actual,'passed':actual==expected,
                            'model_event_id':review['event_id'], 'identity':review['identity']})
        except Exception as error:
            reports.append({'question':question,'passed':False,'error':str(error)})
    try:
        identity=relevance_cookie.identity(model)
    except Exception as error:
        identity={}
        reports.append({'passed':False,'error':str(error)})
    passed=all(r['passed'] and r.get('identity')==identity for r in reports)
    with hive.connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        emit(c,str(uuid.uuid4()),'lore_traps',{'mapping_id':mid,'identity':identity,'passed':passed,'cases':reports})
        if not passed and any('error' in r for r in reports):
            emit(c,str(uuid.uuid4()),'lore_audit_due',{'mapping_id':mid,'reason':'Adversarial audit could not complete'})
        elif not passed:
            emit(c,str(uuid.uuid4()),'lore_quarantined',{'mapping_id':mid,'reason':'Binding-specific adversarial checks failed'})
            flag_dependents(c,mid,'Binding-specific adversarial checks failed')
        else:promote_if_ready(c,mid,str(uuid.uuid4()))
    return reports

def refresh(db, mid, review):
    if not EXPERIMENTAL_PROMOTION:return False
    with hive.connect(db) as c:
        c.execute('BEGIN IMMEDIATE')
        m=materialize(events(c)).get(mid)
        if not m or m['state']!='promoted' or m['rule']!=review['rule']:return False
        latest=m['trap_reports'][-1] if m['trap_reports'] else None
        if not latest or not latest['passed'] or latest['identity']!=review['identity']:return False
        if now()-datetime.fromisoformat(latest['recorded_at'])>timedelta(minutes=30):return False
        emit(c,str(uuid.uuid4()),'lore_audit_passed',{'mapping_id':mid,'model_event_id':review['event_id'],
             'identity':review['identity'],'policy':VERSION})
        return True

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',default='knowledge.sqlite3')
    sub=p.add_subparsers(dest='command',required=True)
    ls=sub.add_parser('list');ls.add_argument('--state',choices=['provisional','promoted','revoked','quarantined'])
    for name in ('inspect','affected','revoke','qualify'):
        q=sub.add_parser(name);q.add_argument('mapping_id')
        if name=='revoke':q.add_argument('--reason',required=True)
        if name=='qualify':
            q.add_argument('--model',required=True);q.add_argument('--seed',required=True,type=int)
            q.add_argument('--recovery-root')
    args=p.parse_args();hive.initialize(args.db)
    if args.command=='list':
        result=[{**m,'active':active(m)} for m in inventory(args.db).values() if not args.state or m['state']==args.state]
    elif args.command=='revoke':result=revoke(args.db,args.mapping_id,args.reason)
    elif args.command=='affected':result=affected(args.db,args.mapping_id)
    elif args.command=='inspect':result=inventory(args.db)[args.mapping_id]
    else:
        import knowledge
        m=inventory(args.db)[args.mapping_id]
        if m['state'] in {'revoked','quarantined'}:raise ValueError('Mapping is disabled')
        candidates=knowledge.search(args.db,m['question'],recovery_root=args.recovery_root)['candidates']
        if not any(v['source_id']==m['source_id'] and v['sha256']==m['sha256'] for v in candidates):
            raise ValueError('Mapping snapshot is stale, unavailable, or not retrieved; cannot qualify it')
        result=knowledge.answer_question(args.db,m['question'],args.model,args.seed,0,recovery_root=args.recovery_root,
                                       requalify=True)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
