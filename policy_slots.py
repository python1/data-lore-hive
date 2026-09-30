"""Conservative policy roles and question slots, derived from source structure."""
import re


def requested_slot(question):
    q = " ".join(question.casefold().split())
    if re.match(r"^(what happens\b|what is required\b)", q):
        return "outcome"
    if re.match(r"^(when\b|under what conditions?\b)", q):
        return "condition"
    return None


def rules(text):
    result = []
    for match in re.finditer(r"(?m)^\|[^\n]+\|(?:\n\|[^\n]+\|)+", text):
        rows = [[c.strip().strip("`") for c in line.strip("|").split("|")] for line in match.group().splitlines()]
        headers = [h.casefold() for h in rows[0]]
        ci = next((i for i, h in enumerate(headers) if h in {"condition", "trigger", "meaning"}), None)
        oi = next((i for i, h in enumerate(headers) if h in {"outcome", "status", "resulting status", "action", "requirement"}), None)
        if ci is None or oi is None or not all(re.fullmatch(r":?-{3,}:?", c) for c in rows[1]):
            continue
        for row in rows[2:]:
            if len(row) == len(headers) and row[ci] and row[oi]:
                result.append({"condition": row[ci], "outcome": row[oi]})
    for match in re.finditer(r"(?im)(?:^|(?<=[.!?])\s+)(?:if|when|whenever)\s+([^,\n]+),\s*(?:then\s+)?([^\n.!?]+)", text):
        condition, consequence = match.group(1).strip(), match.group(2).strip()
        status = re.fullmatch(r"(?:the\s+)?(?:resulting\s+)?status\s+is\s+(.+)", consequence, re.I)
        result.append({"condition": condition.strip("`"), "outcome": (status.group(1) if status else consequence).strip("` ")})
    return result


def question_route(question):
    """Route by question form, never by a table's presence in the evidence."""
    q = " ".join(question.casefold().split())
    if requested_slot(q) is not None:
        return "policy"
    if re.match(r"^(who|whose|which|where)\b|^how (many|much)\b|^what (is|are|was|were)\b|^(is|are|was|were|does|do|did|has|have|can)\b", q):
        return "general"
    # Preserve the existing short keyword lookup interface (e.g. reservoir capacity).
    if (re.fullmatch(r"[\w-]+(?: [\w-]+){0,3}", q)
            and not re.match(r"^(what|how|why|explain|describe|tell|summarize)\b", q)):
        return "general"
    return "review"


def policy_mode(question, texts):
    return question_route(question) == "policy"


def fields(texts):
    values = rules("\n".join(texts))
    schema = {"decision": {"type": "string", "enum": ["answered", "not_found_in_source"]},
              "condition": {"type": "string"}, "outcome": {"type": "string"}}
    for slot in ("condition", "outcome"):
        if values:
            schema[slot]["enum"] = ["", *dict.fromkeys(rule[slot] for rule in values)]
    return schema


def valid(response, slot):
    if not isinstance(response, dict) or not all(type(response.get(k)) is str for k in ("decision", "condition", "outcome")):
        return False
    if slot is None:
        return False
    if response["decision"] == "not_found_in_source":
        return response[slot] == ""
    return response["decision"] == "answered" and bool(response[slot].strip()) and len(response[slot]) <= 400


def role_matches(value, slot, text):
    normalized = " ".join(value.casefold().split()).strip("` .!?")
    return bool(normalized) and any(normalized == " ".join(rule[slot].casefold().split()).strip("` .!?") for rule in rules(text))


def pair_matches(response, text):
    """Both nonempty fields must belong to one parsed rule, never separate rows."""
    if not isinstance(response, dict) or response.get("decision") != "answered":
        return False
    keys = ("condition", "outcome")
    if not all(type(response.get(k)) is str and response[k].strip() for k in keys):
        return False
    normalize = lambda value: " ".join(value.casefold().split()).strip("` .!?")
    return any(all(normalize(response[k]) == normalize(rule[k]) for k in keys)
               for rule in rules(text))


INSTRUCTION = (
    "Extract the policy as separate condition and outcome fields from the cited evidence. "
    "Condition is the trigger; outcome is the consequence, required action, or status. "
    "Copy the exact field values from one applicable rule. Never put a trigger in the outcome field. "
    "Use decision='answered' only if the requested field is established for the question. "
    "Otherwise use decision='not_found_in_source' and leave the requested field empty. "
)
