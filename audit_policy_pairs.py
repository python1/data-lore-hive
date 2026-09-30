"""Read-only audit of accepted source-policy answers against stored evidence."""
import argparse,hashlib,json,sqlite3
from pathlib import Path
import policy_slots

def audit(path):
    path=Path(path).resolve();before=hashlib.sha256(path.read_bytes()).hexdigest()
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        rows=[{**dict(r),'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM events ORDER BY sequence')]
    finally:db.close()
    by_id={r['id']:r for r in rows};findings=[]
    queries=[r for r in rows if r['kind']=='knowledge_query']
    accepted=[r for r in queries if r['payload'].get('status')=='supported_answer']
    for row in accepted:
        result=row['payload'];related=[r for r in rows if r['run_id']==row['run_id'] and r['sequence']<row['sequence']]
        extracts=[r for r in related if r['kind']=='policy_extraction']
        if not (extracts or result.get('question_route')=='policy' or policy_slots.requested_slot(result.get('question',''))):continue
        citation=result.get('citation',{});source=by_id.get(citation.get('source_id'),{});snapshot=source.get('payload',{});quote=result.get('quote','')
        source_ok=(source.get('kind')=='source_ingested' and bool(quote) and quote in snapshot.get('text','') and
                   hashlib.sha256(snapshot.get('text','').encode()).hexdigest()==citation.get('sha256')==snapshot.get('sha256'))
        item={'event_id':row['id'],'sequence':row['sequence'],'run_id':row['run_id'],'question':result['question'],
              'answer':result.get('answer'),'source_id':citation.get('source_id'),'quote_matches_verified_snapshot':source_ok,'cookies':{}}
        slot=result.get('requested_slot') or policy_slots.requested_slot(result['question'])
        for cookie in ['cookie-solver','cookie-support']:
            events=[e for e in extracts if e['cookie']==cookie]
            event=events[-1] if events else None;raw=event['payload'].get('raw',{}) if event else {}
            item['cookies'][cookie]={'extraction_id':event['id'] if event else None,'pair':raw,
                'pair_consistent':source_ok and policy_slots.pair_matches(raw,quote),
                'requested_value_matches_finding':raw.get(slot)==result.get('answer') if slot else False}
        item['pass']=source_ok and all(c['pair_consistent'] and c['requested_value_matches_finding'] for c in item['cookies'].values())
        findings.append(item)
    after=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'database':str(path),'sha256_before':before,'sha256_after':after,'database_unchanged':before==after,
            'event_count':len(rows),'accepted_positive_answers':len(accepted),'accepted_policy_answers':len(findings),
            'passed':sum(x['pass'] for x in findings),'failed':sum(not x['pass'] for x in findings),'findings':findings,
            'not_found_queries':sum(r['payload'].get('status')=='not_found_in_source' for r in queries),
            'historical_source_excerpts':sum(r['payload'].get('status')=='source_excerpt' for r in queries),
            'scope':'All supported_answer query records; policy identified by route, question slot or extraction events. Not-found findings have no accepted pair; historical source_excerpt records were not accepted answers. Stored snapshots used, no original files or model calls.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);args=p.parse_args()
    result=audit(args.db);print(json.dumps(result,indent=2));raise SystemExit(0 if result['database_unchanged'] and not result['failed'] else 1)
