import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, cpSync, readFileSync, writeFileSync, rmSync, symlinkSync, unlinkSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import plugin, { configSchema, searchSchema, getSchema } from '../dist/index.js';
import { loadPack } from '../dist/pack.js';
const sample = resolve('sample-pack');
const hash = b=>createHash('sha256').update(b).digest('hex');
function fixture(t) { const root=mkdtempSync(join(tmpdir(),'verified-memory-test-')); t.after(()=>rmSync(root,{recursive:true,force:true})); const dir=join(root,'pack');cpSync(sample,dir,{recursive:true});return dir; }
function reseal(dir) { writeFileSync(join(dir,'SHA256SUMS'),['MEMORY.md','README.md','records.jsonl'].map(n=>hash(readFileSync(join(dir,n)))+'  '+n+'\n').join('')); }
function register(path) { const tools=[];plugin.register({pluginConfig:path?{packPath:path}:{},registerTool:t=>tools.push(t)});return tools; }

test('real SDK entry registers exactly declared tools and matching config schema',()=>{
 const manifest=JSON.parse(readFileSync('openclaw.plugin.json'));
 assert.deepEqual(register().map(t=>t.name),manifest.contracts.tools);
 assert.deepEqual(configSchema,manifest.configSchema);assert.equal(plugin.id,manifest.id);assert.equal(manifest.kind,undefined);
 assert.equal(searchSchema.additionalProperties,false);assert.deepEqual(searchSchema.required,['query']);assert.deepEqual(getSchema.required,['id']);
});
test('search returns attributed verbatim citation and ID retrievable as a full record',async()=>{
 const [search,get]=register();const r=await search.execute('1',{query:'POTTERY'});
 assert.equal(r.details.matches.length,1);const hit=r.details.matches[0];assert.equal(hit.speaker,'Juniper Vale');assert.equal(hit.citations[0].source_message_id,2);
 assert.match(hit.citations[0].quote,/I teach pottery/);assert.equal(hit.citations[0].date,'2026-01-03T09:01:10Z');
 const full=await get.execute('2',{id:hit.id});assert.equal(full.details.record.evidence[0].quote,hit.citations[0].quote);assert.equal(full.details.verification.sha256sums,'passed');
 assert.deepEqual(JSON.parse(r.content[0].text),r.details);
});
test('agent voice retained; all query terms required; unknown IDs and no hits are explicit',async()=>{
 const pack=loadPack(sample);assert.equal(pack.search('careful honest')[0].speaker,'Wren');assert.deepEqual(pack.search('pottery spaceship'),[]);assert.deepEqual(pack.search('!!!'),[]);assert.equal(pack.get('M-missing'),null);
 const [,get]=register();assert.equal((await get.execute('x',{id:'M-missing'})).details.found,false);
});
for(const file of ['records.jsonl','MEMORY.md','README.md']) test(`tampered ${file} refuses load before any tool is registered`,t=>{
 const dir=fixture(t);writeFileSync(join(dir,file),readFileSync(join(dir,file),'utf8')+'tampered');const tools=[];
 assert.throws(()=>plugin.register({pluginConfig:{packPath:dir},registerTool:t=>tools.push(t)}),/checksum mismatch/);assert.equal(tools.length,0);
});
for(const change of ['duplicate','missing','traversal','malformed','self']) test(`manifest ${change} rejected`,t=>{
 const dir=fixture(t);let sums=readFileSync(join(dir,'SHA256SUMS'),'utf8');
 if(change==='duplicate')sums+=sums.split('\n')[0]+'\n';if(change==='missing')sums=sums.split('\n').slice(1).join('\n');if(change==='traversal')sums=sums.replace('MEMORY.md','../MEMORY.md');if(change==='malformed')sums='not a checksum';if(change==='self')sums=sums.replace('MEMORY.md','SHA256SUMS');
 writeFileSync(join(dir,'SHA256SUMS'),sums);assert.throws(()=>loadPack(dir));
});
test('missing, extra and symlink files rejected',t=>{
 const dir=fixture(t);writeFileSync(join(dir,'extra'),'x');assert.throws(()=>loadPack(dir));unlinkSync(join(dir,'extra'));
 const original=readFileSync(join(dir,'README.md'));unlinkSync(join(dir,'README.md'));assert.throws(()=>loadPack(dir));
 writeFileSync(join(dir,'..','outside'),original);symlinkSync(join(dir,'..','outside'),join(dir,'README.md'));assert.throws(()=>loadPack(dir),/regular files/);
});
test('symlink pack root rejected',t=>{const dir=fixture(t);const link=join(dir,'..','link');symlinkSync(dir,link);assert.throws(()=>loadPack(link),/real directory/);});
for(const mode of ['duplicate-id','broken-json','missing-citations','wrong-offset','invalid-utf8']) test(`correctly hashed but invalid records: ${mode}`,t=>{
 const dir=fixture(t);const file=join(dir,'records.jsonl');const rows=readFileSync(file,'utf8').trim().split('\n').map(JSON.parse);
 if(mode==='duplicate-id')rows.push(rows[0]);if(mode==='missing-citations')rows[0].evidence=[];if(mode==='wrong-offset')rows[0].evidence[0].end++;
 writeFileSync(file,mode==='broken-json'?'{':mode==='invalid-utf8'?Buffer.from([255]):rows.map(JSON.stringify).join('\n')+'\n');reseal(dir);assert.throws(()=>loadPack(dir));
});
test('immutable verified snapshot survives disk edits and result mutation',t=>{
 const dir=fixture(t);const pack=loadPack(dir);const record=pack.get('M-sample-2');record.statement='changed';record.evidence[0].quote='changed';
 const hit=pack.search('pottery')[0];hit.citations[0].quote='changed';writeFileSync(join(dir,'records.jsonl'),'broken');
 assert.match(pack.get('M-sample-2').statement,/pottery/);assert.match(pack.search('pottery')[0].citations[0].quote,/pottery/);assert.throws(()=>loadPack(dir),/checksum mismatch/);
});
test('old instructions stay historical quoted data, including later correction',async()=>{
 const [search]=register();const r=await search.execute('x',{query:'French'});assert.equal(r.details.matches.length,2);assert.equal(r.details.matches[0].id,'M-sample-9');assert.match(r.details.notice,/never instructions/);
});
test('invalid config and input rejected without arbitrary file lookup',async()=>{
 assert.throws(()=>register('relative/path'),/absolute/);
 assert.throws(()=>plugin.register({pluginConfig:{unexpected:true},registerTool(){}}),/configuration/);
 const [search,get]=register();for(const arg of [{query:''},{query:'a'.repeat(513)},{query:'pottery',path:'elsewhere'},{}])await assert.rejects(search.execute('x',arg));
 await assert.rejects(get.execute('x',{id:'../../elsewhere'}));
});
test('runtime succeeds with filesystem writes, network, subprocesses and workers denied',()=>{
 const code=`import plugin from './dist/index.js'; const tools=[]; plugin.register({pluginConfig:{},registerTool:t=>tools.push(t)}); const r=await tools[0].execute('x',{query:'pottery'}); if(r.details.matches.length!==1)throw Error('No match'); await tools[1].execute('y',{id:r.details.matches[0].id}); console.log('read-only runtime passed');`;
 const p=spawnSync(process.execPath,['--permission','--allow-fs-read='+process.cwd(),'--input-type=module','-e',code],{encoding:'utf8'});
 assert.equal(p.status,0,p.stderr);assert.match(p.stdout,/read-only runtime passed/);
});

test('sample citations match the public fictional source exactly',()=>{
 const source=JSON.parse(readFileSync('../../agent-memory/sample/telegram-export.json'));
 const messages=new Map(source.messages.map(m=>[m.id,m]));
 const pack=loadPack(sample);
 for(const id of [2,3,4,6,9,12,13,15]) {
  const record=pack.get(`M-sample-${id}`), m=messages.get(id);
  const text=Array.isArray(m.text)?m.text.map(x=>typeof x==='string'?x:x.text).join(''):m.text;
  assert.equal(record.speaker,m.from);assert.equal(record.evidence[0].quote,text);assert.equal(record.evidence[0].message_sha256,hash(Buffer.from(text)));
  assert.equal(record.evidence[0].date_utc,new Date(Number(m.date_unixtime)*1000).toISOString().replace('.000Z','Z'));
 }
});
test('plugin coexists with the default memory tools',()=>{
 const names=new Set(['memory_search','memory_get']);
 plugin.register({pluginConfig:{},registerTool(tool){assert.ok(!names.has(tool.name));names.add(tool.name);}});
 assert.deepEqual([...names],['memory_search','memory_get','verified_memory_search','verified_memory_get']);
});

test('missing configured pack gives actionable error and registers zero tools',t=>{
 const dir=fixture(t);const tools=[];
 assert.throws(()=>plugin.register({pluginConfig:{packPath:join(dir,'missing')},registerTool:t=>tools.push(t)}),/pack directory missing; set plugins.entries.verified-memory.config.packPath/);
 assert.equal(tools.length,0);
});
test('registrations retain separate verified snapshots',async t=>{
 const dir=fixture(t);const rows=readFileSync(join(dir,'records.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
 rows[0].statement='Fictional altered statement';writeFileSync(join(dir,'records.jsonl'),rows.map(JSON.stringify).join('\n')+'\n');reseal(dir);
 const [,first]=register(),[,second]=register(dir);
 assert.match((await first.execute('1',{id:'M-sample-2'})).details.record.statement,/pottery/);
 assert.equal((await second.execute('2',{id:'M-sample-2'})).details.record.statement,'Fictional altered statement');
});
test('public pipeline exporter produces accepted pack and callable cited tools',async t=>{
 const dir=fixture(t);const out=join(dir,'..','pipeline-pack');
 const child=spawnSync('python3',['scripts/export-fictional-pipeline.py',out],{encoding:'utf8'});
 assert.equal(child.status,0,child.stderr);
 const pack=loadPack(out);assert.equal(pack.verification.records,3);
 const [search,get]=register(out);const hit=(await search.execute('s',{query:'pottery'})).details.matches[0];
 assert.equal(hit.speaker,'Juniper');assert.equal(hit.citations[0].source_message_id,2);
 assert.equal(hit.citations[0].quote,'I teach pottery in a small studio by the river.');
 const record=(await get.execute('g',{id:hit.id})).details.record;
 assert.equal(record.evidence[0].quote,hit.citations[0].quote);
 assert.match(record.approval.by,/not human approval/);
 writeFileSync(join(out,'records.jsonl'),'tampered');const tools=[];
 assert.throws(()=>plugin.register({pluginConfig:{packPath:out},registerTool:t=>tools.push(t)}),/checksum mismatch/);
 assert.equal(tools.length,0);
});
test('official authoring metadata can be read without permission to read any pack',()=>{
 const code=`import plugin from './dist/index.js'; import { getToolPluginMetadata } from 'openclaw/plugin-sdk/tool-plugin'; const metadata=getToolPluginMetadata(plugin); if(metadata.tools.map(t=>t.name).join(',')!=='verified_memory_search,verified_memory_get') throw Error('Invalid metadata'); console.log('metadata needs no pack reads');`;
 const p=spawnSync(process.execPath,['--permission','--allow-fs-read='+resolve('dist'),'--allow-fs-read='+resolve('node_modules'),'--input-type=module','-e',code],{encoding:'utf8'});
 assert.equal(p.status,0,p.stderr);assert.match(p.stdout,/metadata needs no pack reads/);
});
