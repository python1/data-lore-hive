// Development-only copies; runtime never imports this script or writes files.
// Single source of truth: never maintain an independent fork of the verifier.
import { copyFileSync, cpSync, rmSync } from 'node:fs';
const here = new URL('../', import.meta.url);
// Clear stale output so a publish contains only what this build compiled.
rmSync(new URL('dist/', here), { recursive: true, force: true });
for (const file of ['pack.ts', 'verify.ts']) copyFileSync(new URL(`../verified-memory/src/${file}`, here), new URL(`src/${file}`, here));
rmSync(new URL('sample-pack/', here), { recursive: true, force: true });
cpSync(new URL('../verified-memory/sample-pack/', here), new URL('sample-pack/', here), { recursive: true });
