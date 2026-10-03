# Public release redactions

## Update 3: release-2 drill evidence (`evidence/release-2-drill/`)

This update publishes what is needed to verify the release-2 recovery-tested pin. **Signed and hashed files were copied byte-for-byte and never edited.** A file that failed the leak scan was withheld whole. No file was redacted.

- **Sources:** the signed release-2 approval directory on the main machine, and the drill evidence archive returned from the recovery machine. The archive's SHA-256 (`492cc9a1…aca690`) was checked before use. The pin manifest and signature were taken from the pin upload envelope and are byte-identical to the standalone signed files.
- **Published on purpose:** the release-signing **public** key (`allowed_signers`, identity `aster-hive`, fingerprint `SHA256:ZozTASM/tPWZPMpUaYnP5tYJsVWNbANnRnjjYkx5j4A`). Update 2 replaced this fingerprint with a placeholder. It is now public so that the signatures can be verified. `build_recovery_drill.py` keeps its placeholder constant.
- **Published unchanged:** the release-2 `manifest.json` and `manifest.sig`, `pin-manifest.json` and `pin-manifest.json.sig`, `run/evidence-index.json`, and the 28 indexed evidence files that passed the scan, each at its indexed path under `run/`.
- **Withheld by rule (271 files):** the Git bundle (`release/hive.bundle` and its identical download copy), the 261-file `recovered-code/` checkout, every SQLite file and the memory checkpoint stream, `known_hosts`, `baseline.json`, and the release phone receipt.
- **Withheld by the leak scan (18 files):** 16 command records, worker reports, trial records and event dumps contain the replica's LAN address, the recovery machine's account name, or home-directory paths. `release/evidence.json` and its download copy contain the main machine's macOS per-user temporary directory.
- **Leak scan patterns:** private IPv4 ranges; the usernames and hostnames listed in this file; `/Users/`, `/home/<name>`, `/root/` and Windows home paths; macOS per-user temporary directories; any SSH fingerprint other than the signing key's; SSH public-key blobs; and the update-1 identifiers (recovery machine brand, replica container ID, replica hostname, operator's first name, workspace name). A generic `/tmp/tmp…` sandbox path was not treated as a leak.
- **Known exception:** `run/evidence-index.json` is sealed and signed over, so it could not be edited. It lists the filenames of the withheld `recovered-code/` checkout, and some of those names contain the recovery machine's brand and the replica container ID, which update 1 removed from text. `VERIFY.md` and `withheld.json` repeat those paths together with their hashes. The index contains no IP addresses, usernames, home paths or fingerprints.

`withheld.json` lists each withheld path with its index hash and a generic reason. `verify_evidence.py` fails if any indexed file is neither present with a matching hash nor listed there.

## Update 2: signed code releases (private master `b1fd9d4`, tag `recovery-tested-pin-2026-10-03`)

The files added or changed in the private repository between `31dde0f` and `b1fd9d4bcaf6c6e83bd6db04cf858c2cb44c93d4` were exported with `git archive` and redacted under the same rules as the first release, extended as described below. Git history is still not included. The full offline suite now has 226 tests. On this tree 225 pass and 1 is skipped (see Code changes).

### Removed files (update 2)

**84 of the 114 new files were removed**, as were the private `PROJECT-STATE.md` changes (that file was already excluded):

- `signed-code-install-kit-2026-09-30/`, `-final-`, `-v3-`, `-v4-`: generated install kits (33 files). They contain embedded payloads, checksums and installer scripts for one specific replica host. `build_code_installer.py` regenerates an equivalent kit from the included sources.
- `recovery-drill-records-2026-10-02/` and `recovery-drill-records-2026-10-03/`: drill evidence (48 files). This covers the local rehearsal and Mac-off drill evidence, the baseline, the signed pin manifest and signature, the upload envelope, the phone receipt, the operator read-back and a live probe of the replica.
- `SIGNED-CODE-RECOVERY-HANDOFF.md` and `SIGNED-RECOVERY-DRILL-REVIEW.md`: operator runbooks. They contain key-creation and installation steps, kit checksums, key fingerprints, LAN addresses and home-directory paths. The trust model and the drill results they describe are summarised in the README.
- `signed-code-records-2026-10-02/release-1-operator-report.md`: an operator receipt containing a signing-key fingerprint.

No `allowed_signers`, `known_hosts`, public-key, receipt, `.sqlite3` or HiveSync configuration file is included. Code and tests that need these build throwaway fixtures at run time. The signing and host-key fingerprints hard-coded in `build_recovery_drill.py` were replaced with placeholders (see below).

### Placeholder substitutions (update 2)

These are applied in addition to the table further down:

| Original | Replacement |
|---|---|
| real release-signing key fingerprint | `<release-signing-key-fingerprint>` |
| real replica SSH host-key fingerprint | `<replica-host-key-fingerprint>` |
| replica LAN address in code and tests | `replica-host` (used as an SSH host name) |
| LAN gateway address passed to `sshd -T -C addr=` | `192.0.2.1` (RFC 5737 documentation address; `sshd -T` needs a literal IP) |
| replica hostname checked by the installer and rollback | `replica-host` |
| replica container ID in docstrings, messages and generated kit filenames | `replica CT`, `install-replica-ct-code.py`, `rollback-replica-ct-code.py` |
| recovery machine brand name | `recovery host` |
| repository path and macOS temporary directory in test logs | `<repo>`, `<tmpdir>` |

Kept on purpose: the code-level account names (`hive-recovery`, `hive-code-upload`, `hive-code-publisher`), the signed-manifest project identifier `aster-hive` (the engineering agent is credited by name in the README), and the release commit, manifest, checkpoint and model digests used as fixed drill criteria in `recovery_drill.py`. These identify content, not people or hosts.

### Code changes (update 2)

- `build_recovery_drill.py`: the `SIGNER` and `HOST` fingerprint constants are placeholders, and the expected known-hosts entry is `replica-host`. Generating a real baseline requires setting your own values. The tests patch these constants, as they did before redaction.
- `recovery_drill.py`: the SSH destination is `hive-recovery@replica-host`, and one message now says "recovery-host user".
- `install_code_publisher.py`, `rollback_code_publisher.py`: the hostname check is `replica-host`, the `sshd -T` probe address is `192.0.2.1`, and the docstrings and messages say "replica CT".
- `build_code_installer.py`, `test_code_recovery.py`: the generated installer and rollback filenames no longer contain the container ID.
- `test_recovery_drill.py`: the fixture known-hosts address is `replica-host`. `test_real_integrity_worker_restores_only_isolated_sources` clones this repository and checks out signed release 2's commit (`c8a784e…`). That commit exists only in the private history, so the test now skips when the commit is absent. Against the private repository it still runs and passes.
- `retention.py`, `sync_agent.py`: the upstream changes were applied unmodified on top of the first public release.

### Per-file substitution counts (update 2)

```
build_code_installer.py: ct-id-lc=3
build_recovery_drill.py: host-fp=1, ip-replica=1, signing-fp=1
install_code_publisher.py: ct-id=2, hostname=3, ip-gateway=1
recovery_drill.py: device=1, ip-replica=1
rollback_code_publisher.py: ct-id=2, hostname=1
signed-code-records-2026-09-30/*.txt (13 files): mac-tmpdir=17, repo-path=24
signed-code-records-2026-10-02/*.txt (2 files): mac-tmpdir=2, repo-path=4
test_code_recovery.py: ct-id-lc=2, hostname=1
test_recovery_drill.py: ip-replica=3
```

## First release (private master `31dde0f`)

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
