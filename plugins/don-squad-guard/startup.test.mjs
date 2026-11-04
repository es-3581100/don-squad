// Isolated source-contract tests. These use a mock Plugin.define/context and
// DO NOT prove integration with the installed OpenCode plugin API.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const original=fs.readFileSync(path.join(root,'plugins/don-squad-guard/index.js'),'utf8');
const importLine='import { Plugin } from "@opencode/plugin";';
assert.ok(original.startsWith(importLine), 'The fixture expects the guarded Plugin.define import');
const wrapperDir=fs.mkdtempSync(path.join(os.tmpdir(),'don-squad-guard-wrapper-'));
process.on('exit',()=>fs.rmSync(wrapperDir,{recursive:true,force:true}));
const modulePath=path.join(wrapperDir,'guard.mjs');
fs.writeFileSync(modulePath,original.replace(importLine,'const Plugin = { define: value => value };'));
const {default:guard}=await import(pathToFileURL(modulePath).href);
const manifest=JSON.parse(fs.readFileSync(path.join(root,'tools/don-squad/integrity.json'),'utf8'));
const agentIDs=Object.keys(manifest.agents);
const hash=(p)=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const acceptedManifest=()=>({schema_version:'don-squad.integrity.v1',agents:Object.fromEntries(agentIDs.map(id=>[id,hash(path.join(root,'agents',id+'.md'))]))});

function fixture(t,{manifestKind='snapshot',control=true,policyKind='valid',priorHealth=null,missingAgent=null}={}) {
 const base=fs.mkdtempSync(path.join(os.tmpdir(),'don-squad-guard-fixture-'));
 t.after(()=>fs.rmSync(base,{recursive:true,force:true}));
 const configHome=path.join(base,'config');
 const config=path.join(configHome,'opencode');
 const stateHome=path.join(base,'state');
 const state=path.join(stateHome,'don-squad');
 fs.mkdirSync(path.join(config,'agents'),{recursive:true});
 fs.mkdirSync(path.join(config,'tools/don-squad'),{recursive:true});
 for(const id of agentIDs) fs.copyFileSync(path.join(root,'agents',id+'.md'),path.join(config,'agents',id+'.md'));
 if(missingAgent)fs.rmSync(path.join(config,'agents',missingAgent+'.md'));
 let data;
 switch(manifestKind) {
  case 'snapshot':data=manifest;break;
  case 'matching':data=acceptedManifest();break;
  case 'partial':data={schema_version:'don-squad.integrity.v1',agents:{go:manifest.agents.go}};break;
  case 'wrong-id':data=acceptedManifest();data.agents['../escape']='0'.repeat(64);break;
  case 'bad-digest':data=acceptedManifest();data.agents['go']='NOT_A_DIGEST';break;
  case 'missing':break;
  case 'malformed':break;
  default:throw new Error('Unknown manifest fixture');
 }
 const integrityPath=path.join(config,'tools/don-squad/integrity.json');
 if(manifestKind==='malformed') fs.writeFileSync(integrityPath,'{not-json');
 else if(data)fs.writeFileSync(integrityPath,JSON.stringify(data));
 const policyPath=path.join(config,'tools/don-squad/policy.json');
 if(policyKind!=='missing') {
  const p=JSON.parse(fs.readFileSync(path.join(root,'tools/don-squad/policy.json'),'utf8'));
  if(policyKind==='unsafe')p.critical_guard.safe_actions.push('shell');
  fs.writeFileSync(policyPath,JSON.stringify(p));
 }
 if(control)fs.copyFileSync(path.join(root,'tools/don-squad/don-squad-control.mjs'),path.join(config,'tools/don-squad/don-squad-control.mjs'));
 if(priorHealth!==null){fs.mkdirSync(state,{recursive:true});fs.writeFileSync(path.join(state,'health.json'),priorHealth);}
 return {base,configHome,config,stateHome,state,integrityPath,policyPath};
}

async function start(fixtureState) {
 process.env.XDG_CONFIG_HOME=fixtureState.configHome;
 process.env.XDG_STATE_HOME=fixtureState.stateHome;
 const callbacks={};let registeredMCP=null;
 const ctx={
  agent:{transform:async fn=>fn({default:()=>{},update:()=>{}})},
  mcp:{transform:async fn=>fn({set:(_name,value)=>{registeredMCP=value.command;}})},
  session:{hook:async(name,fn)=>{callbacks['session.'+name]=fn;}},
  permission:{hook:async(name,fn)=>{callbacks['permission.'+name]=fn;}},
  tool:{hook:async(name,fn)=>{callbacks['tool.'+name]=fn;}},
  event:{subscribe:async function*(){}}
 };
 const stop=await guard.setup(ctx);
 const healthPath=path.join(fixtureState.state,'health.json');
 const getHealth=()=>JSON.parse(fs.readFileSync(healthPath,'utf8'));
 const authorize=async action=>{
  const event={sessionID:'isolated-test',action,resources:[]};
  await callbacks['permission.evaluate'](event);
  return event.effect==='deny';
 };
 return {stop,authorize,registeredMCP,healthPath,getHealth};
}

async function review(t,config,checks) {
 const f=fixture(t,config),running=await start(f);
 try {await checks(f,running);} finally {running.stop();}
}

test('snapshot retains 11 distinct critical mismatches; shell denied but read allowed',async t=>{
 await review(t,{},async(_f,r)=>{
  const h=r.getHealth();
  assert.equal(h.severity,'critical');
  assert.deepEqual(h.issues.filter(x=>x.active&&x.code==='agent_sha_mismatch').map(x=>x.agent).sort(),
   ['c-family','coder-worker','crossplatform-deployment','don-squad','kolmafia-polyglot','kotlin-family','mobile-deployment','planner','researcher-reviewer','rust','ui-designer'].sort());
  assert.equal(await r.authorize('shell'),true);
  assert.equal(await r.authorize('read'),false);
 });
});

test('a fully matching synthetic manifest imposes no critical guard',async t=>{
 await review(t,{manifestKind:'matching'},async(_f,r)=>{
  assert.equal(r.getHealth().severity,'minor');
  assert.equal(await r.authorize('shell'),false);
  assert.ok(r.registeredMCP && fs.existsSync(r.registeredMCP[1]));
 });
});

for(const kind of ['missing','malformed','partial','wrong-id','bad-digest']){
 test(`${kind} integrity manifest is critical and denies shell`,async t=>{
  await review(t,{manifestKind:kind},async(_f,r)=>{
   assert.equal(r.getHealth().severity,'critical');
   assert.equal(r.getHealth().issues.some(x=>x.code==='integrity_manifest_invalid'),true);
   assert.equal(await r.authorize('shell'),true);
   assert.equal(await r.authorize('read'),false);
  });
 });
}

test('missing agent gets an explicit critical missing-file finding',async t=>{
 await review(t,{manifestKind:'matching',missingAgent:'planner'},async(_f,r)=>{
  assert.ok(r.getHealth().issues.some(x=>x.code==='agent_missing'&&x.agent==='planner'));
  assert.equal(await r.authorize('subagent'),true);
 });
});

test('missing MCP control is critical and never registers a broken command',async t=>{
 await review(t,{manifestKind:'matching',control:false},async(_f,r)=>{
  assert.equal(r.registeredMCP,null);
  assert.ok(r.getHealth().issues.some(x=>x.code==='mcp_control_missing'));
  assert.equal(await r.authorize('shell'),true);
 });
});

test('missing policy is critical even with all matching hashes',async t=>{
 await review(t,{manifestKind:'matching',policyKind:'missing'},async(_f,r)=>{
  assert.ok(r.getHealth().issues.some(x=>x.code==='guard_policy_invalid'));
  assert.equal(await r.authorize('shell'),true);
  assert.equal(await r.authorize('read'),false);
 });
});

test('policy cannot add shell to critical-safe actions',async t=>{
 await review(t,{policyKind:'unsafe'},async(_f,r)=>{
  assert.ok(r.getHealth().issues.some(x=>x.code==='guard_policy_invalid'));
  assert.equal(await r.authorize('shell'),true);
  assert.equal(await r.authorize('read'),false);
 });
});

test('missing or corrupt runtime health denies shell after clean startup',async t=>{
 await review(t,{manifestKind:'matching'},async(_f,r)=>{
  fs.rmSync(r.healthPath);
  assert.equal(await r.authorize('shell'),true);
  fs.writeFileSync(r.healthPath,'{bad-json');
  assert.equal(await r.authorize('shell'),true);
 });
});

test('structurally malformed health is critical even when JSON parses',async t=>{
 await review(t,{manifestKind:'matching'},async(_f,r)=>{
  fs.writeFileSync(r.healthPath,JSON.stringify({severity:'minor',issues:['not-an-issue']}));
  assert.equal(await r.authorize('shell'),true);
 });
});

test('prior corrupt health stays critical until explicitly reconciled',async t=>{
 await review(t,{manifestKind:'matching',priorHealth:'{broken'},async(_f,r)=>{
  assert.ok(r.getHealth().issues.some(x=>x.code==='guard_health_invalid'));
  assert.equal(await r.authorize('shell'),true);
 });
});

test('active critical issue cannot be bypassed by lowering summary severity',async t=>{
 await review(t,{},async(_f,r)=>{
  const h=r.getHealth();h.severity='minor';fs.writeFileSync(r.healthPath,JSON.stringify(h));
  assert.equal(await r.authorize('shell'),true);
 });
});

test('fully validated rescan retires obsolete integrity mismatch issues',async t=>{
 const f=fixture(t);
 const before=await start(f);
 assert.equal(before.getHealth().severity,'critical');before.stop();
 fs.writeFileSync(f.integrityPath,JSON.stringify(acceptedManifest()));
 const after=await start(f);
 try {
  assert.equal(after.getHealth().severity,'minor');
  assert.equal(after.getHealth().issues.some(x=>x.code==='agent_sha_mismatch'&&x.active),false);
 } finally{after.stop();}
});

test('the shipped tools/don-squad MCP executable answers initialize and tools/list',()=>{
 const control=path.join(root,'tools/don-squad/don-squad-control.mjs');
 const body=[JSON.stringify({jsonrpc:'2.0',id:1,method:'initialize'}),JSON.stringify({jsonrpc:'2.0',id:2,method:'tools/list'}),''].join('\n');
 const p=spawnSync(process.execPath,[control],{input:body,encoding:'utf8',timeout:3000});
 assert.equal(p.status,0,p.stderr);
 const replies=p.stdout.trim().split('\n').map(JSON.parse);
 assert.equal(replies[0].result.serverInfo.name,'don-squad-control');
 assert.ok(replies[1].result.tools.some(x=>x.name==='guard_status'));
});
