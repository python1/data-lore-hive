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

## Run with npx

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
`README.md` and `SHA256SUMS`, plus an optional `PACK.json` (creation and expiry dates)
and an optional signature, `SHA256SUMS.sig`
(see [Signed and dated packs](#signed-and-dated-packs)). The easiest way to make one is the bundled offline
builder. It reads your messages and the records you want to remember, finds every
quote in its message, computes offsets and hashes, writes the pack, and then loads it
with the server's own verifier. If any quote is not verbatim in its message, it writes
nothing.

### From a ChatGPT or Claude export, in your browser

**Pack maker (beta): <https://python1.github.io/data-lore-hive/>.** Load your data export, search your chats, select
the exact sentences to remember, and download a ready pack. It runs entirely in the
browser (no server, and its Content-Security-Policy forbids network requests), uses the
same building code as the command-line builder, and checks the pack with the server's
own verifier before offering the download. It does not sign packs or add dates (use `sign-pack`,
below), but its *Check a signed pack* panel runs the same verifier on a signed pack and
the public keys you paste. Its source is in [`web/`](web/); to run it
from a checkout instead, run `npm install && npm run build` there and open
`web/dist/index.html`. See [`web/README.md`](web/README.md).

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
   The building rules (verbatim quotes, code-point offsets, hashes, file layout) live in
   `tools/pack-core.mjs`, which has no imports so a browser can run the same code.
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

Exactly one line per other file (three, or four with `PACK.json`), each
`<64 lowercase hex>` + two spaces + file name; no entry for `SHA256SUMS` or
`SHA256SUMS.sig`; at most 4 KiB:

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
Prefer rebuilding with the builder. Resealing also invalidates any signature: sign again.

## Signed and dated packs

A pack can carry two optional extras:

- `SHA256SUMS.sig`: an OpenSSH signature over the exact `SHA256SUMS` bytes, which pin
  every other file. Only Ed25519 keys, the `sha512` hash and the namespace
  `verified-memory-pack-v1` are accepted, so a git or code-release signature cannot be
  reused as a pack signature.
- `PACK.json` (since 0.3.0): when the pack was made and when it stops being current.
  It is listed in `SHA256SUMS` like every other file, so the signature covers the dates.

```json
{
  "format": "verified-memory-pack",
  "version": 2,
  "created_utc": "2026-10-12T18:00:00Z",
  "expires_utc": "2027-01-10T18:00:00Z"
}
```

Exactly these four keys; dates are UTC ISO 8601 and `created_utc` is before
`expires_utc`. A malformed `PACK.json` refuses to load. The pack maker and the builder
never write one, so their packs still load on 0.2.0 hosts; packs with a `PACK.json` need
0.3.0 or later (older hosts refuse the extra file).

### Signing: `sign-pack`

Sign on a machine you trust with a passphrase-protected key. `tools/sign-pack.mjs` is
in the repository but not in the npm package. It copies a verified pack to a new folder,
writes `PACK.json`, reseals `SHA256SUMS` and runs `ssh-keygen -Y sign`. **It never opens
the private key itself**: ssh-keygen reads it and asks for the passphrase (or uses
ssh-agent). Before it moves the result into place, it loads it with the hosts' own
verifier in strict mode, trusting only your `.pub`. It needs Node 22+ and OpenSSH 8.1+.

```sh
ssh-keygen -t ed25519 -f ~/.ssh/verified-memory-pack -C "my packs"   # once; set a passphrase
cd plugins/verified-memory-mcp && npm ci && npm run build            # once per checkout
node tools/sign-pack.mjs --pack /path/to/pack --key ~/.ssh/verified-memory-pack --expires 90d --out /path/to/pack-signed
```

`--expires` is a number of days (`90d`, at most `1825d`) or an exact UTC time
(`2027-01-31T00:00:00Z`). `--out` must not exist yet. On any failure (wrong passphrase,
a pack that does not verify) nothing is written. Signing an already signed pack replaces
its dates and signature. The script prints the key fingerprint and a trusted-keys line.
Keep the private key out of the pack, out of any repository and off shared machines.
Share only the `.pub` file.

Plain `ssh-keygen -Y sign -f KEY -n verified-memory-pack-v1 pack/SHA256SUMS` still makes
a valid signature, but the pack then has no expiry date (`freshness: unknown`), and
`--strict` refuses it.

### Choosing whom to trust

Trust is only ever a public key you list. There is no built-in key, network, key server
or registry. Put keys in a file, one per line in `allowed_signers` form,
`name ssh-ed25519 AAAA… [comment]` (blank lines and `#` comments are allowed):

```text
alice ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA… alice's laptop
```

The maintainer's pack-signing public key is in [`keys/`](../../keys/) for anyone who
chooses to trust packs signed with it. No host trusts it unless you list it.

```sh
verified-memory-mcp --pack /absolute/path/to/pack --trusted-keys /absolute/path/to/trusted_keys
verified-memory-mcp --pack /absolute/path/to/pack --trusted-keys /absolute/path/to/trusted_keys --require-signature
verified-memory-mcp --pack /absolute/path/to/pack --trusted-keys /absolute/path/to/trusted_keys --strict
```

`--flag=value`, `--require-signature=true|false` and `--strict=true|false` forms are
accepted too. `--require-signature` keeps its 0.2.0 meaning: a signature by a key you
listed is required, and freshness is reported but not enforced, so packs signed with
plain `ssh-keygen` for 0.2.0 keep loading under it. `--strict` requires a trusted
signature *and* a fresh `PACK.json` (it implies `--require-signature`).

### What hosts do

Every tool result carries `verification.signature` and `verification.freshness`.
Freshness is judged against this computer's clock on every call, not only at startup.

| Pack | Default | `--require-signature` | `--strict` |
|---|---|---|---|
| Unsigned (every 0.1 pack) | Starts; `signature.status: "unsigned"` | Refuses to start | Refuses to start |
| Signature present but malformed or invalid | Refuses to start | Refuses to start | Refuses to start |
| Valid signature, key not in your file | Starts; `untrusted`, with the key fingerprint | Refuses to start | Refuses to start |
| Valid signature, key in your file | Starts; `verified`, `signer` (your name for the key), `fingerprint` | Starts | Starts if fresh (below) |
| No `PACK.json` | Starts; `freshness.status: "unknown"` | Starts; `unknown` | Refuses to start |
| `PACK.json`, not yet expired | Starts; `fresh`, with `created_utc`, `expires_utc` | Starts; `fresh` | Starts |
| `PACK.json`, expired | Starts; `stale`, plus a warning on stderr | Starts; `stale`, plus a warning | Refuses to start; a running server stops serving (tool error) once it expires |
| `created_utc` more than 5 minutes in the future | Starts; `not_yet_valid`, plus a warning on stderr | Starts; `not_yet_valid`, plus a warning | Refuses to start |
| `PACK.json` or its checksum tampered with | Refuses to start | Refuses to start | Refuses to start |

`freshness.authenticated` is `true` only when a key you listed signed the dates; dates in
an unsigned or untrusted pack could have been written by anyone. `--require-signature`
or `--strict` with no trusted key, or a trusted key line that is not a single-name `ssh-ed25519` entry,
refuses to start. The signer name always comes from your file, never from the pack, and
fingerprints match `ssh-keygen -l`. Anyone can check a pack without this server:

```sh
ssh-keygen -Y verify -f trusted_keys -I alice -n verified-memory-pack-v1 -s SHA256SUMS.sig < SHA256SUMS
```

**A signature proves who signed, not that the content is true.** It shows that the
holder of that key signed these exact bytes. It does not show that the quotes are
accurate or complete, or that the key's owner is who you think. "Fresh" means the signer
set an expiry that has not passed, not that this is their latest pack: an older pack
from the same key still loads until it expires, and there is no revocation. Freshness
relies on this computer's clock. Version 0.1.0 refuses signed packs (five files);
remove `SHA256SUMS.sig` to load one there.

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

## Claude Desktop one-click install

**Not released yet.** The bundle is built and tested in CI but has not been published.

`verified-memory-<version>.mcpb` is an [MCP Bundle](https://github.com/modelcontextprotocol/mcpb)
for Claude Desktop on macOS and Windows. It runs on Claude Desktop's built-in Node.js, so
you need no Node install and no Terminal. Double-click it (or drag it into Claude Desktop,
or use **Settings → Extensions → Advanced settings → Install Extension…**), then fill in:

| Setting | Required | Passed as |
|---|---|---|
| Memory pack folder | yes | `--pack=<folder>` |
| Trusted keys file | no (blank = none) | `--trusted-keys=<file>` |
| Require a trusted signature | no (off) | `--require-signature=true\|false` |

Change these later in **Settings → Extensions → Verified Memory**. The bundle holds the
same `dist/` as the npm package plus its production dependencies, and nothing else: no pack,
keys, signatures or tests. It is not code-signed with `mcpb sign`, because that would need a
private key. It does not use Node's permission mode, because Claude Desktop starts the server itself.

Build it locally with `npm ci && npm run build:mcpb` (output: `build/verified-memory-<version>.mcpb`).
`npm run test:mcpb` builds it and runs [`test/mcpb/`](test/mcpb/). Those tests unpack the bundle with
`@anthropic-ai/mcpb` and start the server with the arguments that its `getMcpConfigForManifest`
produces from sample settings.

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
`"--allow-fs-read=/absolute/path/to/pack"` before the entry-point argument. With
`--trusted-keys`, also allow reading that file the same way.
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
`../verified-memory/src/pack.ts` and `verify.ts` **byte for byte** into ignored `src/`, and
copies its public fictional sample into ignored `sample-pack/`. TypeScript compiles
that same verifier into `dist/pack.js` (file reading) and `dist/verify.js` (the checks
themselves, with no imports). There is no second maintained verifier, and this build
never modifies the OpenClaw plugin. Build from the repository
checkout so the sibling source and sample are present. Generated files are not committed.

The whole pack must verify **before a server is created or stdio is connected**.
A failing pack cannot initialize, list tools or return records. The exact format
is four regular files: `records.jsonl`, `MEMORY.md`, `README.md`, and `SHA256SUMS`,
plus an optional `PACK.json` and `SHA256SUMS.sig` checked by the same shared verifier.
Checks include exact file inventory, SHA-256 hashes over the bytes actually parsed,
UTF-8, JSON, unique IDs, citation structure and offsets, date ranges, manifest
syntax, symlink roots/entries and file-size/count limits. Limits remain 16 MiB per
data file, 4 KiB manifest, 10,000 records. No permissive fallback. Later disk edits
cannot change the verified in-memory snapshot; retrieval returns copies.

Inherited filesystem checks are not a sandbox against an adversary able to race
ancestor directories. Use a trusted, stable local directory and the Node read allowlist.

**Integrity is not authenticity or truth.** Replacing both data and checksums can
produce a passing pack, unless you use `--strict` with a key you trust. Runtime cannot recheck quotations against original messages.
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
├── scripts/
│   ├── prepare.mjs
│   └── build-mcpb.mjs          # builds the Claude Desktop bundle into build/
├── mcpb/manifest.json          # Claude Desktop bundle manifest (settings form, tools)
├── src/
│   ├── index.ts
│   ├── server.ts
│   ├── pack.ts                 # generated, ignored; exact shared source
│   └── verify.ts               # generated, ignored; exact shared source
├── web/                        # repo-only: browser pack maker (see web/README.md)
├── tools/
│   ├── build-pack.mjs          # offline pack builder (ships in npm)
│   ├── pack-core.mjs           # its import-free building rules (ships in npm)
│   ├── sign-pack.mjs           # repo-only: signs and dates a pack via ssh-keygen
│   └── export-shape.mjs        # repo-only: prints a chat export's structure, never its text
├── examples/
│   ├── input/                  # invented messages.jsonl + records.jsonl
│   └── pack/                   # pack built from them
├── test/
│   ├── server.test.mjs
│   ├── sign-pack.test.mjs
│   ├── build-pack.test.mjs
│   ├── pack-core.test.mjs
│   ├── export-shape.test.mjs
│   └── mcpb/bundle.test.mjs    # run by `npm run test:mcpb` against the built bundle
├── validation/
│   ├── tests.txt               # Node 25.8.0
│   ├── tests-node22-min.txt     # Node 22.0.0
│   └── tests-node22-current.txt # Node 22.23.3
├── sample-pack/                # generated, ignored; four fictional files
├── build/                      # generated, ignored; the .mcpb and its staging folder
└── dist/                       # generated, ignored; JS and declarations
```

See [VALIDATION.md](VALIDATION.md) for recorded tests and limitations.

## License

MIT — [LICENSE](LICENSE). Free functionality, no paid tier.

☕ Support this project: https://buymeacoffee.com/python1
