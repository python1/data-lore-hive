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
  const pkey = join(root, 'pk'), askpass = join(root, 'askpass.cmd'), f2 = join(root, 'f2');
  writeFileSync(askpass, '@echo fictional passphrase\r\n'); writeFileSync(f2, 'x\n');
  show('keygen-pass', spawnSync('ssh-keygen', ['-q', '-t', 'ed25519', '-N', 'fictional passphrase', '-f', pkey], { encoding: 'utf8' }));
  show('sign-askpass', spawnSync('ssh-keygen', ['-Y', 'sign', '-f', pkey, '-n', 'verified-memory-pack-v1', f2], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, SSH_ASKPASS: askpass, SSH_ASKPASS_REQUIRE: 'force', DISPLAY: ':0' } }));
  show('icacls', spawnSync('icacls', [key], { encoding: 'utf8' }));
});
