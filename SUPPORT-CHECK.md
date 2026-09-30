# Source answers with independent support

This supersedes the original source-excerpt workflow in README.md. Historical JSON reports and the original `batch-validation-1d3dc0b9.json` remain unchanged.

## Decision path

1. The solver receives the question and retrieved excerpts. It proposes an answer with an exact supporting quote, or explicitly returns `not_found_in_source`.
2. Code checks the quoted span against the selected source snapshot. Invented quotes are rejected before review.
3. A separate `support_cookie.py` process makes a fresh model request whose context contains **only the question and quote**. It receives no proposed answer, solver explanation, retrieved alternatives, source metadata or conversation history. It independently answers or abstains.
4. Deterministic checks require both answers to agree after case/whitespace/outer punctuation normalization. Every non-Boolean answer must occur as a bounded text span in the quote. This is stricter than anchoring only short names, numbers and dates; it intentionally does not accept unanchored paraphrases. Yes/No answers are checked through independent agreement, because a source can explicitly negate a claim without containing the word “No”.
5. Only passing answers are delivered. Support abstention, disagreement, an unanchored answer or a support-process failure produces `needs_review`, with answer, quote and citation withheld from the returned result. The proposal and review remain in the audit history. The source hash is checked again after support completes.

The support worker is context-isolated in a separate process, not an OS security sandbox. Both cookies use the same model and can share errors. Agreement and an authentic quote do not prove real-world truth. Conservative exact answer comparison may reject equivalent wording; these rejections must be reported rather than silently relaxed.

## Findings and statuses

| Status | Meaning | CLI exit |
|---|---|---|
| `supported_answer` | Answer, exact quote, citation, anchor and support checks passed | 0 |
| `not_found_in_source` | Solver abstained, or retrieval found no candidates; a separate `source_finding` event is saved | 0 |
| `needs_review` | Support or anchor checks failed; proposed answer withheld | 3 |
| `unsupported_output` | Solver output or quote violated the contract | 2 |
| `stale_source` | Source changed or became unavailable during evaluation | 2 |

A not-found finding records the question, reason and searched chunk IDs. Its scope is the retrieved excerpts, not proof that the entire collection or world lacks an answer. Retrieval uses only the top three keyword matches. A support cookie's abstention is a review case, not silently converted into a solver not-found finding.

```bash
python3 knowledge.py ask "Who manufactured the reservoir?" --model gemma4:e4b --seed 11 --temperature 0.2
python3 evaluate_support.py --model gemma4:e4b --seeds 11 29 47 --temperature 0.2
python3 -m unittest -v
```

## Seeded regression evaluation

The evaluator uses the exact source text embedded in the previous batch report, not an edited README. It runs the same two answerable questions and four unanswerable questions under each of three seeds, with one stable ingested snapshot. Each query runs in its own process; support runs as a further subprocess when a quote is proposed. There are no retries. The local model adapter records actual requested seed, temperature and generation limits for every call. The seeds use Ollama's [documented generation parameter](https://docs.ollama.com/modelfile#valid-parameters-and-values); temperature 0.2 permits sampling variation, but these are not independent model populations.

The report separates:

- **False accepts:** an answer delivered on an unanswerable case, or a delivered answer/citation that fails the frozen gold checks on an answerable case.
- **False rejects:** an answerable case with no delivered answer, including abstention, review, invalid output or runtime failure.
- **Wrong accepts on answerable cases:** reported separately as a subset of false accepts, not counted again as withheld false rejects.
- Not-found findings, review cases, runtime errors and audit failures.

Gold answers for the two positives are `needs_review` / `needs review`, and `No` or the exact source statement `It does not provide peer replication`. Citation checks also run. Three negative cases require model judgment despite keyword overlap; the fourth is a no-keyword retrieval abstention with no model call. These 18 cases do not measure the full accuracy of short-value anchoring: names, numbers and dates are additionally covered by deterministic tests.

The maximum model output is now 384 tokens; context remains 4,096 tokens. The arithmetic interface remains compatible. All completed query results, model calls and findings persist in each batch's isolated SQLite database, while summary JSON is saved after every case. The prior report's hash is checked after the run.

## Results: batch 0564edb2

| Seed | False accepts | False rejects | Correct answers delivered | Not-found findings |
|---|---:|---:|---:|---:|
| 11 | 0 | 1 | 1 | 4 |
| 29 | 0 | 1 | 1 | 4 |
| 47 | 0 | 1 | 1 | 4 |
| Total | **0** | **3** | **3** | **12** |

There were 6 answerable and 12 unanswerable trials. All 12 unanswerable trials produced persisted not-found findings: 9 used the solver; 3 had no retrieval candidates. All 3 replication-support answers were delivered correctly. The review-policy question was withheld at every seed. The solver answered with the condition (“Source checks pass, but the model calculates a different total”) rather than the resulting review status; the independent cookie returned a different answer. The disagreement gate therefore worked, but answer selection still needs improvement. The overall regression remains failed because of these false rejects. There were no runtime or audit failures and no model retries.

**Scoring correction:** The original automatic rubric allowed only “No” for the replication question. It incorrectly graded the exact negative source statement as a false accept. `support-seeded-0564edb2-raw.json` preserves those original scores and outputs. `support-seeded-0564edb2-adjudicated.json` documents the three scoring corrections, retains the raw metrics, and reports the counts above. No model outputs or withheld decisions changed. The rerunnable evaluator now allows that exact source statement as an equivalent gold answer.

The original failed batch report is unchanged, with SHA-256 `f092ab8414ce53594359d86b3f10f4a0f0d347c71714cf4879295d315c3a9efc`.

**Targeted historical replay:** In an additional test separate from the 18-case batch, the support cookie received the original manufacturer question and its exact irrelevant quote, with no solver answer. It abstained for all three seeds; see `historical-quote-support-replay.json`.

All 37 automated tests passed after final validation. Numeric anchors additionally reject partial matches such as 37 inside 137, -37, 37.5, or 37,500. This boundary tightening was checked against all recorded batch proposals and support answers without resampling the model.
