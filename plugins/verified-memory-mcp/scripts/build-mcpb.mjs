// Builds the Claude Desktop bundle (build/verified-memory-<version>.mcpb) from the same
// dist/ that npm ships, plus production node_modules from the same lockfile. Run after
// `npm run build`. Nothing here signs anything: no keys are read or written.
import { copyFileSync, cpSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { packExtension, validateManifest } from '@anthropic-ai/mcpb';

const root = fileURLToPath(new URL('../', import.meta.url));
const build = join(root, 'build');
const stage = join(build, 'mcpb-stage');
const { version } = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const manifest = JSON.parse(readFileSync(join(root, 'mcpb/manifest.json'), 'utf8'));
if (manifest.version !== version) throw new Error(`mcpb/manifest.json version ${manifest.version} does not match package.json ${version}`);

rmSync(build, { recursive: true, force: true });
mkdirSync(stage, { recursive: true });
// Explicit allowlist: no sample pack, tests, web/, examples or tools.
for (const file of ['package.json', 'package-lock.json', 'README.md', 'LICENSE']) copyFileSync(join(root, file), join(stage, file));
copyFileSync(join(root, 'mcpb/manifest.json'), join(stage, 'manifest.json'));
cpSync(join(root, 'dist'), join(stage, 'dist'), { recursive: true, filter: src => !src.endsWith('.d.ts') });
// shell: npm is npm.cmd on Windows; every argument is a fixed literal.
execFileSync('npm', ['ci', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund'], { cwd: stage, stdio: 'inherit', shell: process.platform === 'win32' });
rmSync(join(stage, 'package-lock.json'));
rmSync(join(stage, 'node_modules/.package-lock.json'), { force: true });

if (!validateManifest(stage)) throw new Error('manifest.json failed MCPB schema validation');
const output = join(build, `verified-memory-${version}.mcpb`);
if (!(await packExtension({ extensionPath: stage, outputPath: output, silent: true }))) throw new Error('mcpb pack failed');
console.log(output);
