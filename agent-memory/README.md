# agent-memory: cited memory from your own Telegram export

A small local pipeline that turns **your own** Telegram JSON chat export with your AI agent into memory the agent can use. Every record is a short, dated statement in one of two attributed voices, backed by quotes that code has checked word for word against the original messages. A second model audits each record, and you approve what goes in.

It uses only the Python standard library (3.10+). The model can be the Claude Code CLI or a local Ollama model. The offline tests run without either.

> **Status:** prototype, adapted from a private run of the same design. Only the code is published here. No data, outputs or measurements from that run are included (see [REDACTIONS.md](../REDACTIONS.md#update-4-agent-memory-agent-memory)).

## Pipeline

```
Telegram result.json ─► inventory (metadata only, SHA-256 of the export)
        │
        ▼
  secret masking ──► second detection pass; anything left over stops the call
        │
        ▼
  propose (model A, per day-window × voice)      ┐ the model sees masked text only:
        │                                        │ speaker name, date, message ID
        ▼                                        ┘
  quote verification (code, no repair) ──► rejected with a reason, or cited by offset + hash
        │
        ▼
  audit (model B, independent) ──► any failed flag excludes the record
        │
        ▼
  review.json ──► you approve / reject (line by line, or bulk, labelled as such)
        │
        ▼
  export: MEMORY.md · README.md (for the agent) · records.jsonl · SHA256SUMS
        │
        ▼
  search (plain text over records.jsonl, after checking SHA256SUMS)
```

**Two voices.** You pick the human's and the agent's Telegram sender IDs. Records about the human are third-person statements that begin with their name. Records from the agent stay in its own first person ("I…", "My…"). A record may only cite its own voice's messages. Merging, deduplication and supersession never cross voices.

**Quote verification.** A quote must be a contiguous, exact substring of the original message, of the masked text the model was shown, and of a message visible in that window. It must not overlap a masked secret. Whitespace, case, spelling and ellipses are never repaired; a near-miss is rejected. Citations store the message ID, UTC time, character offsets and the SHA-256 of the message text. At export every approved record is checked again against the original export, so editing a statement or quote in `review.json` makes the export refuse.

**Old instructions are history.** The prompts ask for past requests to be recorded as dated events. The exported memory and its README tell the agent that quoted instructions are data and grant no permission now. Every quote is rendered in a fenced block, never as live Markdown.

**Fail-closed.** A model call that fails, times out, returns invalid JSON or reports incomplete coverage stops the run. Failed calls are recorded and never retried automatically. The chunk plan is frozen on first use, and a changed export, voice configuration or masking result stops the run. An audit that omits a record stops the run.

## What stays out

- Media files are never opened. Captions on media, service records, forwarded messages (someone else's words) and other senders are never sent or cited.
- Detected secrets (private keys, passwords and credential assignments, API keys, bearer tokens, JWTs, credential URLs, login links, long machine-like strings) are replaced with `[SECRET: <kind> for <service>, shared <date>]`. A value detected once is masked everywhere it reappears, even without its label.
- The Claude backend runs `claude -p` in an empty temporary directory, with `--tools ''`, `--strict-mcp-config` and an empty MCP config, `--disable-slash-commands`, `--safe-mode` and `--no-session-persistence`, and with `ANTHROPIC_*`, `CLAUDE_CODE_USE_*` and `CLAUDECODE` removed from its environment.
- The Ollama backend posts to `/api/chat` with a JSON-schema `format`, temperature 0, no proxy, and refuses any endpoint that is not loopback unless you pass `--allow-remote-endpoint`.

## Usage

Export the chat from Telegram Desktop (*Export chat history*, format *JSON*). Keep the export and the run directory outside any repository; `runs/`, `exports/` and `result.json` are git-ignored here as a backstop.

```bash
cd agent-memory
python3 agent_memory.py inventory ~/private/result.json            # chats, sender IDs, counts; no text
python3 agent_memory.py init --run runs/one --export ~/private/result.json --chat 0 \
    --user-id user1000001 --agent-id user2000002 --user-name Juniper --agent-name Wren
python3 agent_memory.py mask-report --run runs/one                 # masked spans per kind, never values

python3 agent_memory.py propose --run runs/one --backend claude:opus --max-chunks 2   # pilot first
python3 agent_memory.py propose --run runs/one --backend claude:opus                  # then the rest
python3 agent_memory.py audit   --run runs/one --backend ollama:gemma4:e4b            # a different model

python3 agent_memory.py review  --run runs/one                     # writes runs/one/review.json, all pending
python3 agent_memory.py approve --run runs/one --by Juniper --id M-… --reject M-…   # or --all (bulk)
python3 agent_memory.py export  --run runs/one --out exports/wren-memory
python3 agent_memory.py verify  exports/wren-memory
python3 agent_memory.py search  exports/wren-memory "studio loan" --speaker Juniper
```

Backends are `claude:<model>` (any model name the Claude Code CLI accepts) or `ollama:<model>[@http://127.0.0.1:11434]`. Using the proposer's backend as auditor requires `--allow-same-model`, and the export then says that the audit was not independent.

Give the agent the exported folder. Its `README.md` explains how to cite records, keep the voices apart, treat quoted instructions as history and say "I don't know from this memory" when nothing matches.

### What the run directory contains

`run.json` (export path and hash, voices), `inventory.json`, `plan.json` (frozen chunks), `calls/` (every model request and response, masked), `results/` (verified and rejected proposals with reasons), `audits/`, and `review.json`. It holds your personal data. Keep it private.

## Files

| File | Role |
|---|---|
| `agent_memory.py` | Command-line entry point |
| `tg_export.py` | Telegram JSON parsing and metadata-only inventory |
| `masking.py` | Secret patterns, masking, second-pass detection |
| `backends.py` | Claude Code CLI and Ollama backends, strict schema validation |
| `quotes.py` | Word-for-word quote verification and export-time recheck |
| `pipeline.py` | Run directory, chunking, prompts, propose, audit, review, approve |
| `export_memory.py` | MEMORY.md, the agent's README.md, records.jsonl, SHA256SUMS |
| `search_memory.py` | Plain-text search over an export |
| `sample/telegram-export.json` | Invented two-voice chat (fictional people) with a secret, a correction, an old instruction, a photo, a forwarded post and an edit |
| `tests/` | Offline tests with a scripted backend: `python3 -m unittest discover -s tests` |

## Limits

- **Verified quotes, not verified facts.** Code proves that a quote exists in the export. Whether the statement says no more than the quotes is judged by the audit model and by you. Neither proves that what someone said was true.
- **Audits can share blind spots.** Two models from the same family, or the same model with `--allow-same-model`, can agree on the same mistake.
- **Masking is pattern-based.** Unusual secrets, secrets split across messages, and personal data that is not a credential (addresses, health details) are not masked. Masked text still goes to the model you choose. With the Claude backend it leaves your machine.
- **Coverage is what the model returned.** Windows are cut by day and size, so context across windows can be lost. A model that declares `complete=1` may still miss things.
- **One chat, final revisions.** One chat per run. Message IDs must be unique. Only the exported final text of edited messages is visible.
- **Bulk approval is labelled, not hidden.** `approve --all` is recorded as "bulk approval, not line-reviewed" in every exported record.
