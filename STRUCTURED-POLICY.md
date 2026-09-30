# Policy answers with explicit condition and outcome

Policy cookies now return independent `condition` and `outcome` values, plus a `decision` (`answered` or `not_found_in_source`). The decision field is separate because `outcome` now means the policy's consequence, not the model's verdict. The solver also supplies a source quote and chunk ID. The support cookie still receives only the question and cited evidence, never the solver's extraction.

## Deterministic routing and acceptance

- Questions starting with “what happens” or “what is required” request **outcome**.
- Questions starting with “when” or “under what condition(s)” request **condition**.
- Routing depends on the question, never the presence of a policy table. Identity/location/selection questions (`who`, `whose`, `where`, `which`), quantity questions (`how many/much`), `what is/are/was/were`, and supported yes/no prefixes use the general source path. Existing short keyword lookups remain general. Other forms go to `needs_review`.
- Both cookies use the same deterministic router. General not-found findings still require independent support confirmation against all retrieved excerpts.
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

All 63 automated tests pass, including both requested slots, ambiguous policy questions, legacy/malformed extraction, direction of prose rules, matching wrong-role answers, source anchoring and negative-finding safeguards. Live seeded reports are saved separately; prior records are retained.

## Question-routing checkpoint: current result

The current 12-trial run uses seeds **11/29/47**, temperature **0.2**, and `gemma4:e4b`: **6 correct supported answers, 6 confirmed not-found findings, 0 needs-review results, 0 false accepts, 0 false rejects, 0 runtime errors**. All 63 unit tests pass. The requested target is met. Each seed delivers `inspection_required` and `locked`, and confirms no answer for the vibration consequence and manufacturer questions.

Manufacturer questions now take the general path in both cookies. The complete run verifies independent support absence confirmation for all six negative findings, with question and retrieved evidence as its only context. Malformed outputs are not converted into negative findings.

Routing alone did not meet the target. Four complete failed attempts are preserved:

1. `question-routing-attempt-1.json`: routing only; 6 correct, 3 confirmed not-found, 1 needs review, 2 unsupported outputs.
2. `question-routing-attempt-2.json`: identity guidance; 6 correct, 3 confirmed not-found, 3 reviews.
3. `question-routing-attempt-3.json`: general verdict enum; same counts.
4. `question-routing-attempt-4.json`: explicit solver abstention JSON; same counts, but the cause changed. Solver abstained correctly; support incorrectly answered with a policy trigger when checking the full evidence.

The final change supplies a complete valid abstention JSON example to **both** general cookies. No acceptance or absence-confirmation safeguard was loosened. [Current full record](question-routing-final.json) contains all 12 trials and model traces. [Integrity audit](question-routing-audit.json) records current code hashes and all 28 earlier JSON records, unchanged. The previous documentation is preserved as `STRUCTURED-POLICY-before-question-routing.md`.

The earlier prose/table suites below were not rerun during this routing change; they are historical evidence, not new validation of the modified general prompts. Repeated tuning on this fixture is not a fresh holdout or general accuracy guarantee.

## Previous seeded results (preserved baseline)

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

## Previous manufacturer routing and its correction

The previous router activated policy slots whenever retrieved content contained a recognized policy rule. That sent identity questions to review before either cookie ran. This was conservative but reduced coverage: the question itself does not ask for a policy role.

The current router sends “Who manufactured the seal?” through general source checking regardless of the source layout. A confirmed not-found finding requires the solver to abstain and support to independently confirm absence in retrieved evidence. If support supplies an answer, the result stays `needs_review`. Unclassifiable questions also stay in review. Identity questions receive an explicit actor/name instruction in both cookies, and the general verdict schema constrains the model to `answered` or `not_found_in_source`. Malformed answered non-answers are still withheld, never converted into negative findings. The earlier failed 12-trial record and its explanation are retained in `structured-policy-notfound-8f814944.json` and `STRUCTURED-POLICY-before-question-routing.md`.

## Unsupported phrasings and structures

The following observations describe the current implementation; the parser was not expanded while completing this report. Examples were checked directly and saved in [policy-parser-limitations-observed.json](policy-parser-limitations-observed.json).

**Questions not classified:** “What should happen …?”, “What must I do?”, “How should … be handled?”, “Why …?”, “Explain this policy.” These go to review; manufacturer questions now use general checking. The classifier recognizes prefixes, not semantic paraphrases. `when` is treated as a condition request, so event-date “when” questions are not disambiguated. Mixed or multi-part requests are not reliably interpreted. Short keyword lookups (one to four word/hyphen tokens, excluding unsupported question/directive prefixes) retain their existing general route; this is a compatibility heuristic, not intent understanding.

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
