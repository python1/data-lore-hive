# Public release redactions

This tree was exported with `git archive` from master commit `31dde0f580282f0751141421ee45a8fb82e2551c` of the private repository. Git history is not included. After export, operator records for private machines were removed, and private identifiers in the remaining files were replaced with placeholders. Code behaviour is unchanged apart from the three edits listed under Code changes. The full offline test suite (182 tests) passes after redaction.

## Removed files

**47 files were removed.** They were deployment transcripts, runbooks, recovery sheets, launchd plists, and installers or validators tied to specific private hosts. Between them they contained root SSH session logs, host and key fingerprints, LAN addresses and home-directory paths. The protocol they exercised is still described in SURVIVABILITY.md, SOURCE-RECOVERY.md, CROSS-MACHINE-RECOVERY.md and the SURVIVABILITY-* reports. Where a remaining document cites one of these files, it now notes that the file is not included.

## Placeholder substitutions (text files, applied everywhere)

| Original | Replacement |
|---|---|
| absolute path of the private repository | `<repo>` |
| absolute path of the private workspace | `<workspace>` |
| agent / macOS temporary directories | `<agent-tmp>`, `<tmpdir>` |
| user home directory and username | `~`, `<user>` |
| home directory on the recovery machine | `/home/<user>` |
| private LAN IPv4 addresses (replica, second host, gateway) | `<replica-ip>`, `<lan-ip>`, `<lan-gateway>` |
| SSH host-key and recovery-key fingerprints | `<replica-host-key-fingerprint>`, `<recovery-key-fingerprint>` |
| replica hostname and container ID | `replica-host`, `replica CT` / `replica_ct` |
| hypervisor and unrelated container IDs | `hypervisor`, `unrelated host(s)` |
| recovery machine brand/name | `recovery host` |
| operator's first name | `the operator` |
| names of other assistants the operator works with; a key label derived from one | `another agent`, `setup-hive` |

Evaluation JSON records were changed only by these substitutions and were not otherwise edited. Several of them contain maps from filename to implementation hash, and some of the files named in those maps were removed or renamed. Hashes of files that did change will no longer match the published bytes.

## Code changes

- `install_mac_sync.py`: the default key filename is now `replica_ct_ed25519`. The old name contained the container ID.
- `sync_agent.py`, `recovery_server.py`, `cross_machine_recovery.py`, `test_version_comparison.py`: text in one docstring, comment or message per file (container ID / machine name). Logic is unchanged.
- `evaluate_batch.py`: now snapshots `PROTOTYPE-NOTES.md` instead of `README.md`. The original README was renamed so that a new public README could take its place. The evaluation questions target the original text.
- `PROTOTYPE-NOTES.md` (the original README): "the Gemma model installed on this MacBook" became "a locally installed Gemma model via Ollama".

## Readability pass

Where mechanical substitutions left awkward sentences in the Markdown reports, those sentences were rewritten. The replica is now called "the replica" and the second machine "the recovery machine". Three documents gained a note saying that a cited file is not included. No results, counts, hashes or verdicts were changed.

## Deliberately kept

- `127.0.0.1` (Ollama loopback endpoint).
- Model names and digests (`gemma4:e4b`, `qwen3.5:4b`) and one local model alias, `zoro:latest`, which appears in a recorded Ollama model listing and a test fixture.
- Git commit and tag hashes, database and snapshot SHA-256 values, and the Ollama package checksum. These identify content, not people or hosts.
- Generic system paths such as `/etc/hive-replica/...` and `/var/lib/hive-replica/...`, which describe the receiver design.

## Per-file substitution counts

```
CROSS-MACHINE-RECOVERY.md: ct-id=11, ct-id-lc=7, device=12, host-fp=1, hostname=2, ip-lan=2, ip-replica=4, other-hosts=1, workspace-path=1
POLICY-RELEVANCE-SAFETY.md: ct-id=1
POLICY-ROW-CONSISTENCY-2026-09-28.md: device=1
PRIMARY-POLICY-PAIR-AUDIT-2026-09-28.json: repo-path=1
SOURCE-RECOVERY-SEEDS-2026-09-27.md: ct-id=1
SOURCE-RECOVERY.md: ct-id=4
STRUCTURED-COMPARISON-PLAN.md: device=2, person=2
STRUCTURED-COMPARISON-RESULTS-2026-09-28.md: ct-id=2, device=5, person=1
SURVIVABILITY-COVERAGE-2026-09-27.md: ct-id=6, other-hosts=1, repo-path=1
SURVIVABILITY-RESULTS-2026-09-27.md: agent-name=1, ct-id=6, ct-id-lc=1, hostname=1, ip-replica=1, other-hosts=1, repo-path=1
SURVIVABILITY-STEP4-ASSESSMENT-2026-09-28.md: ct-id=4, device=5, person=7, win-home=1
SURVIVABILITY.md: ct-id=5, hostname=1, ip-replica=1, other-hosts=1, repo-path=1
abstention-format-validation-b3acd7b3.json: workspace-path=12
batch-validation-1d3dc0b9.json: workspace-path=31
condition-slot-validation.json: workspace-path=6
cross_machine_recovery.py: ct-id=1
gemma-validation.json: workspace-path=2
install_mac_sync.py: ct-id-lc=1
outcome-selection-attempt-1.json: workspace-path=51
policy-holdout-validation-7e145b8d.json: workspace-path=12
prose-current-validation-ab0af95d.json: workspace-path=6
prose-nonanswer-unfixed-e7a6c871.json: workspace-path=2
prose-policy-validation-2147ce73.json: workspace-path=6
question-routing-attempt-1.json: workspace-path=12
question-routing-attempt-2.json: workspace-path=12
question-routing-attempt-3.json: workspace-path=12
question-routing-attempt-4.json: workspace-path=12
question-routing-final.json: workspace-path=12
recovery_server.py: ct-id=1
rerun-2026-09-26-measurements.json: agent-tmp=4
rerun-2026-09-26-prose-c05d54e7.json: agent-tmp=6
rerun-2026-09-26-prose-unplanned-246ffdb1.json: repo-path=6
rerun-2026-09-26-table-source-2adf1acc.json: agent-tmp=63
safety-records-2026-09-30/live-30.json: ct-id-lc=6, repo-path=6, workspace-path=18
safety-records-2026-09-30/master-unit-tests.txt: repo-path=4
safety-records-2026-09-30/traps.json: workspace-path=5
safety-records-2026-09-30/unit-tests.txt: repo-path=4
seven-reservoir-test.json: workspace-path=2
source-memory-query-1.json: repo-path=1
source-memory-query-2.json: repo-path=1
source-memory-validation.json: repo-path=2
source-recovery-seeds-29-47-2026-09-27.json: repo-path=8, workspace-path=10
source-recovery-validation-2026-09-27.json: repo-path=17, workspace-path=11
structured-comparison-records-2026-09-28/after.json: ct-id-lc=6, repo-path=12, workspace-path=30
structured-comparison-records-2026-09-28/before.json: ct-id-lc=6, repo-path=12, workspace-path=30
structured-comparison-records-2026-09-28/mutations-initial.json: repo-path=15
structured-comparison-records-2026-09-28/mutations.json: repo-path=14
structured-comparison-records-2026-09-28/policy-relevance-after.json: mac-tmpdir=1
structured-comparison-records-2026-09-28/policy-relevance-before.json: mac-tmpdir=1
structured-comparison-records-2026-09-28/regression-before.txt: repo-path=1
structured-comparison-records-2026-09-28/reported-pair-before.txt: repo-path=1
structured-policy-complete-record.json: workspace-path=87
structured-policy-notfound-8f814944.json: workspace-path=12
structured-prose-validation-baaeb1ee.json: workspace-path=6
structured-table-validation-4a0208d6.json: workspace-path=63
support-meaning-rerun-4c9252b8.json: workspace-path=54
support-seeded-0564edb2-adjudicated.json: workspace-path=54
support-seeded-0564edb2-raw.json: workspace-path=54
survivability-coverage-2026-09-27.json: ct-id=1, repo-path=6
sync_agent.py: ct-id=1
table-context-validation-40eddada.json: workspace-path=63
test_version_comparison.py: device=1
verifier-v2-validation.json: workspace-path=6
```
