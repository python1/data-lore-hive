"""Fail-closed, source-backed comparison for explicit minimum-version questions."""
import re
RULE_VERSION = 'minimum-version-v1'
PRODUCT = r'[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)*'
VERSION = r'(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){1,2}'


def applies(question):
    return bool(re.search(r'\b(minimum|lowest|min)\b', question, re.I)
                and re.search(r'\b(version|release)\b', question, re.I))


def product_for(question):
    q = ' '.join(question.split()).rstrip('?').strip()
    for pattern in [rf'What is the minimum (?P<p>{PRODUCT}) version(?: required)?',
                    rf'What is the minimum version of (?P<p>{PRODUCT})(?: required)?']:
        m = re.fullmatch(pattern, q, re.I)
        if m:return m['p'].casefold()
    return None


def answer(value):
    # Full matches: no ignored qualifiers, alternative bounds, ranges or suffixes.
    m = re.fullmatch(rf'\s*(?P<p>{PRODUCT})\s+(?P<op>>=|>|<=|<|=|exactly\s+)?\s*(?P<v>{VERSION})(?P<tail>\s+or\s+(?:newer|later|older)|\s+only)?\s*[.!]?\s*', value, re.I)
    if not m:return None
    op=(m['op'] or '').strip().casefold();tail=' '.join((m['tail'] or '').casefold().split())
    if op and tail:return None
    operator=op or {'or newer':'>=','or later':'>=','or older':'<=','only':'='}.get(tail,'value')
    if operator=='exactly':operator='='
    return {'product':m['p'].casefold(),'version':[int(x) for x in m['v'].split('.')],
            'operator':operator,'original':value,'version_span':list(m.span('v'))}


def source_constraint(quote, product):
    # Only explicit requirement clauses are allowed. The one optional trailing
    # dependency-list sentence has a bounded grammar and cannot change a version.
    tail = r'(?:\s+The scripted mode needs no (?:services|packages|weights|network connections)(?:(?:,\s*(?:or\s+)?|\s+or\s+)(?:services|packages|weights|network connections))*\.)?'
    p=re.escape(product)
    patterns=[rf'Requires\s+(?P<product>{p})\s+(?P<version>{VERSION})\s+(?P<operator>or newer|or later)',
              rf'(?P<product>{p})\s+(?P<operator>>=)\s*(?P<version>{VERSION})\s+is required',
              rf'(?P<product>{p})\s+(?P<version>{VERSION})\s+(?P<operator>or newer|or later)\s+is required',
              rf'(?P<operator>Minimum)\s+(?P<product>{p})\s+version(?: required)?\s+is\s+(?P<version>{VERSION})']
    for pattern in patterns:
        m=re.fullmatch(r'\s*'+pattern+r'\.?'+tail+r'\s*',quote,re.I)
        if m:
            return {'product':product,'operator':'>=','version':[int(x) for x in m['version'].split('.')],
                    'spans':{k:{'start':m.start(k),'end':m.end(k),'text':m[k]} for k in ('product','version','operator')}}
    return None


def compare(question,quote,solver,support):
    result={'rule_version':RULE_VERSION,'requested_type':'minimum_version','question':question,
            'original_solver':solver,'original_support':support,'quote':quote,'verdict':'unclassified'}
    product=product_for(question)
    if not product:
        result['reason']='unrecognized_minimum_version_question';return result
    source=source_constraint(quote,product);result['source']=source
    if source is None:
        result['reason']='unrecognized_or_ambiguous_source_constraint';return result
    for role,text in [('solver',solver),('support',support)]:
        value=answer(text);result[role]=value
        if value is None:
            result['reason']=role+'_answer_unrecognized';return result
        if value['operator']=='value':
            value['operator']='>='
            value['interpretation']='minimum_value_from_question_and_source'
        else:value['interpretation']='explicit_constraint'
    keys=('product','version','operator')
    match=lambda a,b:all(a[k]==b[k] for k in keys)
    result['answers_equivalent']=match(result['solver'],result['support'])
    result['solver_source_supported']=match(result['solver'],source)
    result['support_source_supported']=match(result['support'],source)
    result['verdict']='equivalent' if all(result[k] for k in ('answers_equivalent','solver_source_supported','support_source_supported')) else 'different'
    result['reason']='both_answers_match_source_minimum' if result['verdict']=='equivalent' else 'answer_or_source_constraint_disagrees'
    return result
