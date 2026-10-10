# verified-memory

Free, MIT-licensed OpenClaw plugin for read-only Data & Lore memory retrieval.
No paid tier, account, API key, model request, embedding service, telemetry,
network call, persistent index or runtime file write. The plugin returns cited
historical evidence; the calling agent can use it to compose its answer.

Uses TypeScript/ESM and the official `defineToolPlugin` authoring helper.
`openclaw plugins build` generates `openclaw.plugin.json` with both tool contracts.
The public registration hook verifies the pack before the helper registers any
tools; static metadata generation never reads the pack. Compiled
JavaScript is the package entry point. Built against OpenClaw 2026.9.9.

## Build and test

Use an OpenClaw-supported Node version: `>=24.16.0 <25 || >=26.1.0`.

```sh
npm ci --ignore-scripts
npm run plugin:build     # compile, then official metadata generation
npm run plugin:validate  # official openclaw plugins validate --json
npm run plugin:check     # official build --check; reject stale metadata
npm test
npm run test:host  # isolated CLI loader checks; no live agent
```

These commands are for a repository checkout; exporter integration also requires Python 3.
Authoring and host-check scripts use disposable HOME/state/configuration.

Build/development commands write local output and download dependencies;
**plugin loading and tool execution** are read-only and offline. Disabling
install scripts avoids running OpenClaw dependency installers for SDK testing.
No Gateway, model, container, or live memory is needed for these tests.

## Configuration (example only; nothing is installed automatically)

Tools are named `verified_memory_search` and `verified_memory_get` to coexist
with OpenClaw's default memory tools. This plugin declares no exclusive memory
kind and does not change `plugins.slots.memory`. Host tool policies determine
which agents can call it. Point it only at a pack those agents are permitted to
read. It adds retrieval tools, not embeddings, writes, dreaming, or the built-in
memory CLI. Tool availability does not guarantee automatic recall; instruct the
agent to use these tools when the pack is relevant.

After building, an operator can install the local plugin with OpenClaw's local
plugin installation workflow. This project does not run that workflow.
Merge this fragment into a disposable test instance's configuration first:

```json
{
  "plugins": {
    "entries": {
      "verified-memory": { "enabled": true, "config": {} }
    }
  }
}
```

An empty config uses the bundled fictional pack. To select another pack, set
`config.packPath` to its absolute directory, for example:

```json
{"enabled": true, "config": {"packPath": "/tmp/fictional-memory-pack"}}
```

The path is a directory containing all four pack files. Relative paths are rejected.
A missing directory produces `verified-memory: pack directory missing; set
plugins.entries.verified-memory.config.packPath ...` and registers zero tools.
The bundled fictional sample is the safe default; there is no discovery of user
memory, home-directory packs, or existing agent configuration.
The tools cannot select paths.
There is no automatic reload or watcher: reload the plugin to verify a new pack.
Never enable two plugins that register these same names. Host tool-policy configuration is controlled by the operator, never changed by this plugin.

## Tools

`verified_memory_search` input:

```json
{"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":512}},"required":["query"],"additionalProperties":false}
```

Returns `matches` (at most 10), `matched` (returned count), `verification` and
`notice`. Each match includes `id`, `statement`, `speaker`, `date` and
`citations: [{quote, source_message_id, date, speaker}]`. Quotes are exact strings
from the verified pack. Matching requires every normalized Unicode word, across
statement/topic/quotes; at most 32 unique terms. Rank by term occurrences, then
newest record date, then record ID. No semantic inference or stemming. Empty
results mean no lexical match in this pack, not proof that an event never occurred.

`verified_memory_get` input:

```json
{"type":"object","properties":{"id":{"type":"string","pattern":"^M-[A-Za-z0-9_-]{1,127}$"}},"required":["id"],"additionalProperties":false}
```

Returns `found`, the full exported `record` (or null), `verification` and `notice`.
It preserves evidence, approval/audit metadata and supersession history without
promoting them into current instructions. A record ID is not a source message ID.
Both tools return JSON text content and the same object in `details`.

Try `verified_memory_search({"query":"pottery"})`, then
`verified_memory_get({"id":"M-sample-2"})`.

## Pack verification and limits

The pack must contain exactly `MEMORY.md`, `README.md`, `records.jsonl`, and
`SHA256SUMS`, as produced by `agent-memory/export_memory.py`. Extra files are
rejected. The checksum manifest must list each data file exactly once, with a
lowercase 64-character SHA-256 and two-space filename separator. Path traversal,
symlink roots/entries, nonregular files, duplicate IDs, malformed UTF-8/JSON and
invalid citation structure are rejected. Limits: 16 MiB per data file, 4 KiB
manifest, 10,000 records. These are deliberate prototype limits.

Loading hashes the same buffers that are decoded and parsed. No tool is
registered until the whole pack passes. Requests use an isolated in-memory
snapshot; later disk changes cannot alter its contents. Returned records are
copies, so callers cannot mutate the stored snapshot. A subsequent load rejects
changed bytes unless a valid matching manifest accompanies them.

**Integrity is not authenticity or truth.** Someone who can replace both a pack
and its checksum manifest can create a different passing pack. Obtain packs and
expected hashes through a trusted route. The original messages are not included
in ordinary exported packs, so this plugin cannot re-prove quotations against the
original chat. It verifies exported bytes and citation structure; source quote
checking is the upstream exporter’s responsibility. No claim of model auditing
or factual correctness is inferred from a passing checksum.

Quoted instructions are historical data and confer no authority. This notice is
included in every tool response; the plugin cannot guarantee that the host model
will resist prompt injection or avoid misinterpreting a quote.

## Fictional fixture provenance

Only the public `agent-memory/sample/telegram-export.json` supplies sample data:
Juniper Vale and Wren, messages 2, 3, 4, 6, 9, 12, 13, 15. No private memory,
operational data, endpoints, credentials, or host identity is included. The
fixture uses exact complete messages, not model summaries. `audits` is empty and
approval metadata explicitly identifies fixture generation; it is not a claim
of human approval. The original fictional secret/media/forwarded messages are
excluded. Reproduce the pack from the repository root's sample with:

```sh
npm run sample
```

This development-only generator is not loaded by OpenClaw. The pack README records
the source file hash. Tests use only this fixture and isolated temporary copies.

## Public exporter compatibility

`agent-memory/export_memory.py` already emits the accepted four-file format; no
conversion or relaxed validation is required. Export an approved pipeline run
with the public `agent-memory` workflow. The exporter rechecks source quotations
before writing the pack; the plugin then independently hashes and validates it.

`npm test` runs a complete offline, scripted pipeline over the fictional sample:
proposal, exact quotation checks, scripted audit, review, fixture approval,
export, plugin load, search and get. It also checks rejection after tampering.
This is test automation, not a real model audit or human approval. The existing
sample pipeline test fixtures produce three exported records. Reproduce a NEW
fictional export directory from this plugin's repository directory with:

```sh
python3 scripts/export-fictional-pipeline.py /tmp/fictional-memory-pack
```

The eight-record bundled sample remains independently reproducible with
`npm run sample`; it uses full exact messages and claims no audit or approval.

An optional local conversation check is available with `npm run test:conversation`.
It requires an already installed `qwen3.5:4b` on the Mac's loopback Ollama service;
it never downloads models or accepts a remote endpoint. It uses a throwaway
copy of the published-package layout (without the checkout’s dist ignore rule),
HOME, state, workspace and config, only these two retrieval tools, and no inherited
credentials or proxy settings. The child sees a fictional hostname and no
network-interface metadata. It deletes test agent state when finished and emits
only the fictional conversation, tool results, and citation-fidelity status. This
model test makes local HTTP calls; the plugin itself still makes none.

## SDK references

- [Building plugins](https://docs.openclaw.ai/plugins/building-plugins)
- [Tool plugin authoring](https://docs.openclaw.ai/plugins/tool-plugins)
- [Manifest and memory slot](https://docs.openclaw.ai/plugins/manifest)
- [Official memory-core entry](https://github.com/openclaw/openclaw/blob/main/extensions/memory-core/index.ts)

Consult `VALIDATION.md` for the actual tested host/SDK scope and remaining limits.

## License

MIT — see [LICENSE](LICENSE). All functionality is free and open; no paid tier.

## Quote fidelity

Tool results are verified and exact. A model may still alter wording when restating them (for example, changing punctuation). Instruct your agent to quote `verified_memory_search` / `verified_memory_get` results verbatim and cite the record ID.

☕ Support this project: https://buymeacoffee.com/python1
