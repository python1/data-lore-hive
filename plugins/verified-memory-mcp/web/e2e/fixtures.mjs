// Shared Playwright fixtures and helpers for the pack maker browser tests.
import { test as base, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { bytesSource, openZip, readEntry } from '../src/zip.mjs';

export { expect };

/**
 * `app` opens the page and then records every request and console problem. Requests made
 * while the page itself loads are not counted; everything after that must stay local.
 */
export const test = base.extend({
  pageUrl: ['', { option: true }],
  app: async ({ page, pageUrl }, use) => {
    const problems = [];
    page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error') problems.push(`console: ${m.text()}`); });
    await page.goto(pageUrl);
    const requests = [];
    page.on('request', (r) => requests.push(r.url()));
    await use({ page, requests, problems });
  }
});

/** Every request after load must be a local blob:/data: URL (worker script, downloads). */
export function expectNoNetwork(requests) {
  expect(requests.filter((u) => !/^(blob|data):/.test(u))).toEqual([]);
}

/**
 * WebKit cannot read a File inside a worker on file:// pages; the page then falls back to
 * the main thread, and WebKit logs that failed read as a console error. Nothing else is allowed.
 */
export function expectNoProblems(problems, browserName, pageUrl) {
  const allowed = (p) => browserName === 'webkit' && pageUrl.startsWith('file:') && /^console: Cannot load blob:null\//.test(p);
  expect(problems.filter((p) => !allowed(p))).toEqual([]);
}

export async function loadFile(page, path) {
  await page.setInputFiles('#file', path);
  await expect(page.locator('#load-status')).toHaveClass(/\b(ok|error)\b/);
}

/** Select `quote` (its n-th occurrence) inside the message whose text contains `contains`, as a DOM range. */
export async function select(page, contains, quote, occurrence = 0) {
  await page.evaluate(([contains, quote, occurrence]) => {
    const el = [...document.querySelectorAll('.message-text')].find((e) => e.textContent.includes(contains));
    if (!el) throw new Error(`no visible message contains ${contains}`);
    let at = -1;
    for (let i = 0; i <= occurrence; i++) { at = el.textContent.indexOf(quote, at + 1); if (at < 0) throw new Error(`quote not found: ${quote}`); }
    // Highlights split the text into several nodes; map the offset onto the right one.
    const point = (offset) => {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) { if (offset <= n.data.length) return [n, offset]; offset -= n.data.length; }
      throw new Error('offset past end of message');
    };
    const range = document.createRange();
    range.setStart(...point(at)); range.setEnd(...point(at + quote.length));
    getSelection().removeAllRanges(); getSelection().addRange(range);
  }, [contains, quote, occurrence]);
  await expect(page.locator('#selection-preview')).toHaveText(new RegExp(`^“${quote.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}” — `));
}

export async function openConversation(page, title) {
  await page.locator('#conversation-list button', { hasText: title }).click();
  await expect(page.locator('#thread-title')).toHaveText(title);
}

/** Fill the record at `index` (0-based) in the records list. */
export async function fillRecord(page, index, values) {
  const record = page.locator('li.record').nth(index);
  for (const [field, value] of Object.entries(values)) {
    const input = record.locator(`[data-field=${field}]`);
    if (field === 'role') await input.selectOption(value); else await input.fill(value);
  }
}

/** Trigger a download and return { name, files } with the zip's entries as Buffers keyed by name. */
export async function downloadZip(page, button) {
  const [download] = await Promise.all([page.waitForEvent('download'), page.click(button)]);
  const bytes = readFileSync(await download.path());
  const source = bytesSource(new Uint8Array(bytes));
  const files = {};
  for (const entry of await openZip(source)) files[entry.name] = Buffer.from(await readEntry(source, entry));
  return { name: download.suggestedFilename(), files };
}
