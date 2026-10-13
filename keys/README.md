# Pack-signing public keys

Public keys only. No private key is ever stored in this repository (CI fails if one appears).

`verified-memory-pack.pub` will hold the maintainer's Ed25519 key for signing Verified Memory
packs, in trusted-keys form (`name ssh-ed25519 AAAA… comment`). It is made and used only on a
separate signing machine, protected by a passphrase.

**No host trusts this key by default.** The OpenClaw plugin and the MCP server trust only keys
you list. To accept packs signed with it, opt in:

```sh
# MCP server
verified-memory-mcp --pack /path/to/pack --trusted-keys /path/to/keys/verified-memory-pack.pub --strict
```

```json
// OpenClaw plugin config: paste the file's line into trustedKeys
{"trustedKeys": ["python1-packs ssh-ed25519 AAAA… verified-memory pack signing"], "strict": true}
```

Before trusting it, compare its fingerprint with one published through a channel you trust:

```sh
ssh-keygen -l -f <(cut -d' ' -f2- keys/verified-memory-pack.pub)
```
