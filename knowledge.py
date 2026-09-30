#!/usr/bin/env python3
"""Persist local text sources and retrieve attributable excerpts across tasks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

import hive
from ollama_local import ask, audit_session, audit_context
from support_cookie import ANSWER_FIELDS, ANSWER_STYLE, question_guidance
from policy_tables import POLICY_INSTRUCTION, policy_question, status_fields, status_table
import policy_slots
import source_recovery
import version_comparison
import policy_relevance
import lore

MAX_BYTES = 256_000
STOPWORDS = set("a an and are as at be by can do does for from how i in is it of on or our that the their this to was we what when where which with many much".split())


def read_source(path):
    with Path(path).open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Source exceeds {MAX_BYTES} bytes")
    text = raw.decode("utf-8")
    if not text.strip() or "\x00" in text:
        raise ValueError("Source must contain nonempty UTF-8 text")
    return text, hashlib.sha256(raw).hexdigest()


def latest_sources(db_path):
    with hive.connect(db_path) as db:
        rows = db.execute("SELECT id,payload FROM events WHERE kind='source_ingested' ORDER BY sequence DESC").fetchall()
    latest = {}
    for row in rows:
        payload = json.loads(row["payload"])
        latest.setdefault(payload["path"], {"id": row["id"], **payload})
    return list(latest.values())


def ingest(db_path, source_path):
    hive.initialize(db_path)
    path = Path(source_path).resolve()
    if path.suffix.lower() not in {".txt", ".md"}:
        raise ValueError("This version accepts .txt and .md files only")
    text, sha = read_source(path)
    previous = next((source for source in latest_sources(db_path) if source["path"] == str(path)), None)
    if previous and previous["sha256"] == sha:
        return {"status": "already_ingested", "source_id": previous["id"], "sha256": sha}
    event_id = hive.append(db_path, str(uuid.uuid4()), "cookie-ingester", "source_ingested", {
        "path": str(path), "source_uri": path.as_uri(), "sha256": sha, "text": text,
        "supersedes": previous["id"] if previous else None,
        "trust": "User-selected source; content not independently corroborated",
    })
    return {"status": "ingested", "source_id": event_id, "sha256": sha}


def chunks(source):
    # Keep original offsets so citation line numbers and exact quotes are checkable.
    for paragraph in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", source["text"]):
        for start in range(paragraph.start(), paragraph.end(), 900):
            text = source["text"][start:min(start + 900, paragraph.end())]
            if text.strip():
                yield {"chunk_id": f"{source['id']}:{start}", "source_id": source["id"],
                       "path": source["path"], "sha256": source["sha256"],
                       "offset": start, "text": text,
                       **{key: source[key] for key in ("original_path", "recovery_root", "recovery_entry") if key in source}}


def terms(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOPWORDS


def checked_source(source):
    if "recovery_root" in source:
        return source_recovery.read_source(source["recovery_root"], source["recovery_entry"], source["sha256"])
    return read_source(source["path"])


def search(db_path, question, recovery_root=None):
    hive.initialize(db_path)
    if not question.strip() or len(question) > 1000:
        raise ValueError("Question must contain 1–1000 characters")
    wanted = terms(question)
    candidates, excluded = [], []
    sources = latest_sources(db_path)
    mapping = source_recovery.load_map(recovery_root, sources) if recovery_root is not None else None
    for source in sources:
        source = dict(source)
        if mapping is not None:
            source["original_path"] = source["path"]
            source["path"] = str(Path(recovery_root).absolute() / mapping[source["id"]]["path"])
            source["recovery_root"] = str(Path(recovery_root).absolute())
            source["recovery_entry"] = mapping[source["id"]]
        try:
            _, current_hash = checked_source(source)
            if current_hash != source["sha256"]:
                excluded.append({"source_id": source["id"], "path": source["path"], "reason": "changed_since_ingestion"})
                continue
        except (OSError, ValueError) as error:
            excluded.append({"source_id": source["id"], "path": source["path"], "reason": "unavailable", "detail": str(error)})
            continue
        for chunk in chunks(source):
            overlap = wanted & terms(chunk["text"])
            if overlap:
                candidates.append({**chunk, "score": len(overlap)})
    candidates.sort(key=lambda item: (-item["score"], item["path"], item["offset"]))
    return {"question": question, "candidates": candidates[:3], "excluded_sources": excluded,
            "retrieval": "keyword overlap; not semantic search"}


def normalize_answer(answer):
    return " ".join(answer.casefold().split()).strip(" .!?`\"'")


def anchored(answer, quote):
    # Stronger than the minimum: every non-Boolean answer must be an exact span.
    # Boundaries prevent e.g. 37 matching 137, or Ann matching Anna.
    value = normalize_answer(answer)
    if value in {"yes", "no"}:
        return True  # Boolean support is established by the independent cookie.
    text = " ".join(quote.casefold().split())
    return bool(value) and re.search(r"(?<![\w.+-])" + re.escape(value) + r"(?![\w+-]|[.,]\d)", text) is not None


def valid_answer(response):
    if response.get("outcome") == "not_found_in_source":
        return response.get("answer") == ""
    return (response.get("outcome") == "answered" and isinstance(response.get("answer"), str)
            and bool(response["answer"].strip()) and len(response["answer"]) <= 400)


def support_review(question, quote, model, seed, temperature):
    request = {"question": question, "quote": quote, "model": model,
               "seed": seed, "temperature": temperature}
    if audit_context() is not None:
        request['audit'] = audit_context()
    process = subprocess.run([sys.executable, str(Path(__file__).with_name("support_cookie.py"))],
                             input=json.dumps(request), capture_output=True, text=True, timeout=200)
    if process.returncode:
        raise RuntimeError(f"Support cookie failed: {process.stderr}")
    result = json.loads(process.stdout)
    return result["answer"], result["record"]


def answer_question(db_path, question, model, seed=None, temperature=0, recovery_root=None, requalify=False):
    try:
        found = search(db_path, question, recovery_root=recovery_root)
    except (OSError, ValueError) as error:
        if recovery_root is None:
            raise
        result = {"task_id": str(uuid.uuid4()), "question": question, "status": "needs_review",
                  "reason": "invalid_source_recovery", "detail": str(error)}
        hive.append(db_path, result["task_id"], "cookie-reader", "knowledge_query", result)
        return result
    task_id = str(uuid.uuid4())
    result = {"task_id": task_id, "question": question, "model": model,
              "status": "not_found_in_source", "excluded_sources": found["excluded_sources"],
              "policy": "quote-support-v2", "seed": seed, "temperature": temperature,
              "scope": "Retrieved-source support only; not proof of real-world truth or exhaustive source coverage"}
    finding_reason = "no_retrieval_candidates"
    texts = [item["text"] for item in found["candidates"]]
    route = policy_slots.question_route(question)
    if version_comparison.applies(question) and version_comparison.product_for(question) is None:
        result.update(status="needs_review", reason="unclassified_minimum_version_question")
        hive.append(db_path, task_id, "cookie-reader", "knowledge_query", result)
        return result
    result["question_route"] = route
    if route == "review":
        result.update(status="needs_review", reason="unclassified_policy_question")
        hive.append(db_path, task_id, "cookie-reader", "knowledge_query", result)
        return result
    structured = route == "policy"
    slot = policy_slots.requested_slot(question) if structured else None
    if structured:
        result["requested_slot"] = slot
        if slot is None:
            result.update(status="needs_review", reason="unclassified_policy_question")
            hive.append(db_path, task_id, "cookie-reader", "knowledge_query", result)
            return result
    if found["candidates"]:
        context = {"question": question, "excerpts": [
            {"chunk_id": item["chunk_id"], "text": item["text"]} for item in found["candidates"]]}
        instruction = (
            "You are the solver cookie. Answer ONLY from the supplied excerpts. If they do not directly answer the question, "
            "return outcome='not_found_in_source' with answer, chunk_id and quote all empty. "
            "Otherwise return outcome='answered', the answer, the selected chunk_id, and a verbatim supporting quote of at most 400 characters. "
            + ANSWER_STYLE + question_guidance(question) + (POLICY_INSTRUCTION if policy_question(question) else "")
            + ' If the requested fact is absent, the complete response must be '
              '{"outcome":"not_found_in_source","answer":"","chunk_id":"","quote":""}. '
              'This is a successful search with no answer, not an answered result.')
        schema = status_fields({**ANSWER_FIELDS, "chunk_id": {"type": "string"}, "quote": {"type": "string"}}, question, texts)
        if structured:
            instruction = ("You are the solver cookie. " + policy_slots.INSTRUCTION + f" Requested slot: {slot}. "
                           "Return chunk_id and an exact quote containing the complete rule, including both condition and outcome. "
                           "For tables cite the complete table with headers. Limit quote to 400 characters. "
                           "For not_found_in_source leave quote and chunk_id empty.")
            schema = {**policy_slots.fields(texts), "chunk_id": {"type": "string"}, "quote": {"type": "string"}}
        with audit_session(db_path, task_id, "cookie-solver"):
            selection, record = ask(model, instruction, context, schema,
                seed=seed, temperature=temperature)
        solver_event_id = hive.append(db_path, task_id, "cookie-solver", "model_call", {**record, "context_sha256": hive.digest(context)})
        solver_policy = None
        if structured:
            solver_policy = selection
            hive.append(db_path, task_id, "cookie-solver", "policy_extraction", {"requested_slot": slot, "raw": solver_policy})
            if (not policy_slots.valid(solver_policy, slot) or
                    not all(type(solver_policy.get(k)) is str for k in ("quote", "chunk_id"))):
                result.update(status="needs_review", reason="invalid_policy_extraction")
                hive.append(db_path, task_id, "cookie-reader", "knowledge_query", result)
                return result
            selection = {"outcome": solver_policy["decision"], "answer": solver_policy[slot],
                         "chunk_id": solver_policy["chunk_id"], "quote": solver_policy["quote"]}
        if (not isinstance(selection, dict) or
                set(selection) != {"outcome", "answer", "chunk_id", "quote"} or
                not all(type(value) is str for value in selection.values())):
            result["status"] = "unsupported_output"
            hive.append(db_path, task_id, "cookie-solver", "malformed_source_proposal", {"raw": selection})
            hive.append(db_path, task_id, "cookie-reader", "knowledge_query", result)
            return result
        selected = next((item for item in found["candidates"] if item["chunk_id"] == selection["chunk_id"]), None)
        table = status_table(selected["text"]) if selected and structured else None
        if table and selection["outcome"] == "answered":
            # Cite the complete original table so the support cookie sees column
            # meanings; this adds source context, never the solver's answer.
            selection = {**selection, "quote": table["quote"]}
        hive.append(db_path, task_id, "cookie-solver", "source_proposal", selection)
        quote = selection["quote"]
        if not valid_answer(selection):
            result["status"] = "unsupported_output"
        elif selection["outcome"] == "not_found_in_source":
            finding_reason = "solver_not_found_in_source"
            if quote or selection["chunk_id"]:
                # An explicit abstention with an empty answer is still an
                # abstention. Keep raw metadata in the audit trail, never turn
                # it into an answer citation or evidence of universal absence.
                normalization_id = hive.append(db_path, task_id, "cookie-reader", "abstention_normalization", {
                    "discarded_fields": [field for field in ("chunk_id", "quote") if selection[field]],
                    "reason": "Citation metadata is not used as answer evidence for an explicit empty-answer abstention",
                    "raw_proposal_preserved": True,
                })
                result["normalization_id"] = normalization_id
        elif not selected or not quote.strip() or len(quote) > 400 or quote not in selected["text"]:
            result["status"] = "unsupported_output"
        else:
            checks = {"solver_answer_anchored": anchored(selection["answer"], quote)}
            if structured:
                checks["solver_value_in_requested_role"] = policy_slots.role_matches(selection["answer"], slot, quote)
                checks["solver_pair_in_same_rule"] = policy_slots.pair_matches(solver_policy, quote)
            relevance = None
            full_source = None
            # Separate process and fresh model request. No source metadata, answer,
            # candidate list, solver rationale or prior conversation is supplied.
            try:
                with audit_session(db_path, task_id, "cookie-support"):
                    support, record = support_review(question, quote, model, seed, temperature)
                support_context = {"question": question, "quote": quote}
                support_event_id = hive.append(db_path, task_id, "cookie-support", "model_call", {
                    **record, "context": support_context, "context_sha256": hive.digest(support_context)})
                if structured:
                    hive.append(db_path, task_id, "cookie-support", "policy_extraction", {"requested_slot": slot, "raw": support})
                    valid_policy = policy_slots.valid(support, slot)
                    checks["support_pair_in_same_rule"] = policy_slots.pair_matches(support, quote)
                    checks["support_value_in_requested_role"] = valid_policy and policy_slots.role_matches(support[slot], slot, quote)
                    # Binding sees the full fresh selected snapshot, not a solver-selected row.
                    if valid_policy and all(checks.values()):
                        full_source, full_hash = checked_source(selected)
                        if full_hash != selected["sha256"]:
                            checks["policy_relevance"] = False
                        else:
                            relevance = policy_relevance.assess(db_path, task_id, question, selected,
                                full_source, solver_policy, support, model, seed, temperature, requalify)
                            checks["policy_relevance"] = relevance["accepted"]
                            result["binding_path"] = relevance["path"]
                            result["binding_event_id"] = relevance["event_id"]
                    else:
                        checks["policy_relevance"] = False
                    support = {"outcome": support["decision"], "answer": support[slot]} if valid_policy else {}
                checks.update(
                    support_answered=valid_answer(support) and support["outcome"] == "answered",
                    support_answer_anchored=valid_answer(support) and anchored(support["answer"], quote),
                    answers_agree=valid_answer(support) and normalize_answer(support["answer"]) == normalize_answer(selection["answer"]),
                )
                if version_comparison.applies(question):
                    comparison = version_comparison.compare(question, quote, selection["answer"], support.get("answer", ""))
                    comparison.update(source_id=selected["source_id"], chunk_id=selected["chunk_id"],
                                      source_sha256=selected["sha256"], solver_event_id=solver_event_id,
                                      support_event_id=support_event_id)
                    comparison_id = hive.append(db_path, task_id, "cookie-support", "answer_comparison", comparison)
                    checks["answers_agree"] = comparison["verdict"] == "equivalent"
                    checks["minimum_constraint_supported"] = comparison["verdict"] == "equivalent"
                    result["comparison_id"] = comparison_id
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
                hive.append(db_path, task_id, "cookie-support", "support_error", {"error": str(error)})
                checks["support_completed"] = False
            hive.append(db_path, task_id, "cookie-support", "support_check", checks)
            result["checks"] = checks
            # Recheck after both model requests; the source can change during either.
            try:
                text, sha = checked_source(selected)
            except (OSError, ValueError):
                text, sha = "", None
            if sha != selected["sha256"]:
                result["status"] = "stale_source"
            elif not all(checks.values()):
                result["status"] = "needs_review"
            else:
                if relevance:
                    mapping_id = policy_relevance.finalize(db_path, task_id, question, selected, full_source, relevance, model)
                    if relevance["path"] in {"fallback", "promoted"}:
                        if mapping_id is None:
                            result.update(status="needs_review", reason="mapping_not_recorded")
                            lore.deliver(db_path, task_id, result)
                            return result
                        result["mapping_id"] = mapping_id
                    try:
                        _, final_hash = checked_source(selected)
                    except (OSError, ValueError):
                        final_hash = None
                    if final_hash != selected["sha256"]:
                        result.update(status="stale_source", reason="source_changed_during_lore_checks")
                        lore.deliver(db_path, task_id, result)
                        return result
                    condition = relevance["rule"]["condition"]
                    result["qualification"] = condition
                    result["qualified_answer"] = "Under the condition: " + condition + "; outcome: " + relevance["rule"]["outcome"]
                offset = selected["offset"] + selected["text"].index(quote)
                result.update(status="supported_answer", answer=selection["answer"], quote=quote, citation={
                    "source_id": selected["source_id"], "chunk_id": selected["chunk_id"],
                    "path": selected["path"], "sha256": sha,
                    "line": text.count("\n", 0, offset) + 1,
                    **({"original_path": selected["original_path"]} if "original_path" in selected else {}),
                })
    if result["status"] == "not_found_in_source":
        # A negative finding is a claim too. The support cookie receives all
        # retrieved evidence, not the solver's chosen/ignored quote or verdict.
        # Empty retrieval is not proof of absence and cannot produce a finding.
        checks = {"evidence_available": bool(found["candidates"])}
        confirmation_id = None
        if found["candidates"]:
            evidence = "\n\n".join(item["text"] for item in found["candidates"])
            try:
                with audit_session(db_path, task_id, "cookie-support"):
                    support, record = support_review(question, evidence, model, seed, temperature)
                support_context = {"question": question, "quote": evidence}
                confirmation_id = hive.append(db_path, task_id, "cookie-support", "model_call", {
                    **record, "purpose": "independent_answer_search", "context": support_context,
                    "context_sha256": hive.digest(support_context)})
                if structured:
                    hive.append(db_path, task_id, "cookie-support", "policy_extraction", {"requested_slot": slot, "raw": support})
                    support = {"outcome": support["decision"], "answer": support[slot]} if policy_slots.valid(support, slot) else {}
                checks["support_confirms_not_found"] = valid_answer(support) and support["outcome"] == "not_found_in_source"
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
                hive.append(db_path, task_id, "cookie-support", "support_error", {"error": str(error)})
                checks["support_completed"] = False
            fresh = True
            for item in found["candidates"]:
                try:
                    _, sha = checked_source(item)
                    fresh = fresh and sha == item["sha256"]
                except (OSError, ValueError):
                    fresh = False
            checks["evidence_still_current"] = fresh
        if structured:
            # Failure to bind a policy question is not evidence that its answer is absent.
            checks["policy_absence_classified"] = False
        result["absence_checks"] = checks
        if version_comparison.applies(question):
            # This narrow parser does not establish absence of a version constraint.
            # Preserve independent absence evidence but withhold an unsupported claim.
            checks["minimum_version_absence_classified"] = False
        check_id = hive.append(db_path, task_id, "cookie-support", "absence_check", {
            "checks": checks, "confirmation_id": confirmation_id})
        if all(checks.values()):
            result["finding_id"] = hive.append(db_path, task_id, "cookie-solver", "source_finding", {
                "finding": "not_found_in_source", "question": question, "reason": finding_reason,
                "searched_chunk_ids": [item["chunk_id"] for item in found["candidates"]],
                "excluded_sources": found["excluded_sources"],
                "confirmation_id": confirmation_id, "absence_check_id": check_id,
                "scope": "Both cookies found no answer in retrieved excerpts; not an exhaustive source or universal absence claim",
            })
        else:
            result["status"] = "needs_review"
    lore.deliver(db_path, task_id, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="knowledge.sqlite3")
    parser.add_argument("--recovery-root", help="Use only verified recreated source files under this directory")
    commands = parser.add_subparsers(dest="command", required=True)
    ingestion = commands.add_parser("ingest")
    ingestion.add_argument("source")
    commands.add_parser("findings")
    lookup = commands.add_parser("search")
    lookup.add_argument("question")
    query = commands.add_parser("ask")
    query.add_argument("question")
    query.add_argument("--model", required=True)
    query.add_argument("--seed", type=int)
    query.add_argument("--temperature", type=float, default=0)
    query.add_argument("--report", help="Optional JSON result file")
    args = parser.parse_args()
    if args.command == "ingest":
        result = ingest(args.db, args.source)
    elif args.command == "findings":
        result = lore.trusted_answers(args.db)
    elif args.command == "search":
        result = search(args.db, args.question, recovery_root=args.recovery_root)
    else:
        result = answer_question(args.db, args.question, args.model, args.seed, args.temperature, recovery_root=args.recovery_root)
        if args.report:
            Path(args.report).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if args.command != "ask":
        return 0
    return 0 if result["status"] in {"supported_answer", "not_found_in_source"} else (3 if result["status"] == "needs_review" else 2)


if __name__ == "__main__":
    sys.exit(main())
