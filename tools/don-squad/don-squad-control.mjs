#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {emitAgentEnvelope, validateAgentEnvelope, validateAgentJSON} from './agent-io.mjs';
const cfgRoot = process.env.XDG_CONFIG_HOME ? path.join(process.env.XDG_CONFIG_HOME,'opencode') : path.join(os.homedir(),'.config','opencode');
const stateRoot = process.env.XDG_STATE_HOME ? path.join(process.env.XDG_STATE_HOME,'don-squad') : path.join(os.homedir(),'.local','state','don-squad');
const readJSON=(p,f={})=>{try{return JSON.parse(fs.readFileSync(p,'utf8'))}catch{return f}};
const policy=()=>readJSON(path.join(cfgRoot,'tools','don-squad','policy.json'),{});
function send(o){process.stdout.write(JSON.stringify(o)+'\n')}
function result(id,o){send({jsonrpc:'2.0',id,result:{content:[{type:'text',text:JSON.stringify(o)}]}})}
function textResult(id,text){send({jsonrpc:'2.0',id,result:{content:[{type:'text',text}]}})}
function expected(a){return {kind:a.expected_kind,task_id:a.expected_task_id,attempt_id:a.expected_attempt_id,sender:a.expected_sender,recipient:a.expected_recipient}}
function status(){return {policy:policy(),health:readJSON(path.join(stateRoot,'health.json'),{severity:'minor',issues:[]}),latest:readJSON(path.join(stateRoot,'latest.json'),{})}}
const identityProperties={
 expected_kind:{type:'string',enum:['prompt','return']},
 expected_task_id:{type:'string'},
 expected_attempt_id:{type:'string'},
 expected_sender:{type:'string'},
 expected_recipient:{type:'string'}
};
let buf='';process.stdin.setEncoding('utf8');process.stdin.on('data',d=>{buf+=d;let i;while((i=buf.indexOf('\n'))>=0){const line=buf.slice(0,i).trim();buf=buf.slice(i+1);if(!line)continue;let m;try{m=JSON.parse(line)}catch{continue}handle(m)}});
function handle(m){
 if(m.method==='initialize')return send({jsonrpc:'2.0',id:m.id,result:{protocolVersion:'2025-11-25',capabilities:{tools:{}},serverInfo:{name:'don-squad-control',version:'1.1.0'}}});
 if(m.method==='notifications/initialized')return;
 if(m.method==='tools/list')return send({jsonrpc:'2.0',id:m.id,result:{tools:[
  {name:'team_roster',description:'Return Don-Squad lead, roster, authority classes, and depth policy.',inputSchema:{type:'object',properties:{}}},
  {name:'guard_status',description:'Return current Don-Squad guard health without changing it.',inputSchema:{type:'object',properties:{}}},
  {name:'handoff_probe',description:'Legacy shallow routing probe. Does not validate an agent-io/v1 envelope; prefer handoff_validate or handoff_emit.',inputSchema:{type:'object',properties:{from:{type:'string'},status:{type:'string'},next_owner:{type:['string','null']}},required:['from','status']}},
  {name:'handoff_validate',description:'Validate a structured agent-io/v1 envelope object, including required array containers and optional expected identity fields. Does not serialize or execute project work.',inputSchema:{type:'object',properties:{envelope:{type:'object'},...identityProperties},required:['envelope']}},
  {name:'handoff_validate_text',description:'Strictly parse and validate already-authored agent-io/v1 JSON text. Rejects duplicate keys and malformed container syntax.',inputSchema:{type:'object',properties:{raw_json:{type:'string'},...identityProperties},required:['raw_json']}},
  {name:'handoff_emit',description:'Validate a structured agent-io/v1 envelope object and return runtime-owned canonical JSON text. The returned text is the handoff; copy it verbatim instead of hand-authoring JSON punctuation.',inputSchema:{type:'object',properties:{envelope:{type:'object'},...identityProperties},required:['envelope']}}
 ]}});
 if(m.method==='tools/call'){
  const n=m.params?.name,a=m.params?.arguments||{},p=policy();
  if(n==='team_roster')return result(m.id,{lead:p.lead,agents:p.agents,children:p.children,authority:p.authority,depth:p.depth});
  if(n==='guard_status')return result(m.id,status());
  if(n==='handoff_probe')return result(m.id,{valid:(p.children||[]).includes(a.from),returns_to:a.status==='needs_escalation'?'don-squad':(a.next_owner||'don-squad'),user_visible:false,validation_scope:'legacy-shallow'});
  if(n==='handoff_validate')return result(m.id,validateAgentEnvelope(a.envelope,expected(a)));
  if(n==='handoff_validate_text'){
   const checked=validateAgentJSON(a.raw_json,expected(a));
   return result(m.id,{valid:checked.valid,errors:checked.errors});
  }
  if(n==='handoff_emit'){
   const emitted=emitAgentEnvelope(a.envelope,expected(a));
   if(!emitted.valid)return result(m.id,{valid:false,errors:emitted.errors});
   return textResult(m.id,emitted.canonical_json);
  }
  return send({jsonrpc:'2.0',id:m.id,error:{code:-32601,message:'unknown tool'}})
 }
}
