# verified-memory-mcp

Free, MIT-licensed local **stdio MCP server** exposing `verified_memory_search`
and `verified_memory_get` using the official
[MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk/tree/v1.x)
(`@modelcontextprotocol/sdk` 1.32.1). Private development package: no publishing step.

Runtime is read-only and offline: no network transport, sockets, telemetry,
embeddings, accounts, filesystem writes, subprocesses or shell execution. It reads
one configured pack at startup and serves an isolated in-memory snapshot. Stdout
is exclusively MCP protocol output; startup errors go to stderr and exit nonzero.
Only these two tools are exposed; no resources, prompts, filesystem or command tools.

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

Omitting `--pack` uses the bundled fictional Juniper Vale/Wren sample regardless
of the client's working directory. To use your own pack, append
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
├── tsconfig.json
├── scripts/prepare.mjs
├── src/
│   ├── index.ts
│   ├── server.ts
│   └── pack.ts                 # generated, ignored; exact shared source
├── test/server.test.mjs
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
