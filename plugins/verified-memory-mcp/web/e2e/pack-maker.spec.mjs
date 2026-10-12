import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { downloadZip, expect, expectNoNetwork, expectNoProblems, fillRecord, loadFile, openConversation, select, test } from './fixtures.mjs';
import { nodeZip } from '../test/helpers.mjs';
import { loadPack } from '../../dist/pack.js';

const fixtures = resolve('test/fixtures');
const golden = resolve('test/golden');
const PACK_FILES = ['MEMORY.md', 'README.md', 'SHA256SUMS', 'records.jsonl'];
const CHATGPT_STATUS = 'ChatGPT export: 3 conversations, 17 messages. 1 has no date and cannot be quoted.';

/** Recreate, through the UI, the selections behind test/golden/chatgpt (see test/pack-inputs.test.mjs). */
async function buildChatGPTGolden(page) {
  await page.fill('#speaker-user', 'Rowan');
  await openConversation(page, 'Seed swap plans');
  await select(page, 'Morning!', 'I look after the tomato beds at the Larkfield community garden.');
  await page.click('#new-record');
  await fillRecord(page, 0, { record_id: 'M-role', topic: 'Role', category: 'profile' });
  await select(page, 'Happy to help', "Let's hold the seed swap on the first Saturday in April.");
  await page.click('#new-record');
  await fillRecord(page, 1, { record_id: 'M-swap-date', topic: 'Seed swap', category: 'plans' });
  await select(page, 'greenhouse instead', 'Can we do it by the greenhouse instead?');
  await page.click('#new-record');
  await fillRecord(page, 2, { record_id: 'M-swap-place', topic: 'Seed swap', category: 'plans', statement: 'The seed swap moves to the greenhouse.', speaker: 'Rowan and ChatGPT' });
  await select(page, 'good spot', 'The greenhouse is a good spot.');
  await page.selectOption('#target-record', { label: 'M-swap-place — Seed swap' });
  await page.click('#add-to-record');
  await openConversation(page, 'Shed rota');
  await select(page, 'rota photo', 'Ivy waters on Mondays 🌱, Rowan on Thursdays.');
  await page.click('#new-record');
  await fillRecord(page, 3, { record_id: 'M-rota', topic: 'Watering rota', category: 'people' });
  await select(page, 'Rota:', 'water', 1);
  await page.click('#new-record');
  await fillRecord(page, 4, { record_id: 'M-water', topic: 'Watering', category: 'advice', statement: 'Water early; the café opens at 9.' });
  await select(page, 'Rota:', 'The café opens at 9.');
  await page.selectOption('#target-record', { label: 'M-water — Watering' });
  await page.click('#add-to-record');
  await page.fill('#title', 'Larkfield garden (ChatGPT fixture)');
  await page.fill('#description', 'Invented fixture export. Not a real person or conversation.');
  await expect(page.locator('#build-status')).toHaveText('Verified: 5 records. Every quote matches its message word for word, and the checksums pass.');
}

function expectGoldenPack(files, folder) {
  expect(Object.keys(files)).toEqual(PACK_FILES.map((f) => `${folder}/${f}`));
  for (const f of PACK_FILES) expect(files[`${folder}/${f}`].equals(readFileSync(join(golden, 'chatgpt', 'pack', f))), f).toBe(true);
}

test('builds the golden ChatGPT pack through the UI, byte for byte, without any network request', async ({ app: { page, requests, problems }, browserName, pageUrl }, testInfo) => {
  await loadFile(page, join(fixtures, 'chatgpt-conversations.json'));
  await expect(page.locator('#load-status')).toHaveText(CHATGPT_STATUS);
  await expect(page.locator('#warnings-summary')).toHaveText('12 kinds of content were skipped or adjusted');
  await buildChatGPTGolden(page);

  const pack = await downloadZip(page, '#download-pack');
  expect(pack.name).toBe('larkfield-garden-chatgpt-fixture.zip');
  expectGoldenPack(pack.files, 'larkfield-garden-chatgpt-fixture');
  // The downloaded folder is accepted by the MCP server's loader.
  const dir = testInfo.outputPath('pack');
  mkdirSync(dir, { recursive: true });
  for (const f of PACK_FILES) writeFileSync(join(dir, f), pack.files[`larkfield-garden-chatgpt-fixture/${f}`]);
  expect(loadPack(dir).verification.records).toBe(5);

  await page.click('text=Rebuild or check it yourself');
  const inputs = await downloadZip(page, '#download-inputs');
  expect(inputs.files['larkfield-garden-chatgpt-fixture-inputs/messages.jsonl'].equals(readFileSync(join(golden, 'chatgpt', 'messages.jsonl')))).toBe(true);
  expect(inputs.files['larkfield-garden-chatgpt-fixture-inputs/records.jsonl'].equals(readFileSync(join(golden, 'chatgpt', 'records.jsonl')))).toBe(true);
  expect(inputs.files['larkfield-garden-chatgpt-fixture-inputs/REBUILD.txt'].toString()).toContain("--title 'Larkfield garden (ChatGPT fixture)'");

  expectNoNetwork(requests);
  expectNoProblems(problems, browserName, pageUrl);
});

test('a saved draft reopens on the same export and gives the identical pack', async ({ app: { page }, context, pageUrl }) => {
  await loadFile(page, join(fixtures, 'chatgpt-conversations.json'));
  await buildChatGPTGolden(page);
  const [download] = await Promise.all([page.waitForEvent('download'), page.click('#save-draft')]);
  const draftPath = await download.path();

  const fresh = await context.newPage();
  await fresh.goto(pageUrl);
  await loadFile(fresh, join(fixtures, 'chatgpt-conversations.json'));
  await fresh.setInputFiles('#load-draft', draftPath);
  await expect(fresh.locator('#load-status')).toHaveText('Draft opened: 5 records.');
  await expect(fresh.locator('#speaker-user')).toHaveValue('Rowan');
  await expect(fresh.locator('#build-status')).toHaveClass(/\bok\b/);
  expectGoldenPack((await downloadZip(fresh, '#download-pack')).files, 'larkfield-garden-chatgpt-fixture');
});

test('reads a Claude export zip among media files; reasoning is hidden until asked for', async ({ app: { page, requests } }, testInfo) => {
  const zipPath = testInfo.outputPath('claude-export.zip');
  writeFileSync(zipPath, nodeZip({ 'users.json': '[]', 'files/photo.png': Buffer.alloc(20000, 3), 'conversations.json': readFileSync(join(fixtures, 'claude-conversations.json')) }));
  await loadFile(page, zipPath);
  await expect(page.locator('#load-status')).toHaveText('Claude export: 2 conversations, 10 messages.');
  await expect(page.locator('#speaker-agent')).toHaveValue('Claude');
  await openConversation(page, 'Greenhouse watering');
  await expect(page.locator('.message-text')).toHaveCount(5);
  await page.check('#show-other');
  await expect(page.locator('.message-text', { hasText: 'The rota file says Tally on Fridays.' })).toBeVisible();
  await openConversation(page, 'Regenerated answer');
  await expect(page.locator('.message-text', { hasText: 'Bed 3, I think.' })).toHaveCount(0);
  await page.check('#show-branches');
  await expect(page.locator('article.message', { hasText: 'Bed 3, I think.' }).locator('.badge')).toHaveText('earlier version');
  expectNoNetwork(requests);
});

test('real mouse selection: a triple-click quotes the whole message, trimmed', async ({ app: { page } }) => {
  await loadFile(page, join(fixtures, 'chatgpt-conversations.json'));
  await openConversation(page, 'Compost day');
  await page.locator('.message-text', { hasText: 'compost bins' }).click({ clickCount: 3 });
  await expect(page.locator('#selection-preview')).toHaveText(/^“The compost bins get turned on the first of the month\.” — Me, 2026-03-12 07:30 UTC$/);
  await page.click('#new-record');
  await expect(page.locator('li.record blockquote')).toHaveText('The compost bins get turned on the first of the month.');
  await expect(page.locator('.message-text mark')).toHaveText('The compost bins get turned on the first of the month.');
});

test('selections that cannot become quotes are refused with an explanation', async ({ app: { page } }) => {
  await loadFile(page, join(fixtures, 'chatgpt-conversations.json'));
  await openConversation(page, 'Shed rota');
  await expect(page.locator('article.message', { hasText: 'Thanks, that matches' }).locator('.badge.warn')).toHaveText('cannot be quoted: no date');
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.message-text')].find((e) => e.textContent.startsWith('Thanks'));
    const r = document.createRange(); r.selectNodeContents(el); getSelection().removeAllRanges(); getSelection().addRange(r);
  });
  await expect(page.locator('#selection-error')).toHaveText('This message has no date in the export, so it cannot be quoted.');
  await expect(page.locator('#new-record')).toBeDisabled();
  await page.evaluate(() => {
    const texts = [...document.querySelectorAll('.message-text')];
    const r = document.createRange(); r.setStart(texts[0].firstChild, 5); r.setEnd(texts[1].firstChild, 3);
    getSelection().removeAllRanges(); getSelection().addRange(r);
  });
  await expect(page.locator('#selection-error')).toHaveText('Select text inside one message.');
  await expect(page.locator('#new-record')).toBeDisabled();
});

test('the Content-Security-Policy blocks network requests even if page code tried one', async ({ app: { page }, pageUrl }) => {
  const result = await page.evaluate(async (target) => {
    const violations = [];
    document.addEventListener('securitypolicyviolation', (e) => violations.push(e.effectiveDirective));
    let fetched = 'not attempted';
    try { await fetch(target); fetched = 'succeeded'; } catch { fetched = 'blocked'; }
    const img = new Image();
    const imageLoaded = await new Promise((r) => { img.onload = () => r(true); img.onerror = () => r(false); img.src = `${target}?image`; });
    await new Promise((r) => setTimeout(r, 200));
    return { fetched, imageLoaded, violations };
  }, pageUrl.startsWith('http') ? pageUrl : 'http://127.0.0.1:4173/');
  expect(result.fetched).toBe('blocked');
  expect(result.imageLoaded).toBe(false);
  expect(result.violations).toEqual(expect.arrayContaining(['connect-src', 'img-src']));
});

test('export text is shown as text, never run as HTML', async ({ app: { page } }, testInfo) => {
  const path = testInfo.outputPath('conversations.json');
  const evil = '<img src=x onerror="window.__ran=1"><script>window.__ran=2</script><b>bold?</b>';
  writeFileSync(path, JSON.stringify([{ uuid: 'c1', name: '<i>title</i>', created_at: '2026-03-01T00:00:00Z',
    chat_messages: [{ uuid: 'm1', sender: 'human', created_at: '2026-03-01T00:00:00Z', content: [{ type: 'text', text: evil }] }] }]));
  await loadFile(page, path);
  await openConversation(page, '<i>title</i>');
  await expect(page.locator('.message-text')).toHaveText(evil);
  await expect(page.locator('#thread img, #thread script, #thread b, #conversation-list i')).toHaveCount(0);
  expect(await page.evaluate(() => window.__ran)).toBeUndefined();
});

test('an unusable file shows an error and the page keeps working', async ({ app: { page } }, testInfo) => {
  const bad = testInfo.outputPath('conversations.json');
  writeFileSync(bad, '{"not": "an export"}');
  await loadFile(page, bad);
  await expect(page.locator('#load-status')).toHaveText('conversations.json: not a ChatGPT or Claude conversations file (expected a list of conversations)');
  await expect(page.locator('#workspace')).toBeHidden();
  await loadFile(page, join(fixtures, 'chatgpt-conversations.json'));
  await expect(page.locator('#load-status')).toHaveText(CHATGPT_STATUS);
  await expect(page.locator('#workspace')).toBeVisible();
});

test('search filters conversations by message text', async ({ app: { page } }) => {
  await loadFile(page, join(fixtures, 'chatgpt-conversations.json'));
  await page.fill('#search', 'COMPOST');
  await expect(page.locator('#search-count')).toHaveText('1 conversation matches');
  await expect(page.locator('#conversation-list button')).toHaveText(['Compost day2026-03-12 · 2 matching messages']);
  await page.fill('#search', 'first of the month');
  await expect(page.locator('#conversation-list button')).toHaveText(['Compost day2026-03-12 · 1 matching message']);
  await page.fill('#search', 'zzz-nothing');
  await expect(page.locator('#search-count')).toHaveText('0 conversations match');
});

test('fits a phone screen without sideways scrolling', async ({ app: { page } }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await loadFile(page, join(fixtures, 'chatgpt-conversations.json'));
  await openConversation(page, 'Shed rota');
  await select(page, 'rota photo', 'Ivy waters on Mondays 🌱, Rowan on Thursdays.');
  await page.click('#new-record');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('current Claude export: several conversations parts at once; other files are noted, injected text never shown', async ({ app: { page, requests } }, testInfo) => {
  const dir = testInfo.outputPath('claude-export');
  mkdirSync(dir, { recursive: true });
  const paths = {
    'conversations-000.zip': nodeZip({ 'conversations.json': readFileSync(join(fixtures, 'claude-current-part-000.json')) }),
    'conversations-001.zip': nodeZip({ 'conversations.json': readFileSync(join(fixtures, 'claude-current-part-001.json')) }),
    'memories-000.zip': nodeZip({ 'memories.json': '[]' }),
    'manifest.json': JSON.stringify({ invented: 'manifest' })
  };
  for (const [name, bytes] of Object.entries(paths)) writeFileSync(join(dir, name), bytes);
  await page.setInputFiles('#file', Object.keys(paths).map((name) => join(dir, name)));
  await expect(page.locator('#load-status')).toHaveText('Claude export (2 files): 2 conversations, 9 messages.');
  await expect(page.locator('#load-notes li')).toHaveText([
    'manifest.json: not used: not a ChatGPT or Claude conversations file (expected a list of conversations).',
    'memories-000.zip: not needed for a memory pack (only the conversations files are), so it was not opened.'
  ]);
  await page.click('#warnings summary');
  await expect(page.locator('#warnings-list')).toContainText('Text the Claude app added to messages (not typed by you) was left out and cannot be quoted (2)');
  await openConversation(page, 'Tool shed inventory');
  await page.check('#show-other');
  await page.check('#show-branches');
  await expect(page.locator('.message-text')).toHaveCount(4);
  await expect(page.locator('body')).not.toContainText('INJECTED');
  await openConversation(page, 'Pond day');
  await select(page, 'Got it', 'Last Sunday of April. Got it, café after.');
  await page.click('#new-record');
  await fillRecord(page, 0, { topic: 'Pond', category: 'routine' });
  await expect(page.locator('#build-status')).toHaveClass(/\bok\b/);
  expectNoNetwork(requests);
});

test('choosing only a non-chat part of a Claude export explains which file to choose', async ({ app: { page } }, testInfo) => {
  const path = testInfo.outputPath('memories-000.zip');
  writeFileSync(path, nodeZip({ 'memories.json': '[]' }));
  await loadFile(page, path);
  await expect(page.locator('#load-status')).toHaveText('memories-000.zip: not needed for a memory pack (only the conversations files are). Choose conversations-000.zip instead (and conversations-001.zip and so on, if your export has more parts).');
  await page.click('text=How do I get my export?');
  await expect(page.locator('.help').first()).toContainText('Each link works only once');
});
