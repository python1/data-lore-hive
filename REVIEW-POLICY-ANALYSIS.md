# Review-policy rejection: meaning before normalization

Question: **What happens when the model calculation disagrees?**

These are the answers saved in the original three-seed batch, before this follow-up made any changes:

| Seed | Solver | Support cookie |
|---|---|---|
| 11 | Source checks pass, but the model calculates a different total | the model calculates a different total |
| 29 | Source checks pass, but the model calculates a different total | the model calculates a different total |
| 47 | Source checks pass, but the model calculates a different total | needs_review |

## Meaning assessment

For seeds 11 and 29, the support answer drops the clause about source checks. The answers are compatible descriptions of the triggering condition, not contradictory factual claims. But neither answers the user's question about the consequence. The solver's quote contains only that condition, omitting the review status and withholding outcome. Treating the two strings as equivalent would approve a non-answer. This is not a safe wording-only normalization opportunity.

For seed 47, the solver again describes the condition, while the support cookie returns the resulting status. Those are different propositions: one states when a policy applies, the other states what it does. The quote in this trial includes the table row's `needs_review` status, which the support cookie correctly identifies.

The source's actual policy is: mark the result `needs_review` and withhold promotion. The original batch calls these false rejects at the task level because the question is answerable. At the candidate-answer level, withholding the solver's non-answer is appropriate. Loosening the comparison would trade these task-level misses for wrong accepted answers.

## Decision

No changes to solver prompts, support prompts, answer normalization, anchor checks or agreement rules. The corrective target is future answer selection: retrieve and quote the consequence, not merely the trigger. No yes/no, negation or number-format normalization was added because none explains this failure.

Only the evaluation runner gained an optional `--baseline` flag. It initializes a fresh database with the prior source ID and frozen source text, preserving chunk IDs so the solver's model-visible input is identical across runs. Each solver context hash is compared against the baseline. Previous queries are not copied into the new database.

Rerun command:

```bash
python3 evaluate_support.py --model gemma4:e4b --seeds 11 29 47 --temperature 0.2 --baseline support-seeded-0564edb2-adjudicated.json
```

Original records remain in `support-seeded-0564edb2-raw.json` and `support-seeded-0564edb2-adjudicated.json`. The original scoring correction recognizing “It does not provide peer replication” as a correct negative answer remains in effect; it does not change the runtime agreement gate.

## Unchanged-check rerun: 4c9252b8

| Seed | False accepts | False rejects | Correct answers | Not-found findings |
|---|---:|---:|---:|---:|
| 11 | 0 | 1 | 1 | 4 |
| 29 | 0 | 1 | 1 | 4 |
| 47 | 0 | 1 | 1 | 4 |
| Total | **0** | **3** | **3** | **12** |

All 18 trials completed, with no runtime or audit failures. All solver-input context checks matched the prior batch (15 matching model contexts and 3 matching no-call cases). The review-policy question remains withheld under each seed. This reproduces the unresolved task-level failure rather than claiming a normalization fix.

`support-meaning-rerun-4c9252b8.json` contains the new results, per-seed answer pairs, model records and preservation checks. SHA-256 checks confirm that the prior raw/adjudicated reports and all three production files (`knowledge.py`, `support_cookie.py`, `ollama_local.py`) are unchanged. No model retries were made within this rerun.
