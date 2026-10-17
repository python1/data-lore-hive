// TEMPORARY diagnostic for Windows CI; removed before merge.
import test from 'node:test';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
test('diag: ssh-keygen on this runner', { skip: process.platform !== 'win32' }, () => {
  const root = mkdtempSync(join(tmpdir(), 'diag-')), key = join(root, 'k'), file = join(root, 'f');
  writeFileSync(file, 'hello\n');
  const show = (label, r) => console.log(`DIAG ${label}: status=${r.status} error=${r.error} out=${JSON.stringify(r.stdout)} err=${JSON.stringify(r.stderr)}`);
  show('where', spawnSync('where', ['ssh-keygen'], { encoding: 'utf8', shell: true }));
  show('keygen', spawnSync('ssh-keygen', ['-q', '-t', 'ed25519', '-N', '', '-f', key], { encoding: 'utf8' }));
  show('sign-fullenv', spawnSync('ssh-keygen', ['-Y', 'sign', '-f', key, '-n', 'verified-memory-pack-v1', file], { encoding: 'utf8' }));
  show('sign-minenv', spawnSync('ssh-keygen', ['-Y', 'sign', '-f', key, '-n', 'verified-memory-pack-v1', file], { encoding: 'utf8', env: { PATH: process.env.PATH, HOME: root, SystemRoot: process.env.SystemRoot, USERPROFILE: root } }));
  show('sign-stdin-ignore', spawnSync('ssh-keygen', ['-Y', 'sign', '-f', key, '-n', 'verified-memory-pack-v1', file], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }));
  show('icacls', spawnSync('icacls', [key], { encoding: 'utf8' }));
});
