# Verified Memory 0.4.0

## Behavior change: editing the pack while it is in use now stops serving

Until 0.3.0, the server kept answering from the snapshot it verified at startup, even
after the pack folder changed on disk. **In 0.4.0, if anything in the pack folder changes
while the server or plugin is running, both tools stop answering** and return:

```text
verified-memory: pack files changed on disk since startup, so the verified snapshot no longer matches them; restart to verify the pack again
```

This covers an edited file (even one whose modification time was put back), an added or
removed file, and a file or the whole folder replaced. The refusal is latched: once a change
is seen, the tools keep refusing even if the file is removed again or the folder is put
back, until the process restarts and verifies the pack again. **To update a pack, replace it and
then restart** Claude Desktop, the MCP client or the OpenClaw plugin. The check reads file
metadata on each request; there are no watchers and nothing is re-read or written.
This applies with every configuration, including one that sets none of the new options.

## Recommended setup: pin the signer

For signed packs, pin the key that signs them. Then a trusted-keys file that someone else
rewrote cannot vouch for their pack.

1. Sign each pack with `sign-pack`, raising `--sequence` every time you publish:

   ```sh
   node tools/sign-pack.mjs --pack my-pack --key ~/.ssh/verified-memory-pack --expires 90d --sequence 1 --out my-pack-signed
   ```

   It prints the line to pin, for example `--trusted-fingerprint SHA256:…`.

2. Start the server with that fingerprint, a minimum sequence and strict mode:

   ```sh
   verified-memory-mcp --pack /absolute/path/to/my-pack-signed \
     --trusted-fingerprint SHA256:… --min-sequence 1 --strict
   ```

   **Claude Desktop add-on:** paste the fingerprint into *Pinned signer fingerprint*, set
   *Minimum pack sequence*, and turn on *Strict*. No trusted keys file is needed.
   **OpenClaw:** `"trustedFingerprints": ["SHA256:…"], "minSequence": 1, "strict": true`.

3. When you install a newer pack, raise the minimum sequence to its number.

Why: in red-team round 4, an attacker bot on a shared machine that could rewrite the
trusted keys file added its own key and re-signed a poisoned pack, and 0.3.0 served it as
`verified`. With a pin, that pack is refused: `pack is signed by SHA256:…, which is not a
pinned signer fingerprint`.

## New

- **Pinned signers:** `--trusted-fingerprint` (repeatable, or comma-separated) /
  `trustedFingerprints`. When set, only a pinned key is accepted, whatever
  `--trusted-keys` says, and an unsigned pack is refused.
- **Revocation:** `--revoked-keys FILE` / `revokedKeys`, one `SHA256:…` per line. A revoked
  signer is always refused, even when pinned or trusted, and the error names it.
- **Rollback protection:** `PACK.json` may carry a signed integer `sequence`.
  `--min-sequence N` / `minSequence` refuses a missing or lower sequence. You set and raise
  `N`; the server keeps no state and writes nothing. (`version` stays the format version.)
- **Order of checks**, each refusal one specific error: files and checksums → signature
  valid → revoked → pinned → trusted keys → sequence → expiry (under `--strict`).
- **Claude Desktop add-on:** new optional settings *Pinned signer fingerprint*, *Revoked
  keys file*, *Minimum pack sequence* and *Strict*. All default to off.
- **`sign-pack --sequence N`**, and it prints the `--trusted-fingerprint` line.
- **Pack maker:** *Check a signed pack* accepts pinned fingerprints, revoked fingerprints
  and a minimum sequence, and reaches the same verdict as the server.

## Compatibility

- Apart from stop-on-change, configurations without the new options behave as in
  0.3.0, with the same decisions and the same `verification` fields. A pack's `sequence`, if
  present, is reported in `verification.freshness.sequence`.
- Packs with a `sequence` need 0.4.0 or later; 0.3.0 hosts refuse the extra key. Packs
  without one load on 0.3.0 as before.
- Node: MCP server `>=22.0.0` (tested on 22.0.0, 22.23.3, 24 and 25); OpenClaw plugin
  `>=24.16.0 <25 || >=26.1.0` (tested on 24.22.0 and 26.12.0). CI runs every suite on
  macOS and Windows.

## Limits

- A signature shows who signed, not that the content is true.
- Change detection uses file metadata (listing, size, modification and change time,
  device and inode). An administrator who can reset the clock or the filesystem can defeat it.
- Revocation and the minimum sequence are only as current as your configuration. There
  is no network, so nothing updates them for you.
- Nothing here protects a host whose own configuration (MCP client config, Claude Desktop
  settings, OpenClaw config or the revoked keys file) an attacker can write.

## Downloads

- `verified-memory-0.4.0.mcpb`, SHA-256 `576070d87208cee58482ab8f2dd04c6773f82b968952872fb12bcc004c251129`. It is not code-signed, so
  Claude Desktop shows its "not verified by Anthropic" warning for add-ons installed from a file.
- npm: `@python1/verified-memory-mcp@0.4.0`. OpenClaw plugin: `@python1/verified-memory@0.4.0` on ClawHub, not npm.
