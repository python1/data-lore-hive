# Abstention formatting and non-answer agreement regression

Expected: `not_found_in_source` with empty answer and citation fields; observed: the same explicit abstention and empty answer, but with a quote and chunk ID, which the validator rejected.

## Agreement on a non-answer

The exact regression test did not previously exist. It was added as `test_both_cookies_agree_on_nonanswer_is_withheld` in `test_policy_tables.py`. With both cookies forced to answer “Calibration overdue” to “What happens when calibration is overdue?”, the first run failed: the old final gate accepted the anchored, matching condition.

The final gate now checks that each answer names an actual status in the recognized policy table's status column. The new test passes even though agreement and anchoring both pass; the answer is withheld as `needs_review`. This is defense in depth beyond the model's schema constraints. It is a specific regression for selecting the condition instead of the status, not a general guarantee against two models sharing an arbitrary semantic error.

## Prose holdout before abstention changes

The same fictional calibration/seal policy was rendered without a table:

> If calibration is overdue, the resulting status is inspection_required.
> If the seal is open, the resulting status is locked.

The question “What happens when calibration is overdue?” passed seeds **11, 29 and 47**, at temperature 0.2: both cookies answered `inspection_required`. The table parser was inactive. Source, quotes, model responses and citations are preserved in `prose-policy-validation-2147ce73.json`. This run completed before the abstention branch was changed.

## Format fix

Only a valid explicit solver abstention with an **empty answer** qualifies. Extra `quote` / `chunk_id` fields are ignored as answer evidence, while their exact contents remain in the original model-call and source-proposal events. A separate `abstention_normalization` event identifies the discarded fields. The query returns no answer or citation and records a scoped `source_finding`; successful abstention exits 0.

The source finding's searched chunk IDs come from actual retrieval, never from ignored model metadata. Invented metadata therefore cannot become a source citation. A nonempty answer combined with `not_found_in_source` remains invalid. Support-cookie abstention or disagreement remains `needs_review`, with no not-found finding substituted for it.

All **48 automated tests passed**, including the new non-answer regression, metadata preservation, fake-metadata exclusion, contradictory abstention rejection and preservation of support-review semantics. Historical evaluation reports remain unchanged.

## Live validation after the fix

`abstention-format-validation-b3acd7b3.json` preserves the repeated 12 policy trials under seeds 11/29/47:

- Six answerable trials returned correct supported answers.
- The three prior format failures now returned persisted `not_found_in_source` findings.
- Three manufacturer questions remained `needs_review` because the independent support cookie abstained; no answers were exposed.
- Zero false accepts, zero false rejects and zero runtime errors.

The evaluator still reports overall failure against its stricter expectation of six explicit not-found findings. That unresolved solver behavior is not masked by relabeling support-cookie abstention. The requested format defect is fixed; the distinction between solver not-found and independent support rejection remains intact.
