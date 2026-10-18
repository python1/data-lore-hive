# Pack maker (beta)

A static page that builds a verified-memory pack from a ChatGPT or Claude data export,
entirely in the browser. This folder is repo-only: it is not part of the npm package.

**Live: <https://python1.github.io/data-lore-hive/>** (GitHub Pages). It works in Chromium, Firefox and WebKit, both
served over http and opened from disk (`file://`).

## Try it locally

```sh
npm install        # dev-only: Playwright, for the browser tests
npm run build      # builds the parent package (for the verifier), then dist/index.html
open dist/index.html
```

`dist/index.html` is one self-contained file (app, worker and styles inlined). Its
Content-Security-Policy pins the inline script and style by hash and sets
`connect-src 'none'`, so the page cannot send anything anywhere. Load
`test/fixtures/chatgpt-conversations.json` or `claude-conversations.json` to try it with
invented data. Large exports are parsed in a Web Worker; where a browser cannot read the
file inside a worker (WebKit on `file://`), the page parses on the main thread instead.

## Modules (`src/`, no dependencies, run in browsers and Node 22+)

| File | Does |
|---|---|
| `zip.mjs` | Reads zip exports through random access (only the central directory and `conversations*.json` are read, never the media), stored/deflate, zip64, CRC-checked. Writes the download zip (stored, deterministic). |
| `load-export.mjs` | Loads one file or several parts of one export. Recognises the format from the data, not the file name: ChatGPT, Claude, or a plain `messages.jsonl` in the builder's format. |
| `export-chatgpt.mjs` | Walks the `mapping` tree from `current_node`; other branches are kept but marked. |
| `export-claude.mjs` | Reads `chat_messages` content blocks; thinking becomes its own message; injected prompts are never used; tree branches from `parent_message_uuid`. |
| `export-common.mjs` | Message shape, warnings, dates, lone-surrogate repair. |
| `ui-logic.mjs` | Page logic without the DOM: selection trimming, error placement, search, drafts. |
| `app.mjs`, `app.css`, `worker.mjs` | The page. Export text is only ever inserted as text nodes, never as HTML. |
| `pack-inputs.mjs` | Browser selection → code-point quote; selections → the CLI's `messages.jsonl` + `records.jsonl` → pack via `../tools/pack-core.mjs`. |
| `check-pack.mjs` | "Check a signed pack": reads a pack (zip or loose files) and runs the shared `../dist/verify.js` on it, supplying SHA-256, SHA-512 and Ed25519 from Web Crypto. |

The pack is built by the same `tools/pack-core.mjs` as the CLI, and the page can offer the
two input files for download, so `verified-memory-build-pack` reproduces the pack byte for byte.

## Signed and dated packs

The page **does not sign, and never writes `PACK.json`**, so its packs still load on
0.2.0 hosts. A signing key in a web page would be exposed to everything
else running there, and storage on `python1.github.io` is shared by every GitHub Pages
site on that account. After a build, *Sign it (optional)* shows the `sign-pack` command
to run from a checkout on your own computer, where the key stays; `sign-pack` adds the
dates and runs `ssh-keygen -Y sign` (see the [MCP README](../README.md#signed-and-dated-packs)).

*Check a signed pack* takes a pack and the public keys you trust (and, since 0.4.0,
pinned signer fingerprints, revoked fingerprints and a minimum sequence), and gives the
same verdict as the MCP server and the OpenClaw plugin, including freshness (by this
computer's clock) and the *Strict* option. That's because it runs the same
`verify.js`. That verifier is synchronous, while Web Crypto is not. So when the verifier
needs a hash or signature check the page has not computed yet, the run stops, the page
computes it, and the run starts again. No rule is reimplemented here, and a Node test
checks that the page reaches the server's verdict on signed, unsigned, dated (fresh,
expired, future), sequenced, pinned, revoked and broken packs.
A browser without Ed25519 in Web Crypto is told it cannot check signatures; it is never
shown a pass. Current Chrome, Firefox and Safari all have Ed25519 (the browser tests
cover all three engines).

## Export formats

Neither vendor documents its export schema. Each format is checked with
`tools/export-shape.mjs` (structure only, no text) on a real export, and the invented
fixtures follow what it shows.

- **Claude: checked against a real export (October 2026).** The export is a manifest plus
  one zip per kind of data, each with its own one-time download link. Only
  `conversations-NNN.zip` holds chats, and there may be several parts; each holds a
  `conversations.json`. The page accepts any number of parts at once. It recognises
  `memories`, `projects`, `frames`, `light_metadata` and `users` files by name and never
  opens them. Any other chosen file without conversations (such as the manifest) is noted
  and skipped. A broken conversations part is an error, so chats are never silently lost.
  Inside: `sender` is `human`/`assistant`; `created_at` is UTC ISO; every message has
  `parent_message_uuid`; `content` blocks of type `text` make the message.
  `injected_prompt_block` (text the app adds to a turn) is never used, and once a message
  has content blocks its plain `text` field is never used either, because it can echo an
  injected prompt. A non-empty `thinking` block becomes a separate reasoning message;
  empty (hidden) ones are counted. `tool_use`, `tool_result`, `flag` and `token_budget` are
  skipped and counted. `image` and `document` count as attachments. A conversation found
  in two parts is kept once.
- **ChatGPT: not yet checked against a real export.** Text is `content.parts` strings
  joined with a blank line; `multimodal_text` voice transcripts (`audio_transcription`)
  count as text; `code`, `thoughts` and `reasoning_recap` are kept as separate kinds;
  `system`/`tool` roles, hidden messages and assistant messages addressed to a tool
  (`recipient` other than `all`) are skipped; dates are `create_time` epoch seconds.
- A message with no date is shown but cannot be quoted (the pack needs a date per quote).

Anything unexpected never crashes the loader: it is skipped and counted in `warnings`,
which the page shows. A fuzz test mutates every fixture 400 times to hold that line.

## Tests

- `npm test`: Node tests for every module, the build and its CSP (builds the parent
  package first, for the verifier).
- `npm run test:e2e`: Playwright tests of `dist/index.html` in Chromium, Firefox and
  WebKit, each over http and from `file://` (84 runs). They rebuild a golden pack through
  the UI byte for byte, reopen a draft, use a real triple-click selection, check that
  export text is never run as HTML, check signed, unsigned and broken packs in the
  check panel (loose files and zipped), that the CSP blocks requests, and that no request
  other than local `blob:` URLs happens after the page loads. First run:
  `npx playwright install chromium firefox webkit`.
- CI: `.github/workflows/verified-memory-tests.yml` runs both on pull requests.

Fixtures in `test/fixtures/` are invented (the fictional Larkfield garden) and regenerated by `test/fixtures/make-fixtures.mjs`.
`test/golden/` holds the packs built from them; regenerate deliberately with `UPDATE_GOLDEN=1 npm test`.
No real chat data belongs anywhere in this folder.

## Publishing

`.github/workflows/pack-maker-pages.yml` builds the page and deploys it to GitHub Pages
at <https://python1.github.io/data-lore-hive/> (Pages source: GitHub Actions). It runs on
every push to `master`, so merging updates the live page; it can also be started by hand
from the Actions tab. Hosting adds nothing
to the page: GitHub serves the one file, and the page cannot contact anything.
