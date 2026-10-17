// One command for every automated suite, as CI runs it on macOS and Windows:
//   node scripts/test-all.mjs        (from plugins/verified-memory-mcp, after npm ci in
//                                     ../verified-memory, here and web/)
// It runs the OpenClaw plugin tests (shared verifier), the MCP server tests (including the
// red-team rounds R1–R6 in test/redteam.test.mjs), the pack maker's unit tests and the Claude
// Desktop bundle tests, in that order, and exits nonzero if any of them failed. The browser
// end-to-end tests (Playwright) are separate: npm run test:e2e in web/.
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('../', import.meta.url));
const suites = [
  ['OpenClaw plugin and shared verifier', '../verified-memory', ['test']],
  ['MCP server, sign-pack and red-team rounds', '.', ['test']],
  ['pack maker unit tests', 'web', ['test']],
  ['Claude Desktop bundle', '.', ['run', 'test:mcpb']]
];
const results = [];
for (const [name, dir, args] of suites) {
  process.stdout.write(`\n=== ${name} (npm ${args.join(' ')} in ${dir}) ===\n`);
  // shell: npm is npm.cmd on Windows; every argument is a fixed literal.
  const run = spawnSync('npm', args, { cwd: join(here, dir), stdio: 'inherit', shell: process.platform === 'win32' });
  results.push([name, run.status === 0]);
}
process.stdout.write('\n=== summary ===\n' + results.map(([name, ok]) => `${ok ? 'pass' : 'FAIL'}  ${name}`).join('\n') + '\n');
process.exitCode = results.every(([, ok]) => ok) ? 0 : 1;
