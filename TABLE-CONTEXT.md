# Policy-table context: selecting the outcome

The review-policy failure was an answer-selection error: the solver selected the trigger condition instead of the policy outcome. Anchor and agreement checks remain strict.

## What changed

For questions beginning with “What happens when”, `policy_tables.py` recognizes small Markdown tables with a `Status` or `Resulting status` column. It derives permitted status labels from that column and adds them, plus an empty abstention value, to the structured response schema. It does not hardcode `needs_review` or any other status. The model still has to choose the applicable row or abstain.

When the solver chooses a status from a recognized table, the source citation includes the full original table, including headers. This prevents the support cookie from seeing a condition stripped of its status or confusing a “No” in the promotion column with the answer. The raw model response and the subsequent source proposal remain separately recorded. The support process receives only question and quote; it independently derives allowed labels from that quote.

No changes were made to deterministic answer agreement or anchor checks. The Ollama adapter now also rejects returned strings outside source-derived enum constraints. Non-policy questions retain their earlier prompt behavior.

Scope is deliberately narrow: complete pipe-delimited Markdown tables, at most 400 characters, a single recognized status column, and well-formed rows. Other sources continue through the existing workflow. This is not a general solution to semantic equivalence, long-table retrieval or conflicting sources. Both cookies still share one model.

## Recorded attempts

1. **Preserved baseline:** `support-seeded-0564edb2-adjudicated.json` — 0 false accepts, 3 false rejects.
2. **Preserved unchanged rerun:** `support-meaning-rerun-4c9252b8.json` — reproduced the baseline.
3. **Failed prompt-only attempt:** `outcome-selection-attempt-1.json` — 2 false accepts and 4 false rejects. It confused the promotion-column “No” with a policy answer and introduced disagreement on the replication question. This approach was replaced, not counted as a successful run.
4. **Table-context version:** `table-context-validation-40eddada.json` — 18/18 trials succeeded: 6 correct answers and 12 recorded not-found findings, with **0 false accepts and 0 false rejects**. Seeds 11, 29 and 47, temperature 0.2, frozen original source and original source/chunk IDs. No runtime or audit failures.

All 44 automated tests passed. New tests cover reordered columns, unfamiliar status labels, malformed/oversized tables, full-table support context, persistent disagreement withholding, and enum enforcement.

Reproduce the main regression:

```bash
python3 evaluate_support.py --baseline support-seeded-0564edb2-adjudicated.json --seeds 11 29 47 --temperature 0.2
```

The original source-memory database and historical failure records are not overwritten by evaluations. Each run has isolated storage.

## Additional policy test

```bash
python3 evaluate_policy_holdout.py
```

This uses a new fictional policy with `inspection_required` and `locked` statuses, an outcome question for each, a vibration condition without a stated consequence, and an unspecified manufacturer. It runs all four questions under the same three seeds. These cases were defined before testing this table-context implementation on them. They are additional regression evidence, not a representative reliability benchmark.

Results are preserved in `policy-holdout-validation-7e145b8d.json`: **0 false accepts, 0 false rejects**, with all six answerable trials delivered correctly. All six unanswerable trials were withheld. However, the stricter expectation of explicit not-found findings failed: three trigger-only trials returned `not_found_in_source` with extra citation fields and were rejected as `unsupported_output`; the three manufacturer trials produced irrelevant candidate answers that the support cookie rejected, giving `needs_review`. No unsupported answer was delivered. The holdout's overall status is therefore failed, not an unconditional pass.

## Next work

Improve the solver's abstention contract while preserving the distinction between a solver not-found finding and a support disagreement. In particular, decide explicitly how to record harmless source metadata accompanying an abstention; do not silently turn a support rejection into a confirmed absence claim. Then expand evaluation to longer tables and multiple sources. Cross-machine deployment remains behind these reliability milestones.
