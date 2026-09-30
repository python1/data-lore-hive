# Source-file recovery — survivability step 2

Source recovery recreates the latest ingested version of each source from its stored UTF-8 text. It preserves source event IDs, chunk offsets, hashes and the append-only database history. It does not re-ingest sources, rewrite old paths in events, or silently use an older source version.

## Recreate and query

After restoring a database from the replica to an isolated directory, run these commands from the prototype directory (replace the example paths with the chosen recovery directory):

```bash
python3 source_recovery.py --db /path/to/recovery/knowledge.sqlite3 --root /path/to/recovery/recovered
python3 knowledge.py --db /path/to/recovery/knowledge.sqlite3 --recovery-root /path/to/recovery/recovered ask "What is the minimum Python version required?" --model gemma4:e4b --seed 11 --temperature 0.2
```

Files are placed at `<root>/sources/<source-event-id>/source.md` or `source.txt`, never at a stored absolute path. The stored text is encoded as UTF-8 without newline translation and hashed against the snapshot before writing. After atomic no-overwrite publication, actual file bytes are read back and hashed again. Only after the required files verify is `<root>/source-recovery.json` published.

The manifest maps existing source IDs to generated relative paths and records original-path provenance. Retrieval derives the expected complete mapping from the latest database snapshots and refuses a manifest with different IDs, paths, hashes, provenance or version. The manifest is a location map, not a replacement authority for source contents. Missing/invalid maps produce `needs_review` before inference. The explicit recovery mode never falls back to original files.

## Freshness is still enforced

Before retrieval and after inference, the recovered regular file is read from disk and its SHA-256 compared with the original snapshot hash. The same rule applies before a negative finding is stored. A missing, modified, oversized, nonregular or symlinked recovered file cannot pass. New citations contain the real recovered path plus `original_path`; original source and chunk IDs remain stable. Support sees the question and quoted text only, as before.

The reader walks generated directories using directory descriptors and no-follow opens. Only regular files are accepted. The format supports the existing `.md`/`.txt` UTF-8 sources with the existing 256,000-byte source limit. Manifest reads are limited to 1 MB. This implementation targets the current POSIX Mac/Linux environment.

## Existing paths and interruption

Identical existing regular files are verified and reused. Different content, directories and symlinks are refused without overwriting or deleting them. Final publication uses a hard link that fails if another process creates the destination first; that file must then verify as identical or recovery stops. File data and directories are fsynced.

If initial recovery is interrupted, already recreated files may remain, but there is no completed manifest. Retry verifies/reuses those files. An existing manifest for a different source set is never replaced: select a new recovery directory. If a previously completed file is later changed or removed, the manifest does not exempt it from freshness checks.

Original source files are neither recreated at their old locations nor altered. Older source snapshots remain in the database for historical evidence; only the latest version for each original source path is materialized for current queries. Changing the source set requires a fresh map.

## Live validation — 2026-09-27

A fresh database was fetched from the replica using only `hive-replica`. Its accepted SHA-256 was `13911c3542a3f68ace538c9c21c42d0b5c45f0bb04b970742ec06bc962f8a025`: 26 events and 4 historical source snapshots. The clean recovery directory initially contained no recreated sources.

To make the original Mac paths unusable without touching them, the entire live query drill replaced the ordinary source-path reader with a function that raises if called. The dedicated recovery reader still performed real filesystem reads and SHA-256 checks. This demonstrates no original-path fallback on the current Mac; it is not a separate-machine deployment test.

Before recreation all three questions returned `needs_review` without model calls. One latest README snapshot was then recreated under its unchanged source event ID, `34b686a2-8e9a-4aeb-a22b-cf1056115034`. Its actual file hash matched `9aeb5f6b2a22ac956025509b24a2836a72c22a87c0c120cbf5accadef345e564`.

With local `gemma4:e4b`, seed 11 and temperature 0.2:

| Question | Result after recreation |
|---|---|
| What happens when the model calculation disagrees? | `supported_answer`: `needs_review` |
| What is the minimum Python version required? | `supported_answer`: `Python 3.10 or newer` |
| Who manufactured the reservoir? | Independently confirmed `not_found_in_source` |

All three match the prior primary results. Historical rows remained exactly identical as the prefix of the restored database; new queries appended new events. New citations point to the recovered file with original-path provenance, and the support/evidence associations were resolved and checked. Supported queries use shared run IDs for support linkage; the negative finding retains explicit confirmation and absence-check IDs.

All **93 tests passed**: 81 existing plus 12 recovery tests covering exact bytes/newlines and history, latest-version selection, corrupt snapshots without older fallback, identical/conflicting files, symlinked files/directories, unexpected file types, manifest path escape, missing maps with originals still present, deleted/modified files, interrupted recovery, concurrent destination creation, and both positive and negative post-inference freshness checks.

The original primary database and the replica's accepted state remained unchanged. The replica is still storage-only; this drill did not upload the isolated copy's new query events. Existing tags and records remain unchanged. Do not push a recovered copy while the original primary remains an independent writer; promotion is a separate operational decision.

Complete evidence and the exact drill procedure: [source-recovery-validation-2026-09-27.json](source-recovery-validation-2026-09-27.json).
