# Survivability step 1 — 2026-09-27

**Passed.** The Mac primary was pushed to the replica, then deleted locally and restored exclusively from the restricted replica account. The emergency backup was not used. All **81 unit tests** passed after recovery (63 existing plus 18 replication tests).

## Actual scope and result

- Primary: `<repo>/knowledge.sqlite3`.
- Replica: `hive-replica@<replica-ip>` on the replica (`replica-host`).
- Restored: **7 events, 3 full source snapshots, 57,344 database bytes**. This primary currently contains no `source_finding` events. Evaluation findings/databases were not imported or replicated.
- Snapshot SHA-256: `80b30334eaf574fc135441cd6e3b145ea27ba12c766b2c600916bce6034e02e4`.
- Event-chain head: `830f000c6ac3192359742cf38aab4d8c5d79979fafb738444ff80002a068ac6a`.
- The complete event-row digest, embedded source hashes, manifest and byte digest matched before/after recovery. The original active database and its WAL/SHM files were actually removed during the drill. `lsof` found no open users before deletion.
- The replica currently has **one accepted generation**, using **57,720 bytes** including its manifest and current pointer. Identical retries do not add generations.

## Verification

Local tests cover valid extension, duplicate retries, three-generation retention after five accepts, interrupted transfers/publication, corruption, trailing bytes, modified/reordered/deleted history even with recomputed manifests, sequence gaps, wrong identity, invalid source hashes, rollback, disk budget/free-space reserve, corrupted retained history, missing current pointer, exact expected-checkpoint restore and command rejection.

Live checks against the replica confirmed a duplicate push leaves one generation, shell/arbitrary commands are refused, and truncated/corrupt uploads leave the accepted state unchanged. A separate rehearsal fetch was byte-identical before the actual deletion drill. Three-generation pruning and injected publication crashes were tested locally, not by inserting synthetic events into the production primary.

After restricted push and fetch succeeded, the exact `setup-hive-replica` key was removed from root's authorized keys. A fresh attempt using only that key was rejected for root; the same key still works for the forced-command replica account. Other root authorized-key entries were preserved. Password login, PTYs, user SSH RC, and agent/network forwarding are disabled for the replica account. The installed receiver's SHA-256 matches the tested local code.

No packages were installed. The replica uses its existing Python 3/SQLite and systemd-managed SSH service. No model, Ollama, new daemon, timer or nohup process was installed. No access or changes were made to unrelated hosts.

## Setup issues retained in the record

The initial `systemctl reload ssh` failed with `Cannot bind any address`. The existing systemd socket activated a fresh SSH service on the next connection. SSH became active, the effective restricted-account configuration was checked, and subsequent tests passed. This did not require changing host networking or IPv6 settings. Future SSH maintenance should account for socket activation rather than assuming a reload will work.

One automatic approval review timed out before the remote-verification command ran. Its permitted single retry succeeded. Neither issue is hidden from the evidence record.

## Operations and limits

See [SURVIVABILITY.md](SURVIVABILITY.md) for commands, retention and recovery boundaries. Synchronization is manual. The replica keeps the latest three accepted generations, with a 2 GiB storage budget including staging, a 1 GiB free-space reserve and a 512 MiB per-snapshot cap. It refuses transfers that do not fit without deleting accepted generations first.

Full source text survives inside memory, but restoration does not recreate external source paths or bypass freshness checks. Recovery proves stored bytes/history survive; it does not prove claims are true or test a live finding that this small production database does not contain. The replica is not an automatic failover node or an independently authenticated ledger against root compromise.

All pre-existing JSON records and existing Git tags remain unchanged. New implementation/evidence lives on `survivability-step-1`; the baseline code is `1d6caf0`. The dedicated private key, runtime configuration, primary database, scratch files and emergency backup are outside Git tracking.

Complete evidence was recorded in `survivability-step-1-2026-09-27.json`. That file is a live SSH transcript and is not included in this public release (see REDACTIONS.md).
