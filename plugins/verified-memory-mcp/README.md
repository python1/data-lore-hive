# verified-memory-mcp

Free, MIT-licensed local **stdio MCP server** exposing `verified_memory_search`
and `verified_memory_get` using the official
[MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk/tree/v1.x)
(`@modelcontextprotocol/sdk` 1.32.1). Prepared for npm as `@python1/verified-memory-mcp`
and for the MCP Registry as `io.github.python1/verified-memory`; not yet published.

Runtime is read-only and offline: no network transport, sockets, telemetry,
embeddings, accounts, filesystem writes, subprocesses or shell execution. It reads
one configured pack at startup and serves an isolated in-memory snapshot. Stdout
is exclusively MCP protocol output; startup errors go to stderr and exit nonzero.
Only these two tools are exposed; no resources, prompts, filesystem or command tools.

## Run with npx (after publishing)

The npm package contains only `dist/`, the pack builder, this README and LICENSE. It ships **no pack**,
so `--pack` is required:

```sh
npx -y @python1/verified-memory-mcp --pack /absolute/path/to/pack
```

Claude Code: `claude mcp add verified-memory -- npx -y @python1/verified-memory-mcp --pack /absolute/path/to/pack`.
Running through npx does not apply Node's permission mode, because npx starts its own
Node process. For the read-only filesystem allowlist described below, install the
package and run its `dist/index.js` with `node` directly.

## Build your own pack

A pack is a directory with exactly four files: `records.jsonl`, `MEMORY.md`,
`README.md` and `SHA256SUMS`. The easiest way to make one is the bundled offline
builder. It reads your messages and the records you want to remember, finds every
quote in its message, computes offsets and hashes, writes the pack, and then loads it
with the server's own verifier. If any quote is not verbatim in its message, it writes
nothing.

### Quick start

1. Put your source messages in `messages.jsonl`, one JSON object per line:

   ```json
   {"id": 3, "date": "2026-03-02T08:20:00Z", "speaker": "Rowan", "text": "Quick thing first: the shed code changed. Also, the café on the corner sells seedlings on Saturdays."}
   ```

   | Field | Rule |
   |---|---|
   | `id` | positive integer, unique |
   | `date` | UTC ISO 8601 ending in `Z` or `+00:00`, e.g. `2026-03-02T08:20:00Z` |
   | `speaker` | non-empty string |
   | `text` | non-empty string; quotes are matched against it exactly |

2. Put what you want remembered in `records.jsonl`, one record per line, each citing
   exact quotes from those messages:

   ```json
   {"record_id": "M-garden-3", "role": "user", "topic": "Seedlings", "category": "places", "quotes": [{"message_id": 3, "quote": "the café on the corner sells seedlings on Saturdays."}]}
   ```

   | Field | Rule |
   |---|---|
   | `record_id` | `M-` followed by 1–127 letters, digits, `_` or `-`; unique |
   | `role` | `"user"` (the person) or `"agent"` (the assistant) |
   | `topic`, `category` | non-empty strings of your choice |
   | `quotes` | non-empty list of `{"message_id", "quote"}`; a quote must appear verbatim in that message. If it appears more than once, add `"start"` (the builder lists the choices) |
   | `statement` | optional summary; defaults to the quotes joined by spaces |
   | `speaker` | optional; defaults to the cited messages' speaker, required if they differ |

   Unknown fields are refused, so typos fail loudly.

3. Build into a directory that does not exist yet, then point the server at it:

   ```sh
   npx -y -p @python1/verified-memory-mcp verified-memory-build-pack \
     --messages messages.jsonl --records records.jsonl \
     --out /absolute/path/to/my-pack --title "My memory" --description "Optional text for the pack README"
   npx -y @python1/verified-memory-mcp --pack /absolute/path/to/my-pack
   ```

   From a repository checkout, run `node tools/build-pack.mjs ...` after `npm run build`.
   The builder makes no network calls. It never overwrites: it stages in a hidden sibling
   directory and renames it into place only after verification passes.

[`examples/input/`](examples/input/) holds invented sample input (a fictional community
garden, not real people), and [`examples/pack/`](examples/pack/) is the pack built from
it; the test suite rebuilds it byte for byte. Neither ships in the npm package.

### `records.jsonl` format (what the server verifies)

One JSON object per line, UTF-8, at most 10,000 records, unique `record_id`s.
Every field below is required unless marked optional:

| Field | Rule |
|---|---|
| `record_id` | `^M-[A-Za-z0-9_-]{1,127}$` |
| `role` | `"user"` or `"agent"` |
| `speaker`, `statement`, `topic`, `category` | non-empty strings |
| `date_first_utc`, `date_last_utc` | UTC ISO 8601 (`Z` or `+00:00`), first ≤ last |
| `evidence` | non-empty list of citations (below) |
| anything else | optional; kept and returned by `verified_memory_get` as metadata (e.g. `supersedes`, `approval`, `audits`) |

Each citation in `evidence`:

| Field | Rule |
|---|---|
| `message_id` | positive integer |
| `date_utc` | UTC ISO 8601, between the record's first and last dates |
| `quote` | non-empty exact text from the message |
| `start`, `end` | integers, `start ≥ 0`, `end − start` = quote length in Unicode code points (offsets index the message text by code point, as Python string slicing does) |
| `message_sha256` | 64 lowercase hex characters: SHA-256 of the full message text encoded as UTF-8 |

Example (one line in the file; wrapped here for reading):

```json
{"record_id":"M-garden-3","role":"user","speaker":"Rowan","category":"places","topic":"Seedlings",
 "statement":"the café on the corner sells seedlings on Saturdays.",
 "date_first_utc":"2026-03-02T08:20:00Z","date_last_utc":"2026-03-02T08:20:00Z",
 "evidence":[{"message_id":3,"date_utc":"2026-03-02T08:20:00Z",
   "quote":"the café on the corner sells seedlings on Saturdays.","start":48,"end":100,
   "message_sha256":"e3aebbd25f7b809dd5b0b8d55b9ad7df6566464dc2a5033d02e3c5aa7ed8eeb2"}]}
```

The server cannot see your original messages, so it checks citation structure, offsets'
arithmetic and hashes' format, not that the quote really came from that message. That
check happens only when the pack is built (by this builder or by `agent-memory/`).

### `MEMORY.md` and the pack `README.md`

The server requires both to exist, be valid UTF-8 and match `SHA256SUMS`. It does not
parse them or return them from either tool; they are for people and agents reading the
pack directly. By convention, and as the builder writes them:

- `MEMORY.md`: a `# Title` heading, then for each record its ID and speaker, its
  statement, and each quote with its message ID and date, marked as historical data.
- `README.md`: what the pack is and where it came from (SHA-256 of the input files,
  record count), plus the notice that quotes are data, not instructions, and that
  checksums prove integrity, not truth or approval.

### `SHA256SUMS` format

Exactly three lines, one per other file, each `<64 lowercase hex>` + two spaces +
file name; no entry for `SHA256SUMS` itself; at most 4 KiB:

```text
f3ed88bca6a7a451a892f49bd6d2970f5671b8c704d0bc6cae7646c46978bc69  MEMORY.md
0685a25133fd3e7f60e70ba1e836a2e8b045ace1e2be2ecbd306a4fc656f558f  README.md
34212f199411c8e4ef52cb341b0c68d970b5b30d9b8117c2eae5729b0d71dfa5  records.jsonl
```

If you edit a pack by hand, regenerate it from inside the pack directory:

```sh
shasum -a 256 MEMORY.md README.md records.jsonl > SHA256SUMS   # macOS
sha256sum MEMORY.md README.md records.jsonl > SHA256SUMS       # Linux
```

Resealing by hand only makes the checksums match again; it does not re-check quotes.
Prefer rebuilding with the builder.

## Build and run

From a checkout of this repository, using Node **22.0.0 or newer** (use the
latest patch release of your chosen Node line), in `plugins/verified-memory-mcp`:

```sh
npm ci --ignore-scripts
npm run build
npm test
node --experimental-permission --allow-fs-read="$PWD" "$PWD/dist/index.js"
```

The last command starts the stdio server, waiting for an MCP client on stdin.
It is not an interactive terminal search interface. Connect it through Claude
Desktop or another MCP client, then request a pottery search and retrieve
`M-sample-2`. Node's permission mode grants only reads under this project directory;
filesystem writes, subprocesses, workers and native addons are denied. The
`--experimental-permission` spelling works at the Node 22.0.0 floor; early Node 22
releases emit an experimental warning on stderr. On Node 22.13+ you can use
`--permission` instead. Node 22 does not enforce network permissions; this server
makes no network calls. Node 25.8.0 additionally passes the socket-denial probe.
See the [Node 22.0 permission documentation](https://nodejs.org/download/release/v22.0.0/docs/api/permissions.html)
and [Node 22.13 permission documentation](https://nodejs.org/download/release/v22.13.0/docs/api/permissions.html).
Use direct `node` invocation at runtime, not npm/npx or a shell wrapper.

Builds, dependency installation and tests are development operations: they write
local output; installing dependencies accesses the npm registry. Runtime does neither.
The test harness launches local Node processes and makes isolated temporary copies
of the fictional pack; the server itself never launches another process.

## Claude Desktop configuration example

Merge this example into your Claude Desktop MCP configuration and restart Claude
Desktop after building. All paths below are **placeholders**, not real user paths.
Replace them with absolute paths to the Node executable and this built directory.
No configuration is installed or edited automatically.

```json
{
  "mcpServers": {
    "verified-memory": {
      "command": "/absolute/path/to/node",
      "args": [
        "--experimental-permission",
        "--allow-fs-read=/absolute/path/to/hive-public/plugins/verified-memory-mcp",
        "/absolute/path/to/hive-public/plugins/verified-memory-mcp/dist/index.js"
      ]
    }
  }
}
```

In a repository build, omitting `--pack` uses the bundled fictional Juniper Vale/Wren
sample regardless of the client's working directory. An npm install has no sample and
refuses to start without `--pack`. To use your own pack, append
`"--pack", "/absolute/path/to/pack"` to `args`, and also add
`"--allow-fs-read=/absolute/path/to/pack"` before the entry-point argument.
Choose a pack that the connecting client is permitted to read.
Relative pack paths and unknown CLI flags are rejected. Tools cannot choose paths.
There is no discovery of home directories, other agents, real memory or configuration.
There are no watchers or reloads; restart to verify a different snapshot.

## Tool contracts

`verified_memory_search`:

```json
{"type":"object","properties":{"query":{"type":"string","minLength":1,"maxLength":512}},"required":["query"],"additionalProperties":false}
```

Returns `matches`, `matched`, `verification`, and `notice`. Search requires all
normalized Unicode words, at most 32 unique terms, across statement/topic/quotes.
Returns at most 10 matches, ordered by term occurrences, newest date, then record
ID. Matches preserve exact quotations, source message IDs, dates and speakers.
No stemming, semantic inference or network lookup. No match is not proof of absence.

`verified_memory_get`:

```json
{"type":"object","properties":{"id":{"type":"string","pattern":"^M-[A-Za-z0-9_-]{1,127}$"}},"required":["id"],"additionalProperties":false}
```

Returns `found`, full `record` (or null), `verification`, and `notice`, preserving
citation, provenance, audit, approval and supersession metadata as historical data.
Successful MCP results contain JSON text in `content` and the same object in
`structuredContent` (the MCP equivalent of the OpenClaw tool's `details`). Invalid
tool arguments return `isError: true`; unknown tool names return a protocol error.
Both tools advertise read-only, nondestructive, idempotent, closed-world annotations.

The SDK's low-level `Server` API keeps the published JSON schemas exact, including
`additionalProperties: false`; arguments are checked explicitly and by the shared
verifier. No OpenClaw runtime or dependencies are needed to build or run this server.

## Shared verifier and fail-closed startup

The development-only `scripts/prepare.mjs` copies the original
`../verified-memory/src/pack.ts` **byte for byte** into ignored `src/pack.ts`, and
copies its public fictional sample into ignored `sample-pack/`. TypeScript compiles
that same verifier into `dist/pack.js`. There is no second maintained verifier,
and no modification to the published OpenClaw plugin. Build from the repository
checkout so the sibling source and sample are present. Generated files are not committed.

The whole pack must verify **before a server is created or stdio is connected**.
A failing pack cannot initialize, list tools or return records. The exact format
is four regular files: `records.jsonl`, `MEMORY.md`, `README.md`, and `SHA256SUMS`.
Checks include exact file inventory, SHA-256 hashes over the bytes actually parsed,
UTF-8, JSON, unique IDs, citation structure and offsets, date ranges, manifest
syntax, symlink roots/entries and file-size/count limits. Limits remain 16 MiB per
data file, 4 KiB manifest, 10,000 records. No permissive fallback. Later disk edits
cannot change the verified in-memory snapshot; retrieval returns copies.

Inherited filesystem checks are not a sandbox against an adversary able to race
ancestor directories. Use a trusted, stable local directory and the Node read allowlist.

**Integrity is not authenticity or truth.** Replacing both data and checksums can
produce a passing pack. Runtime cannot recheck quotations against original messages.
Historical quotes are data, never instructions or permission; that notice accompanies
every successful result. Host model behavior and automatic tool selection are not
validated. Ask the host to quote tool text verbatim and cite record and message IDs.

Only the existing public fictional source
`agent-memory/sample/telegram-export.json` is used. No private records, operational
paths, IP addresses, keys or other-agent files are included. Fixture audit/approval
metadata is not evidence of real model auditing or human approval.

## File tree

```text
plugins/verified-memory-mcp/
├── .gitignore
├── LICENSE
├── README.md
├── VALIDATION.md
├── package.json
├── package-lock.json
├── server.json             # MCP Registry metadata
├── tsconfig.json
├── scripts/prepare.mjs
├── src/
│   ├── index.ts
│   ├── server.ts
│   └── pack.ts                 # generated, ignored; exact shared source
├── tools/build-pack.mjs        # offline pack builder (ships in npm)
├── examples/
│   ├── input/                  # invented messages.jsonl + records.jsonl
│   └── pack/                   # pack built from them
├── test/
│   ├── server.test.mjs
│   └── build-pack.test.mjs
├── validation/
│   ├── tests.txt               # Node 25.8.0
│   ├── tests-node22-min.txt     # Node 22.0.0
│   └── tests-node22-current.txt # Node 22.23.3
├── sample-pack/                # generated, ignored; four fictional files
└── dist/                       # generated, ignored; JS and declarations
```

See [VALIDATION.md](VALIDATION.md) for recorded tests and limitations.

## License

MIT — [LICENSE](LICENSE). Free functionality, no paid tier.
