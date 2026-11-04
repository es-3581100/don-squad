import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import * as moduleExports from './don-squad-v1-guard.js';

const AGENTS=['c-family','coder-worker','crossplatform-deployment','don-squad','go','kolmafia-polyglot','kotlin-family','mobile-deployment','planner','project-planner-hygiene','python','researcher-reviewer','rust','ui-designer','verifier'];
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const write=(p,value)=>{fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,value)};
const json=(p,v)=>write(p,JSON.stringify(v));
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const ownRoot=path.dirname(fileURLToPath(import.meta.url));
const leadSource=fs.readFileSync(path.join(ownRoot,'..','agents','don-squad.md'),'utf8');
const orig={OPENCODE_CONFIG_DIR:process.env.OPENCODE_CONFIG_DIR,XDG_STATE_HOME:process.env.XDG_STATE_HOME};
function fixture(){
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'don-squad-v1-fixture-'));
  const config=path.join(tmp,'config'), state=path.join(tmp,'state');
  process.env.OPENCODE_CONFIG_DIR=config;
  process.env.XDG_STATE_HOME=state;
  const expected={};
  for(const agent of AGENTS){const content=`agent ${agent}\n`;write(path.join(config,'agents',`${agent}.md`),content);expected[agent]=hash(content)}
  const manifest=path.join(config,'tools','don-squad','integrity.json');
  json(manifest,{schema_version:'don-squad.integrity.v1',agents:expected});
  const policy=path.join(config,'tools','don-squad','policy.json');
  json(policy,{schema_version:'don-squad.guard.v1',lead:'don-squad',agents:AGENTS,critical_guard:{safe_actions:['read','glob','grep','webfetch','websearch','skill','question']}});
  const mcp=path.join(config,'tools','don-squad','don-squad-control.mjs');write(mcp,'// MCP stub');
  const health=path.join(state,'don-squad','health.json');
  return {tmp,config,state,manifest,policy,mcp,health,expected,agentPath:a=>path.join(config,'agents',`${a}.md`)};
}
function dispose(f){fs.rmSync(f.tmp,{recursive:true,force:true});for(const [k,v] of Object.entries(orig)){if(v===undefined)delete process.env[k];else process.env[k]=v}}
async function setup(f, ctx={}){const hooks=await moduleExports.DonSquadV1StartupGuard(ctx);assert.equal(typeof hooks['tool.execute.before'],'function');return hooks['tool.execute.before']}
async function denied(h,tool){await assert.rejects(()=>h({tool},{}),/critical integrity state/)}
async function allowed(h,tool){await assert.doesNotReject(()=>h({tool},{}))}
function runCase(name,fn){test(name,async()=>{const f=fixture();try{await fn(f)}finally{dispose(f)}})}

runCase('single V1 discoverable named factory (no V2 dependency)',async f=>{
 assert.deepEqual(Object.keys(moduleExports),['DonSquadV1StartupGuard']);
 assert.equal(typeof moduleExports.DonSquadV1StartupGuard,'function');
 const h=await setup(f);assert.equal(read(f.health).severity,'minor');
 await allowed(h,'bash'); // native V1 agent permission denies bash independently
});
runCase('all 11 observed-style mismatches preserved as distinct issues',async f=>{
 for(const agent of AGENTS.slice(0,11))write(f.agentPath(agent),'different bytes');
 const h=await setup(f);const issues=read(f.health).issues.filter(x=>x.code==='agent_sha_mismatch');
 assert.equal(issues.length,11);assert.equal(new Set(issues.map(x=>x.agent)).size,11);
 for(const t of ['bash','edit','task','mcp_bridge','apply_patch','write','unknown'])await denied(h,t);
});
runCase('read-only builtins allowed during critical',async f=>{
 write(f.agentPath('don-squad'),'mismatched');const h=await setup(f);
 for(const tool of ['read','glob','grep','webfetch','websearch','skill','question'])await allowed(h,tool);
});
runCase('missing manifest is critical',async f=>{
 fs.unlinkSync(f.manifest);const h=await setup(f);assert.equal(read(f.health).severity,'critical');await denied(h,'bash');
});
runCase('malformed manifest is critical',async f=>{
 write(f.manifest,'{garbage');const h=await setup(f);assert.ok(read(f.health).issues.some(x=>x.code==='integrity_manifest_invalid'));await denied(h,'task');
});
runCase('truncated roster is critical',async f=>{
 const m=read(f.manifest);delete m.agents['verifier'];json(f.manifest,m);const h=await setup(f);await denied(h,'edit');
});
runCase('unexpected roster entry is critical',async f=>{
 const m=read(f.manifest);m.agents.evil='a'.repeat(64);json(f.manifest,m);const h=await setup(f);await denied(h,'bash');
});
runCase('wrong digest format is critical',async f=>{
 const m=read(f.manifest);m.agents.go='NOT_SHA';json(f.manifest,m);const h=await setup(f);await denied(h,'bash');
});
runCase('invalid policy is critical',async f=>{
 write(f.policy,'[]');const h=await setup(f);await denied(h,'task');
});
runCase('policy cannot expand privileged safe actions',async f=>{
 const p=read(f.policy);p.critical_guard.safe_actions.push('bash');json(f.policy,p);const h=await setup(f);await denied(h,'bash');
});
runCase('missing MCP executable is critical but not auto-registered',async f=>{
 fs.unlinkSync(f.mcp);const h=await setup(f);assert.ok(read(f.health).issues.some(x=>x.code==='mcp_control_missing'));await denied(h,'bash');
});
runCase('manifest symlink is rejected',async f=>{
 const elsewhere=path.join(f.tmp,'elsewhere.json');fs.renameSync(f.manifest,elsewhere);fs.symlinkSync(elsewhere,f.manifest);const h=await setup(f);await denied(h,'bash');
});
runCase('agent symlink is rejected',async f=>{
 const elsewhere=path.join(f.tmp,'agent.txt');fs.renameSync(f.agentPath('go'),elsewhere);fs.symlinkSync(elsewhere,f.agentPath('go'));const h=await setup(f);await denied(h,'bash');
});
runCase('live file drift after initialized normal is blocked',async f=>{
 const h=await setup(f);assert.equal(read(f.health).severity,'minor');write(f.agentPath('go'),'live drift');await denied(h,'task');assert.equal(read(f.health).severity,'critical');
});
runCase('deleted health after initial startup fails closed',async f=>{
 const h=await setup(f);fs.unlinkSync(f.health);await denied(h,'bash');assert.ok(read(f.health).issues.some(x=>x.code==='guard_health_unavailable'));
});
runCase('corrupt health after initial startup fails closed and stays critical',async f=>{
 const h=await setup(f);write(f.health,'{corrupt');await denied(h,'bash');await denied(h,'bash');assert.ok(read(f.health).issues.some(x=>x.code==='guard_health_invalid'));
});
runCase('previous unrelated critical finding is preserved',async f=>{
 json(f.health,{severity:'critical',issues:[{code:'owner_hold',active:true,severity:'critical'}]});const h=await setup(f);await denied(h,'bash');assert.ok(read(f.health).issues.some(x=>x.code==='owner_hold'));
});
runCase('lead native V1 permissions deny mutation/delegation independently of hook',async f=>{
 assert.match(leadSource,/^permission:\n\s+"\*": deny/m);
 const v1=leadSource.split('permission:')[1].split('permissions:')[0];
 for(const name of ['bash','edit','task','external_directory']) assert.match(v1,new RegExp('\\b'+name+': deny'));
 for(const name of ['read','glob','grep','skill','question']) assert.match(v1,new RegExp('\\b'+name+': allow'));
});

runCase('project-local agent override is critical even when global hash matches',async f=>{
 const project=path.join(f.tmp,'project');
 write(path.join(project,'.opencode','agents','don-squad.md'),'project override');
 const h=await setup(f,{directory:project});
 assert.ok(read(f.health).issues.some(x=>x.code==='project_agent_override_unverified'));
 await denied(h,'bash');
});
runCase('ancestor agent override is critical',async f=>{
 const project=path.join(f.tmp,'parent','child');
 write(path.join(f.tmp,'parent','.opencode','agents','verifier.md'),'ancestor override');
 const h=await setup(f,{directory:project});
 await denied(h,'task');
});
runCase('runtime config overlay is not trusted implicitly',async f=>{
 process.env.OPENCODE_CONFIG_CONTENT='{ "agent": {"don-squad": {"permission": "allow"}} }';
 try{
  const h=await setup(f);assert.ok(read(f.health).issues.some(x=>x.code==='runtime_config_overlay_unverified'));
  await denied(h,'bash');
 }finally{delete process.env.OPENCODE_CONFIG_CONTENT}
});
runCase('malformed existing issue cannot lower critical health',async f=>{
 json(f.health,{severity:'minor',issues:[{active:true,code:'bad',severity:'banana'}]});
 const h=await setup(f);await denied(h,'bash');
 assert.ok(read(f.health).issues.some(x=>x.code==='guard_health_invalid'));
});
