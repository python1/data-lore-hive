# Hive prototype: evidence-gated answers from small local models

A research prototype that asks a small local LLM questions about local documents and **only releases an answer when independent checks agree with the source**. Otherwise it withholds the answer and records why. Everything is append-only and kept as evidence, including failures.

It runs on a single machine with the Python standard library. The optional model mode uses [Ollama](https://ollama.com) on loopback. There are no third-party Python dependencies.

> **Status:** prototype. The measurements below are small, fixed-seed regression runs on one model family. They are not a reliability benchmark. See [Stated limits](#stated-limits) before relying on any of this.

## What it does

The unit of work is a **cookie**: a short-lived worker process with a single role. Cookies never share conversation state. They communicate only through an append-only SQLite event log.

1. **Learner / ingest** stores a source document's text, path and SHA-256 as an immutable snapshot.
2. **Solver** gets keyword-retrieved excerpts and must return either an answer with an **exact quote** or an explicit *not found*.
3. **Support cookie** is a separate process that sees only the question and the quote, never the solver's answer. It must independently answer or abstain.
4. **Deterministic gates** release the answer only when all of these hold:
   - the quote exists verbatim in a snapshot
   - the source file still hashes to that snapshot (freshness)
   - the answer is anchored in the quote
   - solver and support agree
   - for policy tables, condition and outcome come from the *same row*
   - every model response matched a strict JSON schema

   A failure in any gate withholds the answer. The system never falls back to a probabilistic override.
5. **Not found** is not trusted on the solver's word. Absence must be confirmed independently before it is stored as a finding.

Query outcomes: `supported_answer`, `not_found_in_source`, `needs_review` (answer withheld), `unsupported_output`, and `stale_source`.

Survivability work adds one-way replication of the event log to a storage-only replica, tiered retention, and verified restore. It also adds recreation of source files from stored snapshots, so a second machine can answer from a recovered checkpoint while the primary is offline.

Signed code releases extend this to the code itself. Every new master commit is backed up to the replica as an unsigned candidate, but only a release signed with a human-held key can become the approved version. A second signature, the **recovery-tested pin**, marks a release that has actually been recovered and run on another machine with the primary switched off.

[`agent-memory/`](agent-memory/README.md) is a separate, self-contained pipeline. It turns your own Telegram JSON chat export into cited memory for your local agent: secrets are masked, a model proposes dated records in two attributed voices, code verifies every quote word for word, a second model audits each record, and you approve what is exported.

## Architecture

```
            ┌───────────── append-only SQLite event log (triggers block UPDATE/DELETE) ─────────────┐
 ingest ──► │ source snapshots · claims · model calls (raw bytes) · verdicts · findings · lore      │
            └──────▲────────────────▲────────────────────▲─────────────────────▲──────────────────┘
                   │                │                    │                     │
             solver cookie    support cookie     relevance cookie      deterministic gates
            (excerpts only)  (question+quote)   (snapshot, no answer)  (quote/hash/anchor/row)
                   └──── each a separate process; same local model via ollama_local.py ────┘

 replication.py ──(SSH forced-command, push/fetch/status only)──► storage-only replica ─► retention.py
 source_recovery.py / cross_machine_recovery.py: restore DB + recreate sources on another host
 code_sync.py ──(upload-only SSH account)──► code_publisher.py on replica: unsigned candidates, signed releases, signed pin
 recovery_drill.py (other host, primary off): verify signed release ─► restore memory ─► tests + model trials ─► sealed evidence
```

| Module | Role |
|---|---|
| `hive.py` | Event store, the three-cookie arithmetic demo, and verdict policy (`verified` / `disputed` / `needs_review`) |
| `knowledge.py` | Source ingest, keyword retrieval, the `ask` pipeline, freshness checks, findings |
| `support_cookie.py`, `relevance_cookie.py` | Independent second-opinion requests with deliberately restricted context |
| `policy_tables.py`, `policy_slots.py`, `policy_binding.py`, `policy_relevance.py` | Narrow parser for policy tables and If/When prose, plus conservative binding of a question to a rule |
| `version_comparison.py` | Structured, fail-closed comparison for minimum-version questions |
| `lore.py` | Snapshot-bound interpretation records with list/inspect/revoke/affected. **Promotion to authority is disabled** (`EXPERIMENTAL_PROMOTION = False`) |
| `ollama_local.py`, `ollama_preflight.py` | Loopback-only Ollama adapter with bounded context, output and timeout, plus schema/version preflight |
| `replication.py`, `retention.py`, `sync_agent.py`, `recovery_server.py` | One-way snapshot replication with hash-chained manifests, receiver-side retention, macOS launchd sync and watchdog, and a read-only recovery endpoint |
| `source_recovery.py`, `cross_machine_recovery.py` | Recreate sources from snapshots without trusting stored paths, and drive a recovery drill |
| `code_release.py`, `code_builder.py`, `code_publisher.py`, `code_transport.py`, `code_sync.py` | Signed code releases: Git-bundle candidates, `ssh-keygen -Y` signed manifests with monotonic sequence numbers, a publisher service on the replica, a restricted upload/read transport, and the sync hook that backs up each new master commit |
| `install_code_publisher.py`, `build_code_installer.py`, `rollback_code_publisher.py`, `prepare_mac_code_sync.py` | One-time publisher installer and its rollback (both refuse to run on any host not named `replica-host`), plus staging of the client-side update. None of them installs anything when imported or tested |
| `build_recovery_drill.py`, `recovery_drill.py`, `recovery_drill_worker.py` | Recovery drill for signed releases: a frozen baseline, a runner that checks tool hashes before importing anything, and a worker that runs only from the verified checkout. It produces a sealed evidence index that a pin can be signed over |
| `evaluate*.py`, `measure_rerun.py`, `replay_policy_measurement.py` | Evaluators. Each run goes to a fresh directory and saves all results, including failures. Replay re-scores preserved model bytes offline |

## Running it

Requires Python 3.10 or newer. The test suite has been run on 3.14.

```bash
python3 -m unittest discover          # full offline suite, no model or network needed
python3 hive.py demo                  # scripted: "360 litres — verified", exit 0
python3 hive.py demo --inject-error   # scripted: "361 litres — disputed", exit 2 (intentional)
```

Model mode needs Ollama running at `127.0.0.1:11434` with a model already pulled. Nothing is downloaded by this code.

```bash
python3 hive.py demo --model gemma4:e4b
python3 knowledge.py --db mem.sqlite3 ingest PROTOTYPE-NOTES.md
python3 knowledge.py --db mem.sqlite3 ask "What happens when the model calculation disagrees?" --model gemma4:e4b --seed 11 --temperature 0.2
python3 evaluate.py --model gemma4:e4b
```

Demo state is written to `state/` unless you pass `--state-dir`. Databases are git-ignored.

Replication and recovery (`replication.py`, `install_mac_sync.py`, `sync_agent.py`) expect a client config and an SSH key that you provide, and a receiver host that you set up. The signed-code modules additionally need your own release-signing key, an `allowed_signers` file and a pinned replica host key; none are shipped. The host-specific memory-replica installers used in the original deployment, the generated signed-code install kits, and all drill evidence are **not** included; see [REDACTIONS.md](REDACTIONS.md). [SURVIVABILITY.md](SURVIVABILITY.md) and [SOURCE-RECOVERY.md](SOURCE-RECOVERY.md) describe the protocol and its checks.

## Measured results

Setup for these runs:

- Model: `gemma4:e4b` on Ollama 0.32.14
- Seeds: 11, 29 and 47, at temperature 0.2
- Hardware: 16 GB Apple M1 Pro

**Latest production configuration (2026-09-30)**, from [POLICY-RELEVANCE-SAFETY.md](POLICY-RELEVANCE-SAFETY.md) with raw responses in `safety-records-2026-09-30/`:

| Suite | Trials | Correct / answerable | Confirmed not-found | Withheld | False accepts | Errors |
|---|---:|---:|---:|---:|---:|---:|
| Policy table | 18 | 3/6 | 9 | 6 | 0 | 0 |
| Prose | 3 | 3/3 | 0 | 0 | 0 | 0 |
| Recovery drill questions | 9 | 3/6 | 3 | 3 | 0 | 0 |

- **Availability was traded for safety, deliberately.** The previous configuration answered 6/6 table and 6/6 drill questions. Tightening relevance binding makes six answerable paraphrased questions abstain. Three other table cases get no retrieval candidates.
- **Separate binding probes:** 18 live probes gave 0 false accepts and 0 errors. The deterministic path bound 6/6 answerable questions; the model fallback bound 3/6. All 14 scripted gate cases behaved as expected.
- **Injected correlated errors do get through.** When the same wrong judgment is injected into both model calls, the gates pass it: 1 false accept on the fallback path and 1 on the (disabled) promotion path. These are intentional demonstrations, not observed rates.
- **Cross-machine recovery drill:** a second machine restored a byte-identical 26-event checkpoint from the replica with the primary powered off. It then answered 7 of 9 questions correctly, with 0 false accepts, and withheld 2. Under its pre-registered 9/9 criterion the drill is recorded as **FAILED**. See [SURVIVABILITY-STEP4-ASSESSMENT-2026-09-28.md](SURVIVABILITY-STEP4-ASSESSMENT-2026-09-28.md). Parts of that drill rest on operator reports rather than artifacts inspected here, and the document says which.
- **Signed release 2 recovery drill (2026-10-03):** with the main machine off, the recovery machine fetched signed release 2 and the 26-event memory checkpoint from the replica, verified the release signature, bundle and commit before running any of its code, and restored the memory. Integrity checks and the final pristine-memory check passed. The recovered release ran its own suite: **212/212 tests passed**. The nine fixed model trials gave **6 correct** (3 answers, 3 confirmed absences), **3 abstentions**, **0 false accepts** and **0 errors**. All three abstentions were the same question across the three seeds. That met every pin-eligibility gate but missed the 9/9 quality target. The operator then signed a recovery-tested pin over the SHA-256 of the sealed evidence index. The replica accepted it as pin sequence 1 for release 2 and read it back unchanged. The main machine being off is the operator's statement, not something that was measured. The upload and read-back were also run by the operator. The signed release manifest, the signed pin, the public signing key, the sealed evidence index and the 28 indexed evidence files that passed a leak scan are published in [`evidence/release-2-drill/`](evidence/release-2-drill/VERIFY.md), so you can check the signatures and hash chain yourself.

**Earlier milestones.** These used different code and fixtures, so they are not directly comparable:

- The first verifier returned `valid: false` while its explanation said the answer was valid (`seven-reservoir-test.json`). That led to verifier v2, which passed all 6 cases (`verifier-v2-validation.json`).
- Question routing took four failed attempts (`question-routing-attempt-{1..4}.json`) before reaching 6 correct, 6 confirmed not-found and 0 false accepts on a 12-trial suite (`question-routing-final.json`, [CHECKPOINT.md](CHECKPOINT.md)).

### Evaluation records included

Every JSON record in the repo root and in `*-records-*/` is an unedited run output. The only changes are redactions of private identifiers (see REDACTIONS.md). Failed and superseded runs are kept on purpose:

- `seven-reservoir-test.json`: contradictory Boolean-vs-prose verifier output
- `question-routing-attempt-1..4.json`: failed routing attempts before the final one
- `prose-nonanswer-unfixed-*.json`: a controlled **false accept**. Answers that only restated the trigger passed both anchoring and agreement. The record is kept unfixed; the current code withholds on replay
- `outcome-selection-attempt-1.json`: a failed prompt-only fix, with **2 false accepts and 4 false rejects**
- `policy-parser-limitations-observed.json`: parser failure cases
- `structured-comparison-records-2026-09-28/`: before/after raw records, mutation tests and diagnostics
- `safety-records-2026-09-30/`: the latest 30-trial live run, traps and verification
- `evidence/release-2-drill/`: signed release-2 and pin manifests, the sealed drill evidence index, the publishable subset of the drill evidence, and `verify_evidence.py`. [VERIFY.md](evidence/release-2-drill/VERIFY.md) explains the checks and lists every withheld file with its index hash
- `signed-code-records-2026-09-30/`, `signed-code-records-2026-10-02/`: offline test-suite logs from developing signed releases, including failing runs. Installer runs in these logs are sandbox emulation

The dated Markdown reports explain each run. [PROTOTYPE-NOTES.md](PROTOTYPE-NOTES.md) is the original project README. It is kept because evaluators ingest it as a test source.

## Stated limits

### Deliberate, and not on the roadmap

**Withholding beats answering.** Every gate fails closed. A correct answer that cannot be tied to one quote, one fresh snapshot and one table row is withheld, not released with a caveat. That cost is measured and accepted. In the latest table suite, 3 of 6 answerable questions were withheld. Making paraphrases work without weakening the gates is open work.

**No learned authority.** The lore/promotion lifecycle exists but is switched off (`EXPERIMENTAL_PROMOTION = False`), and there is no CLI or environment switch to turn it on. A mapping that a model judged relevant once does not become a shortcut for later answers. Revoking a mapping flags past answers that depended on it but cannot undo what was done with them. The lifecycle is exercised only in synthetic tests.

### Not built, and you should not assume it works

**Correlated model errors.** Solver, support and relevance cookies are separate *processes*. They are not independent *judges*: all of them run on the same model, so a shared blind spot passes every model-based gate. The injected-error controls show exactly this (1 fallback false accept and 1 promoted-path false accept). Zero false accepts in the live runs is a statement about those runs, not a rate. The deterministic gates (quote, hash, anchor, same row) are the real safety margin, and they prove an answer is *grounded*, not that it is *relevant*. A second model family was tried and is not merged, because its first live confirmation failed.

**Narrow parser.** Policy parsing handles specific Markdown table headers and `If/When/Whenever …, …` clauses. It does not handle exceptions, outcome-first prose, cross-references, compound conditions or multi-sentence consequences, and may parse them only partially. Question routing relies on English prefixes and keyword heuristics, and cannot tell "when did X happen" apart from a policy condition. Retrieval ranks paragraphs by keyword overlap and uses the top three, so it can miss evidence. "Not found" means not found *in the retrieved excerpts*. Full table quotes are capped at 400 characters.

**Prototype scale.** Sources are single `.txt`/`.md` files of at most 256 KB, with no crawling. Everything runs on one machine, against one SQLite file, with trusted local processes. There is no authentication, no multi-writer support and no task queue. Each result table comes from tens of trials with three seeds on one 4B-class model, which makes it a regression sample, not a benchmark. The append-only triggers are an application guardrail and do not protect against a hostile host. Hashes detect change, but they do not establish that a source is true.

**Signatures approve, they do not verify.** A signed release or pin means the key holder approved that exact commit and evidence hash. It does not mean the code is bug-free, and it does not make test logs produced on the main machine independently true. The offline verifier tracks the highest release sequence it has seen. It cannot detect a replica that hides a release newer than the operator's last saved receipt. Rotating or revoking keys is manual operator work, and sync can never change which keys are trusted. You can check the release-2 drill yourself with [`evidence/release-2-drill/VERIFY.md`](evidence/release-2-drill/VERIFY.md). It covers both signatures, the pin's links to the release manifest and the evidence index, and the hash of every published evidence file. You cannot check the code itself, because the release bundle is private. 289 of the 317 indexed evidence files are withheld, including the raw model trials, the integrity report and the release's `evidence.json`; only their hashes are public. The main machine being off is the operator's statement. The public key is published next to the signatures it verifies, so compare its fingerprint with an independent copy if you have one. **This public repository itself has no signed tags or signed release artifacts.**

**No security audit.** Nobody but the people credited below has reviewed this. Some tests emit nonfatal SQLite `ResourceWarning`s.

## Repository layout

The Python code and tests are at the top level, except for the self-contained [`agent-memory/`](agent-memory/README.md) folder. The design and results documents are the upper-case `.md` files, and records are the `.json` files plus the `*-records-*/` folders. Each record is kept alongside the report that describes it.

## Credits

- Built by Pawel.
- Engineering by Aster (GPT-6 Astra).
- Project lead: Claude Opus 5.5.
- Runs on Gemma 4 e4b (`gemma4:e4b`) via Ollama.

## License

MIT. See [LICENSE](LICENSE).
