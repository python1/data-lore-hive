# Validation — 2026-10-13 (v0.3.0: signed and dated packs, Claude Desktop bundle)

Tested on macOS ARM64 with TypeScript 5.9.3, Node 22 type definitions, and
official MCP TypeScript SDK 1.32.1. **Minimum supported Node: 22.0.0**;
`engines.node` is `>=22.0.0`. The complete `npm test` workflow, including the build,
was rerun on each runtime below. Node 22 runs use the official nodejs.org darwin-arm64
builds, checked against the published SHA256SUMS, with their bundled npm (10.5.1 on
22.0.0, 10.9.9 on 22.23.3); 25.8.0 uses npm 11.11.0. No system runtime was replaced.
Versions 0.1.0 and 0.2.0 are published; these records are for 0.3.0 (`PACK.json`
freshness, `--strict`, `sign-pack`, and the Claude Desktop `.mcpb` bundle), not yet published.

| Node runtime | Passed | Failed | Skipped | Evidence |
|---|---:|---:|---:|---|
| 22.0.0 (minimum) | 68 | 0 | 1 | [tests-node22-min.txt](validation/tests-node22-min.txt) |
| 22.23.3 | 68 | 0 | 1 | [tests-node22-current.txt](validation/tests-node22-current.txt) |
| 25.8.0 | 69 | 0 | 0 | [tests.txt](validation/tests.txt) |

The Claude Desktop bundle (`npm run test:mcpb`: builds `build/verified-memory-0.3.0.mcpb`,
unpacks it and runs it with the arguments `@anthropic-ai/mcpb` generates) passed 7/7 on
Node 25.8.0 and on Node 22.0.0.

The one explicit skip on Node 22 is the **additional socket-denial probe**: that
runtime has no network permission scope. All core server tests run and pass on
every tested version, including valid, tampered and malformed packs. The server
implementation remains offline; Node 22's permission model does not independently
enforce that network boundary. Node 25.8.0 additionally verifies OS socket API
denial through Node permissions. No network probe runs on versions that cannot
deny it, so testing does not open a socket on Node 22.

| Pack / check | Result |
|---|---|
| Valid eight-record fictional pack | MCP initialize, list tools, search and get succeed |
| Tampered MEMORY.md, README.md or records.jsonl; original hashes | Each refuses startup, exit 1, no stdout |
| Malformed JSON or UTF-8 with matching hashes | Each refuses startup, exit 1, no stdout |
| Rehashed duplicate ID, missing citations, wrong offsets, invalid ID/date/hash | Each refuses startup, exit 1, no stdout |
| Duplicate, missing, traversal, malformed or self-referential manifest entries | Each refuses startup, exit 1, no stdout |
| Missing pack/files, extra files, symlink file/root, relative path | Startup refuses |
| Actual stdio client under Node permission restrictions | Both tool calls succeed with writes/subprocesses/workers denied on every tested version |
| Pack builder on the invented `examples/input` | Rebuilds `examples/pack` byte for byte; stdio server returns the exact "café" quote from message 3 and both citations of the two-message record |
| Builder: non-verbatim, ambiguous or mis-positioned quote; unknown message, unknown field, bad date, duplicate message or record ID | Each exits 1 and leaves no pack or staging directory |
| Builder: text with a non-BMP character (emoji) before the quote | Offsets counted in code points, matching the verifier |
| Builder: `--out` already exists | Refuses; existing directory untouched |
| v0.1 unsigned pack, with or without `--trusted-keys` | Starts; same output either way; `signature.status` `unsigned`, `freshness.status` `unknown` |
| Signed, fresh pack over real stdio under permission mode, with `--strict`, `--strict=true`, `--require-signature`, and both | Starts; `verified`, `fresh`, `authenticated: true` |
| Committed `ssh-keygen` fixture (no `PACK.json`), key listed, `--require-signature` | Starts as in 0.2.0; `verified`, `ssh-keygen -l` fingerprint, freshness `unknown` |
| Expired signed pack with `--require-signature` | Starts; stderr warning; reports `stale` |
| Valid signature by an unlisted key | Starts; `signature.status` `untrusted`, no signer |
| Expired pack without `--strict` | Starts; one stderr warning (no path); every result reports `stale` |
| `--require-signature` with: v0.1 unsigned pack, wrong (unlisted) key, no keys | Each refuses startup, exit 1, no stdout (0.2.0 messages) |
| `--strict` with: v0.1 unsigned pack, wrong (unlisted) key, signed but undated pack, expired pack, future-dated pack, no keys, comment-only key file | Each refuses startup, exit 1, no stdout |
| Pack expires while the server runs | `--strict`: both tools return `isError` with no record data; `--require-signature`: keeps serving, reports `stale` |
| Expired pack with `expires_utc` extended and `SHA256SUMS` re-sealed | Refuses startup: signature does not verify |
| Signature byte flipped; malformed, missing or relative trust file | Each refuses startup, exit 1, no stdout, no configured path in stderr |
| Duplicate flags, missing values, `--strict=yes`, `--require-signature=yes` | Usage error, exit 1, no stdout |
| `sign-pack` with a passphrase-protected key, under Node permissions that deny reading the private key file | Signs; output passes `--strict` in the server, `loadPack` strict and `ssh-keygen -Y verify`; input untouched |
| `sign-pack`: wrong passphrase; bad `--expires`, existing `--out`, missing `.pub`, RSA key, tampered input | Each exits 1, writes nothing, leaves no staging folder |
| `npm pack` file list | Has the funding link; no keys, signatures, test fixtures or `sign-pack` |

The stdio test launches the server directly with a project filesystem read
allowlist and an unrelated working directory. It selects `--experimental-permission`
on early Node 22 and `--permission` when supported. It uses the real SDK Client
and StdioClientTransport. Denial probes confirm filesystem writes, subprocesses
and workers fail with `ERR_ACCESS_DENIED` on each runtime; the separate network
probe confirms socket denial where the runtime supports it. Early Node 22's
expected permission warning on stderr is accepted; stdout remains protocol-only.

Other coverage: exact input schemas and names, read-only annotations, JSON text /
structured response agreement, exact pottery citation, complete record retrieval,
no-match and missing-record results, historical instructions and voice separation,
query limits and extra-property/path injection rejection, unknown tools and absent
resource/prompt capabilities, immutable snapshots after disk edits and client-side
mutation, invalid CLI options, pack-neutral usage/error messages, and byte-identical shared
verifier/sample copies.
Every sample quote and message hash is independently compared against the public
fictional source. Temporary tests use only copies of that sample or the invented
`examples/input` garden data, not real data. The builder test spawns the builder as a
local Node process; the builder itself makes no network calls.

This build never modifies `plugins/verified-memory`; the shared verifier is edited
there and copied byte for byte (checked by a test). No Gateway, live agent,
Claude Desktop configuration change, model service, publishing or merge is used.
Claude Desktop's configuration is documented but an actual Desktop session has
not been tested. Other SDK versions, untested Node releases, systems and MCP
host policies are not validated. Runtime permission claims refer to the documented direct Node command;
running without permission mode relies on the implementation's read-only behavior.

The verifier's existing security and integrity limits still apply: checksums do
not prove authenticity, truth or source quotation fidelity, and a valid signature
proves only which key signed the exact bytes; freshness relies on the host clock, and
there is no revocation (an older pack from the same key loads until it expires); filesystem checks
are not a defense against adversarial ancestor-directory races. No downstream
model prompt-injection resistance or automatic recall is claimed. No new independent
verifier is maintained; future sibling-verifier changes require rebuilding/retesting.

Reproduce from `plugins/verified-memory-mcp`:

```sh
npm ci --ignore-scripts
npm test
```

Development installation/build/test writes are separate from the read-only server
runtime; the install fetches npm dependencies. The test harness spawns local Node
processes. It does not invoke a shell from the server or make network requests.

Permission flag differences are documented in the official
[Node 22.0 documentation](https://nodejs.org/download/release/v22.0.0/docs/api/permissions.html)
and [Node 22.13 documentation](https://nodejs.org/download/release/v22.13.0/docs/api/permissions.html).
Use a current patched Node release for deployment; 22.0.0 is the tested
compatibility floor, not a recommendation to install that old patch.
