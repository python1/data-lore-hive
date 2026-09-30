"""Narrow Markdown policy-table parsing; no domain-specific status values."""
import re


def policy_question(question):
    return question.strip().lower().startswith("what happens when ")


def status_table(text):
    for match in re.finditer(r"(?m)^\|[^\n]+\|(?:\n\|[^\n]+\|)+", text):
        table = match.group()
        lines = table.splitlines()
        cells = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines]
        headers = [c.casefold() for c in cells[0]]
        status_columns = [i for i, h in enumerate(headers) if h in {"status", "resulting status"}]
        if len(status_columns) != 1 or len(cells) < 3 or len(table) > 400:
            continue
        if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells[1]):
            continue
        column = status_columns[0]
        if not all(len(row) == len(headers) for row in cells[2:]):
            continue
        statuses = [row[column].strip("`") for row in cells[2:]]
        if all(statuses):
            return {"quote": table, "statuses": list(dict.fromkeys(statuses))}
    return None


def status_fields(fields, question, texts):
    result = {key: dict(value) for key, value in fields.items()}
    if policy_question(question):
        statuses = []
        for text in texts:
            table = status_table(text)
            if table:
                statuses.extend(table["statuses"])
        if statuses:
            result["answer"]["enum"] = ["", *dict.fromkeys(statuses)]
    return result


POLICY_INSTRUCTION = (
    "For a 'what happens when' question about a policy table, identify the row whose condition matches, "
    "and answer with its Status or Resulting status cell. Do not answer with a condition or a value "
    "from a Promotion column. If no row establishes the requested consequence, abstain. "
)
