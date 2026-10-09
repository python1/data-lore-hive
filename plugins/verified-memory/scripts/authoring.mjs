// Official authoring CLI, with disposable HOME/state/config and no credentials.
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
const args=process.argv.slice(2);
if(!['build','validate'].includes(args[0])) throw new Error('Expected build or validate');
const home=mkdtempSync(join(tmpdir(),'verified-memory-author-'));
try {
 const config=join(home,'openclaw.json');writeFileSync(config,'{}');
 const child=spawnSync(process.execPath,[resolve('node_modules/openclaw/openclaw.mjs'),'plugins',...args],{
  stdio:'inherit',env:{PATH:process.env.PATH,HOME:home,OPENCLAW_STATE_DIR:join(home,'state'),OPENCLAW_CONFIG_PATH:config,NO_COLOR:'1'}
 });
 if(child.error)throw child.error;
 process.exitCode=child.status ?? 1;
} finally {rmSync(home,{recursive:true,force:true});}
