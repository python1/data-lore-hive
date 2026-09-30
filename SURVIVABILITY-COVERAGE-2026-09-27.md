# Recovery coverage and live receiver tests — 2026-09-27

**Passed.** The actual primary now contains two supported answers and one independently confirmed not-found finding. After synchronization, it was deleted and restored from the replica. All source/evidence links and support records survived unchanged; all **81 unit tests passed** afterward. The emergency backup was not used.

## Findings stored and recovered

| Question | Stored result | After restore |
|---|---|---|
| What happens when the model calculation disagrees? | `supported_answer`: `needs_review` | Identical |
| What is the minimum Python version required? | `supported_answer`: `Python 3.10 or newer` | Identical |
| Who manufactured the reservoir? | Independently confirmed `not_found_in_source` | Identical |

These were real local `gemma4:e4b` calls on the primary database, seed 11, temperature 0.2. The current README was explicitly re-ingested because its stored snapshot predated its current contents. This appended a new source version without changing old snapshots, existing reports, prompts or acceptance checks. No evaluation databases or findings were imported.

Supported answers are stored as `knowledge_query` events with status `supported_answer`, not as separate `source_finding` events. Their citations point to the source ID/chunk/hash; support model-call and support-check events are associated by the same `run_id`. There is no direct support-event foreign key on a supported query. This existing association was resolved and verified before and after recovery.

The negative finding has explicit `confirmation_id` and `absence_check_id` references. The drill resolved both, verified the independent support abstention and all absence checks, reconstructed the searched excerpts from source snapshots, and matched them to the support context.

For all three results, the record includes query/task IDs, support/check event IDs, source IDs, chunk IDs, source hashes, and per-event hashes before and after recovery. Supported quotes and anchors were checked against the restored source text. No confirmation event was invented or relinked.

## Real replica receiver tests

| Candidate sent over restricted SSH | Result | Accepted state |
|---|---|---|
| Reordered events with a recomputed valid manifest/chain | Rejected | Unchanged |
| Modified event with a recomputed valid manifest/chain | Rejected | Unchanged |
| Deleted tail event with repaired sequence allocator and recomputed manifest/chain | Rejected | Unchanged |
| Genuine older 7-event snapshot (rollback) | Rejected | Unchanged |

All four failed at history-prefix validation with exit 1 and `History rewrite, deletion, or rollback`. Candidate files were altered copies, never the active primary. Valid manifests were checked locally before sending; the replica itself made every rejection. Its manifest, generation count and stored-byte count were read before and after every test and remained identical. A subsequent valid duplicate push returned `unchanged`.

## Full recovery drill

- Primary: `<repo>/knowledge.sqlite3`.
- No open database users were found by `lsof`. A separately retained emergency backup was created, but never used for restoration.
- The primary database and present SQLite sidecars were actually deleted; its absence was asserted before fetching the replacement from the replica.
- Restored **26 events and 4 source snapshots**, including the three requested results.
- Snapshot: **86,016 bytes**; SHA-256 `13911c3542a3f68ace538c9c21c42d0b5c45f0bb04b970742ec06bc962f8a025`.
- Complete event-chain head: `e51439da5b89dfbcd3902736f21c1933395cffd5f05c1dfe0196a73db4760f67`.
- Byte identity, full-history identity and every checked evidence/support association matched. All 81 unit tests passed after restoration.
- The replica retains **2 accepted generations**, occupying **144,049 bytes**. This is replica usage, not a free-disk measurement.

## Preservation and boundaries

All **39 pre-existing JSON records** remain byte-identical. The previous recovery report remains unchanged. No implementation code, receiver configuration, root keys, existing Git tags, model prompts or external source files were changed. Only the Mac primary and restricted replica receiver were involved; unrelated hosts were not accessed.

The source-file limitation is unchanged: restored source text lives in the database, but retrieval still excludes original files that are missing or changed. This drill proves survival of source-scoped findings and their existing associations; it does not establish real-world truth or exhaustive absence.

Complete machine-readable evidence, including the exact executed procedures: [survivability-coverage-2026-09-27.json](survivability-coverage-2026-09-27.json).
