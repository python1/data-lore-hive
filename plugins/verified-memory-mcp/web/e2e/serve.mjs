// Test-only static server: serves dist/index.html at / and /index.html, nothing else.
// Logs every other request path to stderr so an unexpected request is visible in test output.
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const port = Number(process.argv[2] ?? 4173);
const page = () => readFileSync(fileURLToPath(new URL('../dist/index.html', import.meta.url)));
createServer((req, res) => {
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
    res.end(page());
    return;
  }
  process.stderr.write(`serve.mjs: unexpected request ${req.method} ${req.url}\n`);
  res.writeHead(404).end();
}).listen(port, '127.0.0.1');
