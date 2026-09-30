# Data & Lore: first hive experiment

Latest development: [table-aware answer selection and evaluation](TABLE-CONTEXT.md). The original 18-case source regression now has zero false accepts and zero false rejects. Additional policy tests reveal remaining abstention-contract issues; those results are preserved separately.

This runnable prototype tests one narrow idea: a cookie records a fact, a second cookie uses it, and a third checks the answer against its source. Each cookie runs in a separate Python process. Shared SQLite memory preserves the evidence and outcome between process lifetimes.

This is a local coordination experiment with a scripted mode and an optional Ollama model mode. It is not a distributed deployment. Requires Python 3.10 or newer. The scripted mode needs no services, packages, weights, or network connections.

## Run

From this folder:

```bash
python3 hive.py demo
python3 hive.py demo --inject-error
python3 -m unittest -v
```

To use a locally installed Gemma model via Ollama:

```bash
python3 hive.py demo --model gemma4:e4b
python3 hive.py demo --model gemma4:e4b --inject-error
```

Ollama must be running at `127.0.0.1:11434`. Each worker makes its own model request: extraction, problem solving, and source review. Workers run sequentially and share one model runtime; these are separate roles, not three model copies or independent intelligences. The adapter uses Ollama's [chat API](https://docs.ollama.com/api/chat) with structured JSON output. The deterministic source and arithmetic checks still gate promotion even if the model incorrectly approves a result.

No model is downloaded. Requests bypass proxy settings and target only the loopback endpoint. The arithmetic demo sends synthetic fixture/task data; the source-memory commands below send excerpts from files you explicitly ingest. Each request caps context at 4,096 tokens and output at 384 tokens with a 180-second HTTP timeout, and requests a one-minute keep-alive. These settings bound individual calls, not system-wide CPU/GPU or power consumption. Model call records include the returned JSON, model name, context hash and reported timing/token counts. Invalid responses and network failures stop the run; they do not silently fall back to scripted answers. Failed runs may leave partial events and no final report.

The scripted demo produces **360 litres — verified**. Its fault-injection demo produces **361 litres — disputed** and exits with code 2 intentionally. Model runs can also require review. Each run writes a unique source fixture and JSON report plus a persistent `memory.sqlite3` into `state/`. Use `--state-dir /path/to/folder` to choose another location. Use `--capacity 37 --count 7` to change both the synthetic source and question.

## Verification policy v2

A live test of the original verifier returned `valid: false` while explaining that the correct 840-litre answer was valid. That failure is preserved in `seven-reservoir-test.json`; the earlier `gemma-validation.json` also describes the old policy.

The revised verifier receives only the original source and reservoir count. It does **not** see the solver's answer, rationale or fault-injection flag. It returns one integer, `expected_total_litres`, instead of a Boolean and prose explanation. Code compares that independent model calculation with the proposed answer and deterministic source calculation. This removes the contradictory Boolean/prose interface; it does not make the model infallible.

| Status | Meaning | Promotion | CLI exit |
|---|---|---|---|
| `verified` | All source checks pass; the model calculation agrees when enabled | Yes | 0 |
| `disputed` | A deterministic evidence or arithmetic check failed | No | 2 |
| `needs_review` | Source checks pass, but the model calculates a different total | No | 3 |

`needs_review` is a recorded state, not an automatic human-review queue. Model/network failures still abort without promotion. This policy is specific to exact arithmetic from a structured fixture; it does not settle open-ended factual disagreements or interpret contradictory natural-language reasoning. All workers still use the same model and share its potential weaknesses.

Run the repeatable six-case evaluation:

```bash
python3 evaluate.py
python3 evaluate.py --model gemma4:e4b
```

It tests 120 × 7, 37 × 7, and 123 × 13, each with a normal and deliberately altered answer. Each invocation creates a fresh directory containing every run and a progressively saved `summary.json`, including failures. A case passes only if the answer, promotion behavior, status, and process exit code match expectations. The evaluation exits 1 if any case fails. Six cases are a regression sample, not a reliability benchmark.

The saved `verifier-v2-validation.json` records a successful live run using `gemma4:e4b`: all six cases passed, including the previous 840-litre regression. All 16 automated tests also passed. The earlier failure reports remain unchanged.

## What the cookies share

1. **Learner:** reads a synthetic reservoir specification, stores its source URI, content hash and snapshot, then records an explicitly unverified capacity claim.
2. **Solver:** retrieves that claim from memory and uses it to answer a new question. It does not read the source file.
3. **Verifier:** reads the original source and checks evidence links, source consistency, the claim and arithmetic. In model mode it also obtains an independent calculation. It records verification, dispute, or a need for review, then a scoped observation in lore. Only a passing answer becomes working knowledge.

The source contains a fictional 120-litre reservoir. Verification demonstrates agreement with that fixture, not real-world truth. Lore here is a record of what happened during the experiment, not a universal rule.

## Memory semantics and limits

Events are append-only through SQLite triggers: verification adds an event rather than rewriting an earlier claim. Run IDs isolate experiments. Original disputed results remain inspectable. The database owner can bypass the triggers; these are an application guardrail, not cryptographic identity or protection against hostile hosts. Hashes detect changes relative to a stored snapshot; they do not establish source trust.

The arithmetic demo uses one local database, exact retrieval by event type, a fixed task sequence, and trusted processes. The source-memory workflow adds keyword retrieval and document versioning across tasks. It does not provide peer replication, semantic search, model training, authentication, independent real-world corroboration, automatic retries, resource quotas, or general conflict resolution. Separate verifier code checks the source independently of the solver's arithmetic, but all workers share this implementation and trust domain. Source-memory ingestion can supersede document snapshots, but it does not automatically revise earlier arithmetic conclusions or resolve conflicting sources.

Workers exit after their task. No idle daemon remains. Power use has not been measured.

## Source memory across tasks

`knowledge.py` adds persistent ingestion of local `.txt` and `.md` files. It stores their UTF-8 text, paths and SHA-256 hashes in append-only events. Separate process invocations can query the same database without repeating ingestion or relying on model conversation history.

```bash
python3 knowledge.py ingest README.md
python3 knowledge.py search "What happens when the model calculation disagrees?"
python3 knowledge.py ask "What happens when the model calculation disagrees?" --model gemma4:e4b
python3 knowledge.py ask "Does this project support peer replication?" --model gemma4:e4b
```

The default database is `knowledge.sqlite3`. To choose a shared database path, put `--db /path/to/memory.sqlite3` before the subcommand. `ask` also accepts `--report result.json` to save its output. The database's parent directory must already exist.

Retrieval ranks paragraphs by keyword overlap and sends the top three excerpts to the local solver. The solver now returns an answer with an exact quote or an explicit not-found finding. A separate support-cookie process receives only the question and quote and must independently answer or abstain. Deterministic anchor checks and agreement checks gate delivery. See [SUPPORT-CHECK.md](SUPPORT-CHECK.md) for the full policy, three-seed evaluation, and remaining false rejects.

| Query status | Meaning |
|---|---|
| `supported_answer` | Exact quote, source freshness, answer anchor and independent support passed |
| `not_found_in_source` | No answer found in retrieved excerpts; persisted as a finding, CLI exit 0 |
| `needs_review` | Support abstained/disagreed/failed or an anchor failed; answer withheld |
| `unsupported_output` | Solver output or quotation violated the contract |
| `stale_source` | The selected source changed or became unreadable during inference |

The old `source_excerpt` and `insufficient_evidence` statuses remain in historical reports. Current results use the statuses above. Source truth is not independently established, and open-ended synthesized claims are not promoted into verified working knowledge.

Changed/missing sources detected before inference are excluded and listed under `excluded_sources`. Re-run `ingest` after editing a source to make a new version available; previous snapshots remain in history. Unchanged repeat ingestion is deduplicated. Only the latest ingested version of each file participates in new queries, and the original file must remain accessible for freshness checks. These checks capture file state at the check time, not a guarantee against subsequent edits.

Ingestion is explicit and limited to 256,000 bytes per file; there is no folder crawling, PDF parsing, web fetching, semantic search, or external communication. Keyword retrieval can miss relevant evidence. Conflicting documents are not reconciled, and identical quotes can be misleading out of context. Source text is treated as data and never executed. This is a trusted local prototype, not an authenticated multi-user memory service. Each completed query gets its own task ID and stored result event; model/network errors stop the query and may leave partial history.

## Next implementation boundary

Next, expand retrieval and review for real source material, then choose a second participating machine. Move task delivery to an authenticated queue and memory access to a service rather than sharing SQLite over a network filesystem. Opt-in hosts should enforce resource limits locally. Cross-host replication and Eureka Protocol integration require current repository and deployment details before implementation.

## Current checkpoint

See [CHECKPOINT.md](CHECKPOINT.md) for the current routing behavior, measured results and known limits. Earlier sections and validation records remain as project history.
