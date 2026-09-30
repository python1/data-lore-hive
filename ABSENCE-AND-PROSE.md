# Independent absence confirmation and the unfixed prose gap

## Negative findings now require support

An explicit solver abstention is a proposal, not sufficient evidence to record a not-found finding. Before writing a `source_finding`, the system gives the independent support cookie the question and **all retrieved excerpt text**, without the solver's answer, abstention verdict, or ignored citation metadata. The support cookie tries to answer normally; only a valid, empty-answer abstention confirms the proposed negative finding.

If support finds an answer, returns invalid output or fails, the result becomes `needs_review` with no finding. Retrieved source hashes are checked again after support runs; changed evidence also prevents a finding. Empty retrieval becomes `needs_review`: the absence of retrieval hits is not proof of source absence. No source-finding event is written on that path.

Confirmed findings link both the support response and the absence-check event, and name the searched chunks. Their scope remains **the retrieved excerpts**, not the entire file collection or the world. Raw unconfirmed solver responses and proposals remain audit history, not approved findings. Missing source coverage is still a limitation; same-model agreement is not proof of truth.

Tests cover an answerable question with malformed solver output, a false solver abstention overturned by support, invalid/failed confirmation, stale evidence, finding-to-confirmation links, and no-finding behavior on empty retrieval. All **53 automated tests passed**.

The live missing-temperature question also produced a linked negative finding only after both solver and support abstained. `absence-confirmation-validation.json` preserves the model events, finding/confirmation link and prior-record integrity checks.

## Live prose holdout rerun

`prose-current-validation-ab0af95d.json` records the updated-code run at seeds **11, 29 and 47**, temperature 0.2. All three live trials answered `inspection_required` correctly from prose. No table parser was active.

## Both cookies agree on a prose trigger: not caught

The new `diagnose_prose_nonanswer.py` regression forces both cookie responses to isolate the acceptance gate from sampling. It makes no live inference calls.

- Source: “If calibration is overdue, the resulting status is inspection_required.”
- Question: “What happens when calibration is overdue?”
- Solver answer: “calibration is overdue”
- Support answer: “calibration is overdue”
- Correct answer: `inspection_required`.

Observed result: **`supported_answer`**. Both anchoring and string agreement passed even though the answers merely restated the trigger. This is an **uncaught false accept in the controlled prose regression**. It has deliberately not been fixed, per the user's instruction. The observed failure is preserved in `prose-nonanswer-unfixed-e7a6c871.json`; the diagnostic exits 1 while the gap persists.

The table-specific non-answer regression still passes, but does not generalize to prose. The 53 passing automated tests must not be presented as an all-clear: this separately recorded negative diagnostic fails.

## Reproduce

```bash
python3 -m unittest -q
python3 evaluate_prose_policy.py
python3 diagnose_prose_nonanswer.py
```

The prose evaluator calls local Gemma. The diagnostic uses controlled responses. All prior JSON records are retained unchanged; new evaluations use separate output files and isolated databases.
