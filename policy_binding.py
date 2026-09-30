"""Conservative question-to-rule binding. No probabilistic override of a mismatch."""
import hashlib
import re
import policy_slots

VERSION = 'policy-binding-v1'
MAX_CONTEXT = 12000

def normalize(value):
    return ' '.join(value.casefold().split()).strip('` .!?')

def rules(text):
    result = []
    def add(condition, outcome, cs, os):
        index = len(result)
        identity = hashlib.sha256((VERSION + '\0' + str(index) + '\0' + condition + '\0' + outcome).encode()).hexdigest()
        result.append({'condition': condition, 'outcome': outcome, 'id': identity,
                       'spans': {'condition': [cs, cs+len(condition)], 'outcome': [os, os+len(outcome)]}})
    for table in re.finditer(r'(?m)^\|[^\n]+\|(?:\n\|[^\n]+\|)+', text):
        lines = table.group().splitlines(keepends=True)
        headers = [v.strip().casefold() for v in lines[0].strip().strip('|').split('|')]
        ci = next((i for i,h in enumerate(headers) if h in {'condition','trigger','meaning'}),None)
        oi = next((i for i,h in enumerate(headers) if h in {'outcome','status','resulting status','action','requirement'}),None)
        if ci is None or oi is None or not all(re.fullmatch(r':?-{3,}:?',v.strip()) for v in lines[1].strip().strip('|').split('|')):
            continue
        offset=table.start()+len(lines[0])+len(lines[1])
        for line in lines[2:]:
            cells=list(re.finditer(r'(?<=\|)[^|]+(?=\|)',line))
            if len(cells)==len(headers):
                values=[m.group().strip().strip('`') for m in cells]
                if values[ci] and values[oi]:
                    starts=[offset+m.start()+m.group().find(v) for m,v in zip(cells,values)]
                    add(values[ci],values[oi],starts[ci],starts[oi])
            offset+=len(line)
    for match in re.finditer(r'(?im)(?:^|(?<=[.!?])\s+)(?:if|when|whenever)\s+([^,\n]+),\s*(?:then\s+)?([^\n.!?]+)',text):
        condition=match[1].strip().strip('`')
        consequence=match[2].strip()
        status=re.fullmatch(r'(?:the\s+)?(?:resulting\s+)?status\s+is\s+(.+)',consequence,re.I)
        outcome=(status[1] if status else consequence).strip('` ')
        add(condition,outcome,match.start(1)+match[1].find(condition),match.start(2)+match[2].find(outcome))
    return result

def agrees(rule, response):
    return isinstance(response, dict) and all(normalize(response.get(k, '')) == normalize(rule[k]) for k in ('condition', 'outcome'))

def selector(question):
    q = ' '.join(question.split()).rstrip('?').strip()
    for pattern, slot in [(r'(?:What happens|What is required) (?:when|if) (.+)', 'condition'),
                          (r'(?:When|Under what conditions?) is (?:(?:the )?status )?(.+)', 'outcome')]:
        match = re.fullmatch(pattern, q, re.I)
        if match:
            return slot, normalize(match[1])
    return None, None

def skeleton(value):
    # Used ONLY to veto near misses, never to equate answers.
    value = re.sub(r'\b(?:not|never|no|and|or)\b|[<>]=?|\b\d+(?:\.\d+)*\b', ' ', value)
    return ' '.join(value.split())

def bind(question, text):
    parsed = rules(text)
    result = {'version': VERSION, 'state': 'unclassified', 'rules': parsed, 'reason': 'unrecognized_selector'}
    if len(text.encode("utf-8")) > MAX_CONTEXT or not parsed:
        return {**result, 'state': 'conflict', 'reason': 'incomplete_or_unsupported_policy_context'}
    # Do not let a parsed row erase surrounding exceptions, precedence, or negation.
    if re.search(r'\b(unless|except|override[sd]?|takes precedence|does not apply|not applicable)\b', text, re.I):
        return {**result, 'state': 'conflict', 'reason': 'unsupported_exception_or_precedence'}
    slot, value = selector(question)
    if slot is None:
        return result
    result.update(selector_slot=slot, selector=value)
    matches = [r for r in parsed if normalize(r[slot]) == value]
    if len(matches) > 1:
        return {**result, 'state': 'conflict', 'reason': 'multiple_matching_rules'}
    if len(matches) == 1:
        return {**result, 'state': 'bound', 'rule': matches[0], 'reason': 'literal_selector'}
    if any(skeleton(value) == skeleton(normalize(r[slot])) for r in parsed):
        return {**result, 'state': 'mismatch', 'reason': 'negation_operator_number_or_conjunction_mismatch'}
    return {**result, 'reason': 'selector_requires_interpretation'}
