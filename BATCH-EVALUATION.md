# Combined evaluation

Run from this directory with Ollama and the installed model available:

```bash
python3 evaluate_batch.py --model gemma4:e4b
```

Each batch uses fresh isolated databases and a snapshot of the actual README. It does not change `knowledge.sqlite3`, the original README, or prior reports. Cases run sequentially, sharing one local model runtime. There are no automatic retries or prompt adjustments after failures.

The batch runs all automated unit tests, then two live suites:

- **Arithmetic:** 120 × 7, 37 × 7, and 123 × 13, each with a correct and deliberately altered answer. Checks arithmetic, status, promotion and process exit code.
- **Source memory:** two answerable README questions, three unanswerable questions with overlapping source keywords (reservoir temperature, server IP, reservoir manufacturer), and one unanswerable question without keyword matches. The overlap cases must actually call the model; the no-match case must abstain without calling it.

Answerable source cases must return the expected factual content as an exact quote, with the correct source version, path, hash and line. Unanswerable cases must return `insufficient_evidence` without a quote or citation. Returning a real but irrelevant source quote is a failure, even if the production quote checker accepts it. Withholding malformed output is also recorded as a failure of the expected abstention behavior, rather than being counted as success.

Each invocation saves a progressively updated `summary.json` under a unique directory in `batch-evaluation/` (override with `--state-dir`). The report includes subprocess output, checks, retrieval candidates and model response events. It exits 0 only if both live suites and unit tests pass. The harness uses fixed expected phrases for its two positive cases; source wording changes may require updating those expectations explicitly.

These twelve cases are a regression sample, not a broad reliability benchmark. Exact source attribution does not establish real-world truth. The summary preserves failures for analysis; it does not modify the model or production verification policy.

## Recorded batch: 1d3dc0b9

`batch-validation-1d3dc0b9.json` contains the combined result and frozen source text. All 26 unit tests passed. Arithmetic passed 6/6 live cases; source memory passed 5/6. Of the four unanswerable questions, three abstained correctly (temperature, IP address, and the no-keyword question). The manufacturer question returned a real quote describing the learner cookie, which does not identify a manufacturer. This is a relevance/abstention failure, not an invented quotation. Overall the batch failed (11/12 live cases). There were no retries or production prompt changes.

The next issue to address is answer relevance: matching a quote to its source does not establish that the quote answers the question. Preserve this case as a regression when changing selection or review behavior.
