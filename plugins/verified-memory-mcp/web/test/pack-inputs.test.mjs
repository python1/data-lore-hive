import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { loadExport } from '../src/load-export.mjs';
import { bytesSource } from '../src/zip.mjs';
import { buildPack, InputError, packInputs, quoteFromSelection } from '../src/pack-inputs.mjs';
import { sha256 } from '../../tools/pack-core.mjs';
import { verifyPackEntries } from '../../dist/verify.js';
import { loadPack } from '../../dist/pack.js';

// Golden packs built from the invented fixtures. Regenerate deliberately with UPDATE_GOLDEN=1.
const golden = resolve('test/golden');
const PACK_FILES = ['MEMORY.md', 'README.md', 'SHA256SUMS', 'records.jsonl'];

async function loaded(fixture) {
  const r = await loadExport({ name: 'conversations.json', source: bytesSource(readFileSync(resolve('test/fixtures', fixture))) });
  return new Map(r.conversations.flatMap((c) => c.messages).map((m) => [m.key, m]));
}
/** Find a message by its text and select `quote` the way a browser range would (UTF-16 offsets). */
function select(messages, contains, quote, occurrence = 0) {
  const m = [...messages.values()].find((x) => x.text.includes(contains));
  let at = -1;
  for (let i = 0; i <= occurrence; i++) at = m.text.indexOf(quote, at + 1);
  return { key: m.key, ...quoteFromSelection(m.text, at, at + quote.length) };
}

const cases = {
  chatgpt: async () => {
    const messages = await loaded('chatgpt-conversations.json');
    return { messages, speakers: { user: 'Rowan', agent: 'ChatGPT' }, title: 'Larkfield garden (ChatGPT fixture)', description: 'Invented fixture export. Not a real person or conversation.', records: [
      { record_id: 'M-role', role: 'user', topic: 'Role', category: 'profile', quotes: [select(messages, 'Morning!', 'I look after the tomato beds at the Larkfield community garden.')] },
      { record_id: 'M-swap-date', role: 'agent', topic: 'Seed swap', category: 'plans', quotes: [select(messages, 'Happy to help', "Let's hold the seed swap on the first Saturday in April.")] },
      { record_id: 'M-swap-place', role: 'user', speaker: 'Rowan and ChatGPT', topic: 'Seed swap', category: 'plans', statement: 'The seed swap moves to the greenhouse.', quotes: [
        select(messages, 'greenhouse instead', 'Can we do it by the greenhouse instead?'), select(messages, 'good spot', 'The greenhouse is a good spot.')] },
      { record_id: 'M-rota', role: 'user', topic: 'Watering rota', category: 'people', quotes: [select(messages, 'rota photo', 'Ivy waters on Mondays 🌱, Rowan on Thursdays.')] },
      { record_id: 'M-water', role: 'agent', topic: 'Watering', category: 'advice', statement: 'Water early; the café opens at 9.', quotes: [select(messages, 'Rota:', 'water', 1), select(messages, 'Rota:', 'The cafe\u0301 opens at 9.')] }
    ] };
  },
  claude: async () => {
    const messages = await loaded('claude-conversations.json');
    return { messages, speakers: { user: 'Rowan', agent: 'Claude' }, title: 'Larkfield garden (Claude fixture)', records: [
      { record_id: 'M-friday', role: 'agent', topic: 'Greenhouse', category: 'people', quotes: [select(messages, 'According to the rota', 'Tally waters the greenhouse on Fridays.')] },
      { record_id: 'M-compost', role: 'user', topic: 'Compost', category: 'routine', quotes: [select(messages, 'Great. Remind me', 'the compost bins get turned on the first of the month.')] },
      { record_id: 'M-beans', role: 'agent', topic: 'Beds', category: 'plans', quotes: [select(messages, 'Bed 4 gets', 'Bed 4 gets the beans; bed 3 is resting this year.')] },
      { record_id: 'M-cafe', role: 'user', topic: 'Café', category: 'places', quotes: [select(messages, 'Legacy text', 'the café 🌻')] }
    ] };
  }
};

for (const [name, make] of Object.entries(cases)) {
  test(`${name} fixture: selections build the golden pack, and the CLI rebuilds it from the input files byte for byte`, async (t) => {
    const input = await make();
    const { files, messagesBytes, recordsBytes } = await buildPack(input);
    const dir = join(golden, name);
    if (process.env.UPDATE_GOLDEN) {
      rmSync(dir, { recursive: true, force: true }); mkdirSync(join(dir, 'pack'), { recursive: true });
      writeFileSync(join(dir, 'messages.jsonl'), messagesBytes); writeFileSync(join(dir, 'records.jsonl'), recordsBytes);
      for (const f of PACK_FILES) writeFileSync(join(dir, 'pack', f), files[f]);
    }
    assert.deepEqual(Buffer.from(messagesBytes), readFileSync(join(dir, 'messages.jsonl')));
    assert.deepEqual(Buffer.from(recordsBytes), readFileSync(join(dir, 'records.jsonl')));
    for (const f of PACK_FILES) assert.deepEqual(Buffer.from(files[f], 'utf8'), readFileSync(join(dir, 'pack', f)), f);

    // The browser path: the pure verifier over in-memory bytes with Web Crypto hashes.
    const bytes = Object.fromEntries(PACK_FILES.map((f) => [f, new TextEncoder().encode(files[f])]));
    const digests = new Map();
    for (const b of Object.values(bytes)) digests.set(b, await sha256(b));
    assert.equal(verifyPackEntries(PACK_FILES, (f) => bytes[f], (b) => digests.get(b)).records.size, input.records.length);

    // The CLI path on the downloaded input files gives the same four files, and its loader accepts them.
    const root = mkdtempSync(join(tmpdir(), 'pack-maker-golden-'));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    const p = spawnSync(process.execPath, [resolve('../tools/build-pack.mjs'), '--messages', join(dir, 'messages.jsonl'), '--records', join(dir, 'records.jsonl'),
      '--out', join(root, 'pack'), '--title', input.title, ...(input.description ? ['--description', input.description] : [])], { encoding: 'utf8' });
    assert.equal(p.status, 0, p.stderr);
    assert.deepEqual(readdirSync(join(root, 'pack')).sort(), PACK_FILES);
    for (const f of PACK_FILES) assert.deepEqual(readFileSync(join(root, 'pack', f)), readFileSync(join(dir, 'pack', f)), f);
    assert.equal(loadPack(join(root, 'pack')).verification.records, input.records.length);
  });
}

test('golden inputs contain only the cited messages, numbered by date', () => {
  const lines = readFileSync(join(golden, 'chatgpt', 'messages.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(lines.map((m) => [m.id, m.speaker]), [[1, 'Rowan'], [2, 'ChatGPT'], [3, 'Rowan'], [4, 'ChatGPT'], [5, 'Rowan'], [6, 'ChatGPT']]);
  assert.ok(!lines.some((m) => m.text.includes('Draft one')), 'uncited branch message left out');
});

test('quoteFromSelection converts UTF-16 ranges to code-point offsets and refuses bad selections', () => {
  const text = '🌱 water early, 🌻 water early';
  const second = text.lastIndexOf('water early');
  assert.deepEqual(quoteFromSelection(text, second, second + 11), { quote: 'water early', start: 17 });
  assert.equal([...text].slice(17, 28).join(''), 'water early');
  assert.throws(() => quoteFromSelection(text, 1, 5), /splits a character/);
  assert.throws(() => quoteFromSelection(text, 0, 1), /splits a character/);
  assert.throws(() => quoteFromSelection(text, 2, 3), /only spaces/);
  assert.throws(() => quoteFromSelection(text, 4, 4), /select some text/);
  assert.throws(() => quoteFromSelection(text, 0, 999), InputError);
});

test('page-side refusals: undated or unloaded messages, and builder rules still apply', async () => {
  const messages = await loaded('chatgpt-conversations.json');
  const speakers = { user: 'Rowan', agent: 'ChatGPT' };
  const record = (quotes, extra = {}) => ({ record_id: 'M-x', role: 'user', topic: 't', category: 'c', quotes, ...extra });
  const undated = [...messages.values()].find((m) => m.date === null);
  assert.throws(() => packInputs({ messages, speakers, records: [record([{ key: undated.key, quote: 'Thanks', start: 0 }])] }), /record 1 quote 1: the export has no date/);
  assert.throws(() => packInputs({ messages, speakers, records: [record([{ key: 'gone', quote: 'x', start: 0 }])] }), /no longer loaded/);
  const q = select(messages, 'Morning!', 'tomato beds');
  await assert.rejects(buildPack({ messages, speakers, records: [record([{ ...q, start: q.start + 1 }])] }), /records line 1 quote 1: quote does not match the message at start/);
  await assert.rejects(buildPack({ messages, speakers, records: [record([q]), record([q])] }), /records line 2: duplicate record_id M-x/);
  await assert.rejects(buildPack({ messages, speakers: {}, records: [record([q])] }), /messages line 1: speaker is required/);
});
