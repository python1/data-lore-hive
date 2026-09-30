# Survivability step 1: storage-only replica

The MacBook is the only writer. The replica (`replica-host`, `<replica-ip>`) receives consistent SQLite snapshots over SSH. It never runs a model or sends updates back to the primary. Recovery is a separate Mac-initiated fetch.

## Scope and identity

The only primary database is:

`<repo>/knowledge.sqlite3`

Its complete `events` table is replicated, including raw payloads, source text and hashes, model-call history, verification links, and any findings. Unverified or failed events retain their original status. No event is promoted, interpreted as an instruction, or rewritten by replication. The initial production database contains 7 events and 3 source snapshots; it has no `source_finding` events. Evaluation databases and all evaluation state directories are excluded. Their existing reports remain in Git, not in the replica.

The client configuration and dedicated private key are outside the repository, in `../../work/replication/`. The database identity is pinned in both the local configuration and the root-owned replica configuration. Do not generate a new identity when resuming or restoring.

## Consistent export and fail-closed acceptance

`replication.py snapshot` uses SQLite's backup API, so committed WAL data is included. Exported snapshots use DELETE journal mode and are self-contained. The primary is not modified by export. The manifest records the snapshot SHA-256, size, pinned identity, event count, sequence bounds, embedded-source count, and a SHA-256 chain over every raw event field in sequence order.

The receiver independently checks SQLite integrity, the supported schema and append-only triggers, contiguous event sequences, unique event IDs, source hashes, manifest contents and the exact previous event prefix. Every accepted event must still be present and unchanged. A modified/deleted/reordered history, shorter history, wrong identity, corrupt retained generation, bad source hash or malformed transfer is rejected. An identical logical history returns `unchanged` and consumes no generation.

A filesystem lock serializes uploads and fetches. Transfers are staged privately, with a five-minute receiver deadline and bounded lengths. Complete validated generation directories and the current pointer are published with atomic renames and fsync. A failed or interrupted upload leaves the last accepted pointer unchanged. Incomplete staging is discarded on the next push. A complete generation left by a publication crash can be reused on a matching retry; conflicting pending history fails closed. A missing current pointer with existing generations requires operator investigation; it never silently reinitializes the history.

## Retention and disk limits

The replica stores generations at:

`/var/lib/hive-replica/generations/<snapshot-sha256>/knowledge.sqlite3`

Each directory also contains its manifest. The latest **three distinct accepted generations** are retained. Only after a new generation is durably published does the receiver remove generations beyond that count. Each retained snapshot contains the complete history, not an incremental fragment.

The storage budget is **2 GiB including staging**, with a **1 GiB free-space reserve** and a **512 MiB maximum individual snapshot**. The receiver checks available space before writing and again before publication. If a transfer cannot fit without deleting accepted generations first, it refuses it. The receiver does not delete accepted generations after a failed sync. These application limits are not a filesystem quota against unrelated root activity.

## Replica runtime and access

No packages beyond the already installed Python 3, its SQLite support, and OpenSSH are required. The receiver imports only Python's standard library. It runs on demand through the existing systemd-managed SSH service; there is no additional daemon, timer, nohup process, model, or Ollama installation.

Root owns `/usr/local/lib/hive-replica/replication.py`, `/etc/hive-replica/config.json`, `/etc/hive-replica/authorized_keys`, and the SSH Match configuration at `/etc/ssh/sshd_config.d/60-hive-replica.conf`. The `hive-replica` account owns only its replica store. The key is restricted to `push`, `fetch`, and `status`; shell commands, password authentication, PTYs, user SSH RC, agent forwarding and network forwarding are disabled. SSH host verification remains strict.

The setup key is removed from root's authorized keys after restricted transfer and recovery are verified. No changes to unrelated hosts are part of this implementation. Future privileged maintenance on the replica must use the operator's independent administration route, not the replica key.

## Manual operation from the prototype directory

Choose a NEW package directory for each export; exports never overwrite old packages.

```bash
python3 replication.py snapshot --config ../../work/replication/client.json --package ../../work/replication/sync-next
python3 replication.py push --config ../../work/replication/client.json --package ../../work/replication/sync-next
python3 replication.py status --config ../../work/replication/client.json
```

Keep the accepted manifest locally as the expected recovery checkpoint. If an unchanged push acknowledges a previously accepted byte snapshot with the same logical event history, use the manifest returned by the receiver, not a newly exported physical snapshot's manifest.

Restore requires an absent destination and no associated SQLite journal files. It verifies the downloaded snapshot against the independently retained expected manifest and publishes without overwriting any existing file:

```bash
python3 replication.py restore --config ../../work/replication/client.json --destination ../../work/replication/recovered.sqlite3 --expected-manifest ../../work/replication/initial-snapshot/manifest.json
```

This command restores into a separate file; it does not delete active memory. Any live replacement requires a maintenance window with all writers stopped, a verified final sync, and an independent emergency backup. Unit tests create their own temporary databases and do not validate a restored production database by themselves: compare its full event chain, counts, embedded source hashes and snapshot bytes separately.

## Recovery boundary and limits

The database contains complete ingested source text, not merely paths and hashes. Those source versions survive database restoration. External source files are not recreated, and normal retrieval still checks the original paths for freshness. If those files are unavailable or changed, retrieval continues to withhold them. Exporting a stored source snapshot is a separate action and must not overwrite a newer file silently.

This is manual one-way replication, not automatic failover, multi-writer synchronization or a distributed inference system. The first transfer establishes trust in the existing history. Hashes and SSH detect corruption and unexpected history changes; they do not prove the truth of claims, protect against a compromised primary that appends plausible false events, or provide independent authenticity if an attacker controls both the replica and its expected manifests. A lost expected manifest needs explicit recovery review. A failed sync leaves the replica at its previous accepted checkpoint, so unsynced events remain at risk.

The current format intentionally rejects schema evolution and sequence gaps. Changing it requires a versioned migration. Current records and tags must remain untouched.
