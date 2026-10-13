// Development validation only: isolated host state and fictional fixture copies.
import { mkdtempSync, mkdirSync, cpSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
import { newKey, sshsig } from '../test/sshsig.mjs';
const pluginRoot=resolve('.');
const root=mkdtempSync(join(tmpdir(),'verified-memory-host-'));
const summaries=[];
// Signed cases use the committed fictional fixture; its private key no longer exists.
const fixtureSig=join(pluginRoot,'test/fixtures/signed-sample');
const trustedKeys=[readFileSync(join(fixtureSig,'trusted_keys'),'utf8')];
// Dated cases are signed in memory with an invented key, as sign-pack would sign them.
const dateKey=newKey(),dateTrust=[dateKey.line('fictional-publisher')];
const iso=ms=>new Date(Math.floor(ms/1000)*1000).toISOString().replace('.000Z','Z');
const DAY=86400000,now=Date.now();
function dated(pack,created,expires){
 writeFileSync(join(pack,'PACK.json'),JSON.stringify({format:'verified-memory-pack',version:2,created_utc:iso(created),expires_utc:iso(expires)})+'\n');
 writeFileSync(join(pack,'SHA256SUMS'),['MEMORY.md','PACK.json','README.md','records.jsonl'].map(n=>createHash('sha256').update(readFileSync(join(pack,n))).digest('hex')+'  '+n+'\n').join(''));
 writeFileSync(join(pack,'SHA256SUMS.sig'),sshsig(dateKey,readFileSync(join(pack,'SHA256SUMS'))));
}
const LOADS=['valid','pipeline','signed-trusted','signed-undated-required','dated-fresh-strict','dated-expired','dated-expired-required'];
try {
 for(const name of ['valid','pipeline','missing','tampered','malformed','signed-trusted','unsigned-strict','unsigned-required','signed-undated-strict','signed-undated-required','signed-invalid','dated-fresh-strict','dated-expired','dated-expired-required','dated-expired-strict']) {
  const dir=join(root,name);mkdirSync(dir);const pack=join(dir,'pack');
  if(name==='pipeline') {
   const exporter=spawnSync('python3',[join(pluginRoot,'scripts/export-fictional-pipeline.py'),pack],{encoding:'utf8'});
   assert.equal(exporter.status,0,exporter.stderr);
  } else if(name!=='missing') cpSync(join(pluginRoot,'sample-pack'),pack,{recursive:true});
  if(name==='tampered')writeFileSync(join(pack,'records.jsonl'),'tampered');
  if(name.startsWith('signed-'))cpSync(join(fixtureSig,'SHA256SUMS.sig'),join(pack,'SHA256SUMS.sig'));
  if(name==='signed-invalid')writeFileSync(join(pack,'SHA256SUMS.sig'),readFileSync(join(pack,'SHA256SUMS.sig'),'utf8').replace('-----END','x\n-----END'));
  if(name.startsWith('dated-'))dated(pack,name.includes('expired')?now-60*DAY:now-DAY,name.includes('expired')?now-DAY:now+30*DAY);
  const mode=name.endsWith('-strict')?{strict:true}:name.endsWith('-required')?{requireSignature:true}:{};
  const signing=name.startsWith('dated-')?{trustedKeys:dateTrust,...mode}:name.startsWith('signed-')||name.startsWith('unsigned-')?{trustedKeys,...mode}:{};
  if(name==='malformed') {
   writeFileSync(join(pack,'records.jsonl'),'{broken json\n');
   writeFileSync(join(pack,'SHA256SUMS'),['MEMORY.md','README.md','records.jsonl'].map(n=>createHash('sha256').update(readFileSync(join(pack,n))).digest('hex')+'  '+n+'\n').join(''));
  }
  const config=join(dir,'openclaw.json');
  writeFileSync(config,JSON.stringify({plugins:{allow:['verified-memory'],load:{paths:[pluginRoot]},entries:{'verified-memory':{enabled:true,config:{packPath:pack,...signing}}}}}));
  const child=spawnSync(process.execPath,[join(pluginRoot,'node_modules/openclaw/openclaw.mjs'),'plugins','inspect','verified-memory','--runtime','--json'],{
   encoding:'utf8',timeout:120000,maxBuffer:4*1024*1024,
   env:{PATH:process.env.PATH,HOME:dir,OPENCLAW_STATE_DIR:join(dir,'state'),OPENCLAW_CONFIG_PATH:config,NO_COLOR:'1'}
  });
  assert.ifError(child.error);
  const output=JSON.parse(child.stdout);
  if(LOADS.includes(name)) {
   assert.equal(output.plugin.status,'loaded');assert.deepEqual(output.plugin.toolNames,['verified_memory_search','verified_memory_get']);assert.deepEqual(output.diagnostics,[]);
  } else {
   assert.notEqual(output.plugin.status,'loaded');assert.deepEqual(output.plugin.toolNames,[]);
  }
  summaries.push({case:name,status:output.plugin.status,tools:output.plugin.toolNames,expected:LOADS.includes(name)?'loaded':'refused',passed:true});
 }
 console.log(JSON.stringify({node:process.version,openclaw:JSON.parse(readFileSync(join(pluginRoot,'node_modules/openclaw/package.json'))).version,cases:summaries},null,2));
} finally {rmSync(root,{recursive:true,force:true});}
