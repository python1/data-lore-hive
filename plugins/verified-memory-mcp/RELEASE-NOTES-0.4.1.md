# Verified Memory 0.4.1

A small follow-up to 0.4.0. Signature, sequence, revocation and stop-on-change behavior
are unchanged.

## Changed

- **A pack with 0 records is refused at load.** An empty (or whitespace-only)
  `records.jsonl` used to load and answer every search with no matches. Now the server
  refuses to start, exits 1, and prints:

  ```text
  verified-memory-mcp: verified-memory: pack has no records; records.jsonl must hold at least one record
  ```

  The check is in the shared verifier, so the OpenClaw plugin and the pack maker's
  *Check a signed pack* refuse such a pack too. The builders never wrote one.
- **`sign-pack` ships in the npm package**, as the `verified-memory-sign-pack` command,
  next to `verified-memory-build-pack`. No checkout is needed to sign a pack:

  ```sh
  npx -y -p @python1/verified-memory-mcp verified-memory-sign-pack \
    --pack my-pack --key ~/.ssh/verified-memory-pack --expires 90d --sequence 1 --out my-pack-signed
  ```

  It still never opens the private key; ssh-keygen does. `node tools/sign-pack.mjs` from
  a checkout works as before.
- **Pack maker:** the *Strict* checkbox in *Check a signed pack* now reads "require a
  pinned or trusted signature", matching what it checks.
- **Pack maker site:** the GitHub Pages workflow also deploys on every push to `master`;
  it can still be run by hand.

## Documentation

- README and VALIDATION.md now say plainly: **quotes are checked against their source
  messages when the pack is built, and after that the signature protects them.** The
  server does not re-check quotes against `message_sha256` at load or at serve time; it
  never has the source messages.

## Compatibility

- Every pack that loaded on 0.4.0 loads on 0.4.1, except one with no records.
- Node: MCP server `>=22.0.0`, unchanged.

## Downloads

- `verified-memory-0.4.1.mcpb`, SHA-256 to be filled in when the release is built. It is
  not code-signed, so Claude Desktop shows its "not verified by Anthropic" warning for
  add-ons installed from a file.
- npm: `@python1/verified-memory-mcp@0.4.1`.
