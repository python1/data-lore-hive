# Policy answers with explicit condition and outcome

Policy cookies now return independent `condition` and `outcome` values, plus a `decision` (`answered` or `not_found_in_source`). The decision field is separate because `outcome` now means the policy's consequence, not the model's verdict. The solver also supplies a source quote and chunk ID. The support cookie still receives only the question and cited evidence, never the solver's extraction.

## Deterministic routing and acceptance

- Questions starting with “what happens” or “what is required” request **outcome**.
- Questions starting with “when” or “under what condition(s)” request **condition**.
- If retrieved policy content is recognized but its question cannot be classified, the result is `needs_review`.
- Only the requested field is selected as the answer. Both cookies must agree on that value, and it must be anchored to the quote.
- A deterministic source-role check also requires that value to appear in the requested role, not merely somewhere in the quote. This prevents two cookies from putting the same trigger in the outcome field and passing through agreement alone.

Policy structure is derived from named table columns (`Trigger`/`Condition`/`Meaning` versus `Status`/`Resulting status`/`Outcome`/`Action`/`Requirement`) and explicit prose rules of the form “If/When/Whenever condition, consequence”. “The resulting status is …” prose is interpreted as a status value. Field enums are derived from the source, never hardcoded to evaluation answers. Complete table context is retained for support review.

This is a narrow parser, not general natural-language semantics. In the policy path, a value with no recognized role mapping is withheld; synonym/negation inference is not used to loosen comparisons. However, some unsupported constructions can be partially parsed rather than cleanly rejected, as listed below. The models still select the applicable rule, so correlated errors remain possible. A correct field name alone is insufficient: the field value must pass the source-role check.

## Preserved non-answer regression

The old `prose-nonanswer-unfixed-e7a6c871.json` remains unchanged. Its exact source/question replay now returns `needs_review` because the legacy unstructured response cannot satisfy the policy contract. A stronger schema-compatible injection then made both cookies extract:

```json
{"decision":"answered","condition":"calibration is overdue","outcome":"calibration is overdue"}
```

That case is also caught: agreement and anchoring pass, but both requested-role checks fail. See `structured-prose-diagnostic.json`. The correct policy outcome remains `inspection_required`. This isolates structural validation from live-model sampling.

## Negative findings remain independently checked

A policy abstention leaves the requested slot empty. Before saving a negative finding, support independently searches the retrieved evidence using the same requested-slot semantics. If support finds a value, fails, or source freshness changes, no negative finding is recorded. Empty retrieval remains `needs_review`, consistent with the previous change. None of these findings proves absence outside the retrieved excerpts.

All 60 automated tests pass, including both requested slots, ambiguous policy questions, legacy/malformed extraction, direction of prose rules, matching wrong-role answers, source anchoring and negative-finding safeguards. Live seeded reports are saved separately; prior records are retained.

## Final seeded results

The saved runs were already complete when the task resumed; no duplicate live trials were needed. Every suite below ran seeds **11, 29 and 47**, temperature **0.2**, using local `gemma4:e4b`.

| Suite | Trials | Correct supported answers | Confirmed not-found | Needs review | False accepts | False rejects |
|---|---:|---:|---:|---:|---:|---:|
| Frozen table/source batch | 18 | 6 | 9 | 3 | 0 | 0 |
| Additional policy/not-found suite | 12 | 6 | 3 | 3 | 0 | 0 |
| Prose outcome holdout | 3 | 3 | 0 | 0 | 0 | 0 |
| Prose condition-slot checks | 3 | 3 | 0 | 0 | 0 | 0 |
| **Total** | **36** | **18** | **12** | **6** | **0** | **0** |

There were no runtime errors. False rejects here mean answerable trials with no delivered answer; reviews of unanswerable or unclassified questions are reported separately, not silently counted as correct not-found findings. These are finite regression samples, not a general accuracy guarantee.

The complete per-trial outputs, extraction records and source evidence are collected in [structured-policy-complete-record.json](structured-policy-complete-record.json). It embeds the four original suite reports and their hashes, while leaving those reports untouched. Integrity checks confirmed all 20 pre-existing JSON records tracked at the start of this change remained unchanged.

### Policy/not-found suite, all trials accounted for

| Seed | Overdue calibration | Open seal | Vibration trigger without outcome | Manufacturer question |
|---|---|---|---|---|
| 11 | `inspection_required` | `locked` | Confirmed not-found | `needs_review` |
| 29 | `inspection_required` | `locked` | Confirmed not-found | `needs_review` |
| 47 | `inspection_required` | `locked` | Confirmed not-found | `needs_review` |

The policy suite's original evaluator still reports **`failed`**, because it expected six explicit not-found findings. Actual behavior is three confirmed findings and three intended reviews. That strict coverage failure is preserved; zero false accepts/rejects does not mean every original expected status passed.

## Why manufacturer questions go to review

In the additional policy fixture, retrieval returns a recognized policy table. “Who manufactured the seal?” asks for an identity, not a condition or outcome. `requested_slot()` returns `None`, so the pipeline stops at `unclassified_policy_question` before either model is called. No independent absence confirmation has taken place, so recording a not-found finding would be unjustified.

This is **intended under the requirement that unclassifiable policy slots require review**. It is a deliberate coverage limitation, not a new false-accept problem. Compared with a generic reader that might investigate identity questions, it sacrifices automatic completion. In the same earlier policy holdout these manufacturer trials were already `needs_review`, but then the cause was the support cookie's abstention; the current routing reason is different. In the frozen README batch the manufacturer question still receives a confirmed not-found finding because its retrieved passages do not activate the structured-policy branch. Routing depends on the retrieved evidence, not only the question text.

## Unsupported phrasings and structures

The following observations describe the current implementation; the parser was not expanded while completing this report. Examples were checked directly and saved in [policy-parser-limitations-observed.json](policy-parser-limitations-observed.json).

**Questions not classified:** “What should happen …?”, “What must I do?”, “How should … be handled?”, “Why …?”, “Who manufactured …?”, “Explain this policy.” Recognized policy content with these questions goes to review. The classifier uses only the four supported prefixes, not semantic paraphrase recognition; mixed or multi-part requests are not reliably interpreted.

**Prose forms not recognized as rules:**

- Outcome-first: “Inspection is required if calibration is overdue.”
- Missing comma: “If calibration is overdue then inspection is required.”
- Alternative introducers: “Unless …”, “Provided that …”, “As soon as …”.
- Implicit or cross-referenced consequences: “Otherwise …”, “See the preceding rule”, or condition/action descriptions split across separate sentences without the supported pattern.
- Non-English equivalents of the supported introducers and question prefixes.

**Forms that can be parsed incorrectly or incompletely:**

- A comma inside a compound condition: “If calibration is overdue, or the seal is open, inspection is required.” The parser splits at the first comma and incorrectly includes part of the condition in the outcome.
- Multiple-sentence consequences: “If calibration is overdue, record the result. Then request inspection.” Only the first action is captured.
- Decimal points and abbreviations inside consequences: “If pressure rises, set the threshold to 37.5.” The parser truncates the outcome at the first period. Anchoring may reject the truncated value, but parsing itself is not correct.
- Nested conditions, exception precedence, Boolean equivalence, unit conversion and pronoun resolution are not interpreted. Wording may be copied without those semantics being understood.

**Table limits:** The parser expects pipe-delimited Markdown with an alignment row and recognized column names. Headers such as `Prerequisite` and `Effect`, HTML tables, merged cells, escaped pipes and wrapped/malformed rows are not supported reliably. Full-table quote expansion retains its 400-character limit; longer tables are not guaranteed to retain the headers needed for role checks.

A line break immediately after the condition's comma is accepted by the present regex; arbitrary line wrapping within a condition or consequence is not generally supported. Do not treat the narrow supported grammar as evidence that all other forms fail closed: partial parsing remains an explicit limitation.
