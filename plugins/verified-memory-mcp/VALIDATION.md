# Validation — 2026-10-11

Tested on macOS ARM64 with TypeScript 5.9.3, Node 22 type definitions, and
official MCP TypeScript SDK 1.32.1. **Minimum supported Node: 22.0.0**;
`engines.node` is `>=22.0.0`. The complete `npm test` workflow, including the build,
was rerun on each runtime below. Node 22 runs use npm 10.9.3. No system runtime
was replaced, and `private: true` is retained.

| Node runtime | Passed | Failed | Skipped | Evidence |
|---|---:|---:|---:|---|
| 22.0.0 (minimum) | 25 | 0 | 1 | [tests-node22-min.txt](validation/tests-node22-min.txt) |
| 22.23.3 | 25 | 0 | 1 | [tests-node22-current.txt](validation/tests-node22-current.txt) |
| 25.8.0 | 26 | 0 | 0 | [tests.txt](validation/tests.txt) |

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
fictional source. Temporary tests use only copies of that sample, not real data.

The original `plugins/verified-memory` is unchanged. No Gateway, live agent,
Claude Desktop configuration change, model service, publishing or merge is used.
Claude Desktop's configuration is documented but an actual Desktop session has
not been tested. Other SDK versions, untested Node releases, systems and MCP
host policies are not validated. Runtime permission claims refer to the documented direct Node command;
running without permission mode relies on the implementation's read-only behavior.

The verifier's existing security and integrity limits still apply: checksums do
not prove authenticity, truth or source quotation fidelity, and filesystem checks
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
