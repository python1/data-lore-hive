# Source recovery: seeds 29 and 47 — 2026-09-27

The original SOURCE-RECOVERY.md run used seed 11 only. The same three questions were now run under seeds 29 and 47 with local gemma4:e4b, temperature 0.2, against the isolated recovered database and recreated source files. Original-path reads were blocked throughout. All six additional trials match seed 11 exactly in status and answer; no code or prompt changes were made.

| Seed | Policy question | Python version | Manufacturer |
|---|---|---|---|
| 11 (original record) | Supported: `needs_review` | Supported: `Python 3.10 or newer` | Confirmed not-found |
| 29 (new run) | Supported: `needs_review` | Supported: `Python 3.10 or newer` | Confirmed not-found |
| 47 (new run) | Supported: `needs_review` | Supported: `Python 3.10 or newer` | Confirmed not-found |

Across these records: 9/9 expected outcomes, six supported answers and three confirmed not-found findings. This is seeded regression coverage, not a general reliability estimate.

## Before source recreation

The original live drill recorded all three questions as `needs_review`, reason `invalid_source_recovery`, because the recovery directory/map did not exist. No answer was returned, no not-found finding was created, and no model was called. This was tested once before recreation; it is deterministic and was not repeated for the new seeds.

## Failure tests

All 12 source-recovery unit tests were rerun and passed. These are local failure-injection tests, not extra live model trials.

| Condition | Observed result |
|---|---|
| Corrupted latest snapshot text | Recovery raises `ValueError` for snapshot hash/content mismatch; no fallback to an older source version. |
| Deleted recovered file | Source excluded; zero retrieval candidates. Deletion during the absence-confirmation test returns `needs_review` and stores no negative finding. |
| Modified recovered file | Source excluded; zero retrieval candidates. Modification during the supported-answer test returns `stale_source` with no answer. Recovery over conflicting bytes refuses and leaves them unchanged. |
| Interrupted recovery | Injected interruption before manifest publication leaves no completed manifest. Retry verifies/reuses the files and succeeds. |

All earlier JSON records remain hash-identical. The primary database and the replica were not involved in these additional model queries; only the isolated recovery copy gained query events. Existing tags are unchanged.

Full traces, per-trial results, the executed procedure and verbose failure-test output: [source-recovery-seeds-29-47-2026-09-27.json](source-recovery-seeds-29-47-2026-09-27.json).
