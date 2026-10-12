// Browser tests for dist/index.html in Chromium, Firefox and WebKit, both served over http
// (as GitHub Pages would) and opened from disk (file://). Run with `npm run test:e2e`.
import { defineConfig, devices } from '@playwright/test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const PORT = 4173;
const httpUrl = `http://127.0.0.1:${PORT}/`;
const fileUrl = pathToFileURL(fileURLToPath(new URL('dist/index.html', import.meta.url))).href;
const browsers = [['chromium', devices['Desktop Chrome']], ['firefox', devices['Desktop Firefox']], ['webkit', devices['Desktop Safari']]];

export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  reporter: 'list',
  use: { acceptDownloads: true },
  webServer: { command: `node e2e/serve.mjs ${PORT}`, url: httpUrl, reuseExistingServer: !process.env.CI },
  projects: browsers.flatMap(([name, device]) => [
    { name: `${name}-http`, use: { ...device, pageUrl: httpUrl } },
    { name: `${name}-file`, use: { ...device, pageUrl: fileUrl } }
  ])
});
