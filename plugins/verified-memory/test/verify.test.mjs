import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { verifyPackEntries } from '../dist/verify.js';
import { loadPack } from '../dist/pack.js';
const sample = resolve('sample-pack');
const hash = b=>createHash('sha256').update(b).digest('hex');
const entries = dir=>Object.fromEntries(readdirSync(dir).map(n=>[n,readFileSync(join(dir,n))]));
const verify = files=>verifyPackEntries(Object.keys(files),n=>files[n],hash);

test('pure verifier has no imports, so it can run outside Node',()=>{
 assert.doesNotMatch(readFileSync('dist/verify.js','utf8'),/^\s*import\b|\brequire\(|\bimport\(/m);
});
test('pure verifier agrees with loadPack on the sample pack',()=>{
 const {records,manifest_sha256}=verify(entries(sample));const pack=loadPack(sample);
 assert.equal(records.size,pack.verification.records);assert.equal(manifest_sha256,pack.verification.manifest_sha256);
 for (const id of records.keys()) assert.deepEqual(records.get(id),pack.get(id));
});
test('pure verifier rejects in-memory tampering with the loader messages',()=>{
 const files=entries(sample);
 const flipped=Buffer.from(files['README.md']);flipped[0]^=1;
 assert.throws(()=>verify({...files,'README.md':flipped}),/^Error: verified-memory: checksum mismatch: README\.md$/);
 const {['MEMORY.md']:_,...three}=files;
 assert.throws(()=>verify(three),/pack must contain exactly four expected files/);
 assert.throws(()=>verify({...files,extra:Buffer.from('x')}),/pack must contain exactly four expected files/);
});
