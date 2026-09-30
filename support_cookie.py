#!/usr/bin/env python3
"""Independent request context: question and quote only, never the proposed answer."""
import json
import sys

from ollama_local import ask, audit_session
from contextlib import nullcontext
from policy_tables import POLICY_INSTRUCTION, policy_question, status_fields
import policy_slots

ANSWER_FIELDS = {"outcome": {"type": "string", "enum": ["answered", "not_found_in_source"]},
                 "answer": {"type": "string"}}
ANSWER_STYLE = (
    "Use the shortest exact text span that fully answers the question, without adding explanation. "
    "For a yes/no question return only Yes or No if the text explicitly establishes it. "
    "Do not infer missing names, quantities or dates from related text. "
)


def question_guidance(question):
    if question.strip().casefold().startswith("who "):
        return (" This is an identity question. An answer must identify the person or organization "
                "that performed the action asked about, explicitly named in the evidence. "
                "A policy trigger or status does not identify that actor. If no such identity is given, "
                "return outcome='not_found_in_source' and answer=''; never put 'not found' or an "
                "absence explanation in an answered result. Leave any citation fields empty when abstaining.")
    return ""


def review(question, quote, model, seed=None, temperature=0):
    if policy_slots.question_route(question) == "review":
        raise ValueError("Unclassified question requires review")
    if policy_slots.policy_mode(question, [quote]):
        slot = policy_slots.requested_slot(question)
        return ask(model, "You are the independent support cookie. Use only the supplied quote. "
                   + policy_slots.INSTRUCTION + f" Requested slot: {slot}.",
                   {"question": question, "quote": quote}, policy_slots.fields([quote]), seed=seed, temperature=temperature)
    return ask(model,
        "You are the support cookie. Answer the question using ONLY the supplied quote. "
        "Shared keywords are not sufficient evidence. If the quote does not directly answer the question, "
        "return outcome='not_found_in_source' and answer=''. Otherwise return outcome='answered'. "
        + ANSWER_STYLE + question_guidance(question) + (POLICY_INSTRUCTION if policy_question(question) else "")
        + ' If the requested fact is absent, the complete response must be '
          '{"outcome":"not_found_in_source","answer":""}. '
          'This is a successful search with no answer, not an answered result.',
        {"question": question, "quote": quote}, status_fields(ANSWER_FIELDS, question, [quote]), seed=seed, temperature=temperature)


if __name__ == "__main__":
    request = json.load(sys.stdin)
    audit = request.pop('audit', None)
    with audit_session(**audit) if audit else nullcontext():
        answer, record = review(**request)
    print(json.dumps({"answer": answer, "record": record}))
