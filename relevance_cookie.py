"""Independent full-snapshot relevance request; neither answer is an input."""
import json
import secrets
from urllib.request import Request, build_opener, ProxyHandler
import hive
from ollama_local import ask, audit_session
import policy_binding as binding

VERSION = 'relevance-v2'

def local_api(path, body=None):
    request = Request('http://127.0.0.1:11434/api/' + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json'})
    with build_opener(ProxyHandler({})).open(request, timeout=30) as response:
        return json.load(response)

def identity(model):
    tags = local_api('tags')['models']
    entries = [m for m in tags if model in (m.get('name'), m.get('model'))]
    if len(entries) != 1:
        raise ValueError('Cannot resolve exact installed model tag')
    details = local_api('show', {'model': model})['details']
    family = details.get('family')
    digest = entries[0].get('digest')
    if not family or not isinstance(digest, str) or len(digest) != 64:
        raise ValueError('Missing model family or digest; relevance fails closed')
    return {'tag': model, 'digest': digest, 'family': family.casefold(), 'runtime': local_api('version')['version']}

def review(db,run_id,question,text,model,seed,temperature,purpose='binding'):
    parsed=binding.rules(text)
    if len(text.encode())>binding.MAX_CONTEXT or not parsed:raise ValueError('Complete policy context unavailable')
    if seed is None:seed=secrets.randbelow(2**31)
    before=identity(model)
    context={'question':question,'source_context':text,'rules':parsed}
    instruction=('Independently determine which policy rule answers the question. Do not merely choose a coherent row. '
        'Consider all competing rules, negation, exceptions and prerequisites in the complete source. '
        'Only one unambiguous applicable rule is acceptable. '
        'A question can be shorthand for asking about a rule; its answer will explicitly include the complete source condition, '
        'not assert that the prerequisites have occurred. '
        'If the question explicitly contradicts a prerequisite, or more than one rule applies, abstain or report ambiguous.')
    if purpose=='prerequisite_audit':instruction+=' This is a fresh adversarial prerequisite audit: actively check omitted prerequisites and competing rules before selecting.'
    def call(stage,fields,extra):
        prompt=instruction+extra
        if len((prompt+json.dumps(context)+json.dumps(fields)).encode())>15000:raise ValueError('Context budget exceeded')
        with audit_session(db,run_id,'cookie-relevance'):
            answer,record=ask(model,prompt,context,fields,seed=seed,temperature=temperature,num_ctx=16384)
        eid=hive.append(db,run_id,'cookie-relevance','model_call',{**record,'identity':before,'purpose':purpose,
            'prompt_version':VERSION,'stage':stage,'context_sha256':hive.digest(context)})
        if set(answer)!=set(fields) or any(type(v) is not str for v in answer.values()):raise ValueError('Malformed stage response')
        if any(v not in fields[k]['enum'] for k,v in answer.items()):raise ValueError('Invalid stage choice')
        return answer,eid
    decision,event=call('decision',{'decision':{'type':'string','enum':['bound','ambiguous','abstain']}},
        ' Return only the decision. Use bound only if an applicable rule can be selected unambiguously; otherwise ambiguous or abstain.')
    selection=None;rule=None;selection_event=None
    if decision['decision']=='bound':
        selection,selection_event=call('selection',{'rule_id':{'type':'string','enum':['',*[r['id'] for r in parsed]]}},
            ' Independently select the applicable rule_id. Return an empty rule_id if no unique applicable rule can be established. Do not assume a previous decision exists.')
        rule=next((r for r in parsed if r['id']==selection['rule_id']),None)
    after=identity(model)
    if before!=after:raise ValueError('Model identity changed')
    return {'accepted':rule is not None,'rule':rule,'raw':{'decision':decision,'selection':selection},
        'qualification':rule['condition'] if rule else None,'event_id':selection_event or event,'decision_event_id':event,
        'identity':before,'seed':seed,'purpose':purpose,'prompt_version':VERSION}
