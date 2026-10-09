// Development validation only: isolated host state and fictional fixture copies.
import { mkdtempSync, mkdirSync, cpSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
const pluginRoot=resolve('.');
const root=mkdtempSync(join(tmpdir(),'verified-memory-host-'));
const summaries=[];
try {
 for(const name of ['valid','pipeline','missing','tampered','malformed']) {
  const dir=join(root,name);mkdirSync(dir);const pack=join(dir,'pack');
  if(name==='pipeline') {
   const exporter=spawnSync('python3',[join(pluginRoot,'scripts/export-fictional-pipeline.py'),pack],{encoding:'utf8'});
   assert.equal(exporter.status,0,exporter.stderr);
  } else if(name!=='missing') cpSync(join(pluginRoot,'sample-pack'),pack,{recursive:true});
  if(name==='tampered')writeFileSync(join(pack,'records.jsonl'),'tampered');
  if(name==='malformed') {
   writeFileSync(join(pack,'records.jsonl'),'{broken json\n');
   writeFileSync(join(pack,'SHA256SUMS'),['MEMORY.md','README.md','records.jsonl'].map(n=>createHash('sha256').update(readFileSync(join(pack,n))).digest('hex')+'  '+n+'\n').join(''));
  }
  const config=join(dir,'openclaw.json');
  writeFileSync(config,JSON.stringify({plugins:{allow:['verified-memory'],load:{paths:[pluginRoot]},entries:{'verified-memory':{enabled:true,config:{packPath:pack}}}}}));
  const child=spawnSync(process.execPath,[join(pluginRoot,'node_modules/openclaw/openclaw.mjs'),'plugins','inspect','verified-memory','--runtime','--json'],{
   encoding:'utf8',timeout:120000,maxBuffer:4*1024*1024,
   env:{PATH:process.env.PATH,HOME:dir,OPENCLAW_STATE_DIR:join(dir,'state'),OPENCLAW_CONFIG_PATH:config,NO_COLOR:'1'}
  });
  assert.ifError(child.error);
  const output=JSON.parse(child.stdout);
  if(name==='valid' || name==='pipeline') {
   assert.equal(output.plugin.status,'loaded');assert.deepEqual(output.plugin.toolNames,['verified_memory_search','verified_memory_get']);assert.deepEqual(output.diagnostics,[]);
  } else {
   assert.notEqual(output.plugin.status,'loaded');assert.deepEqual(output.plugin.toolNames,[]);
  }
  summaries.push({case:name,status:output.plugin.status,tools:output.plugin.toolNames,expected:['valid','pipeline'].includes(name)?'loaded':'refused',passed:true});
 }
 console.log(JSON.stringify({node:process.version,openclaw:JSON.parse(readFileSync(join(pluginRoot,'node_modules/openclaw/package.json'))).version,cases:summaries},null,2));
} finally {rmSync(root,{recursive:true,force:true});}
