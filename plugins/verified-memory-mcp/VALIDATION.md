# Validation — 2026-10-11

Tested on macOS ARM64, Node 25.8.0, TypeScript 5.9.3 and official MCP TypeScript
SDK 1.32.1. `npm test` builds from the unchanged shared verifier and runs 25 tests.
**25 passed, zero failed, skipped or cancelled.** Recorded output:
[validation/tests.txt](validation/tests.txt).

| Pack / check | Result |
|---|---|
| Valid eight-record fictional pack | MCP initialize, list tools, search and get succeed |
| Tampered MEMORY.md, README.md or records.jsonl; original hashes | Each refuses startup, exit 1, no stdout |
| Malformed JSON or UTF-8 with matching hashes | Each refuses startup, exit 1, no stdout |
| Rehashed duplicate ID, missing citations, wrong offsets, invalid ID/date/hash | Each refuses startup, exit 1, no stdout |
| Duplicate, missing, traversal, malformed or self-referential manifest entries | Each refuses startup, exit 1, no stdout |
| Missing pack/files, extra files, symlink file/root, relative path | Startup refuses |
| Actual stdio client under Node permission restrictions | Both tool calls succeed with writes/network/subprocesses/workers denied |

The stdio test launches the server directly with `--permission`, only a project
filesystem read allowlist, and an unrelated working directory. It uses the real SDK
Client and StdioClientTransport, rather than a handcrafted successful transcript.
Separate denial probes confirm that the same permission policy blocks filesystem
writes, socket connections, subprocesses and workers with `ERR_ACCESS_DENIED`.
The probes attempt only dummy operations; the policy rejects them.

Other coverage: exact input schemas and names, read-only annotations, JSON text /
structured response agreement, exact pottery citation, complete record retrieval,
no-match and missing-record results, historical instructions and voice separation,
query limits and extra-property/path injection rejection, unknown tools and absent
resource/prompt capabilities, immutable snapshots after disk edits and client-side
mutation, invalid CLI options, and byte-identical shared verifier/sample copies.
Every sample quote and message hash is independently compared against the public
fictional source. Temporary tests use only copies of that sample, not real data.

The original `plugins/verified-memory` is unchanged. No Gateway, live agent,
Claude Desktop configuration change, model service, publishing or merge is used.
Claude Desktop's configuration is documented but an actual Desktop session has
not been tested. Other SDK/Node versions, systems and MCP host policies are not
validated. Runtime permission claims refer to the documented direct Node command;
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
