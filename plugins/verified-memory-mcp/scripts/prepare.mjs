// Development-only copies; runtime never imports this script or writes files.
// Single source of truth: never maintain an independent fork of the verifier.
import { copyFileSync, cpSync, rmSync } from 'node:fs';
const here = new URL('../', import.meta.url);
copyFileSync(new URL('../verified-memory/src/pack.ts', here), new URL('src/pack.ts', here));
rmSync(new URL('sample-pack/', here), { recursive: true, force: true });
cpSync(new URL('../verified-memory/sample-pack/', here), new URL('sample-pack/', here), { recursive: true });
