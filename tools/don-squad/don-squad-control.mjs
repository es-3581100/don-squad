#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
const cfgRoot = process.env.XDG_CONFIG_HOME ? path.join(process.env.XDG_CONFIG_HOME,'opencode') : path.join(os.homedir(),'.config','opencode');
const stateRoot = process.env.XDG_STATE_HOME ? path.join(process.env.XDG_STATE_HOME,'don-squad') : path.join(os.homedir(),'.local','state','don-squad');
const readJSON=(p,f={})=>{try{return JSON.parse(fs.readFileSync(p,'utf8'))}catch{return f}};
const policy=()=>readJSON(path.join(cfgRoot,'tools','don-squad','policy.json'),{});
function send(o){process.stdout.write(JSON.stringify(o)+'\n')}
function result(id,o){send({jsonrpc:'2.0',id,result:{content:[{type:'text',text:JSON.stringify(o)}]}})}
function status(){return {policy:policy(),health:readJSON(path.join(stateRoot,'health.json'),{severity:'minor',issues:[]}),latest:readJSON(path.join(stateRoot,'latest.json'),{})}}
let buf='';process.stdin.setEncoding('utf8');process.stdin.on('data',d=>{buf+=d;let i;while((i=buf.indexOf('\n'))>=0){const line=buf.slice(0,i).trim();buf=buf.slice(i+1);if(!line)continue;let m;try{m=JSON.parse(line)}catch{continue}handle(m)}});
function handle(m){
 if(m.method==='initialize')return send({jsonrpc:'2.0',id:m.id,result:{protocolVersion:'2025-11-25',capabilities:{tools:{}},serverInfo:{name:'don-squad-control',version:'1.0.0'}}});
 if(m.method==='notifications/initialized')return;
 if(m.method==='tools/list')return send({jsonrpc:'2.0',id:m.id,result:{tools:[
  {name:'team_roster',description:'Return Don-Squad lead, roster, authority classes, and depth policy.',inputSchema:{type:'object',properties:{}}},
  {name:'guard_status',description:'Return current Don-Squad guard health without changing it.',inputSchema:{type:'object',properties:{}}},
  {name:'handoff_probe',description:'Validate an internal handoff envelope without executing project work.',inputSchema:{type:'object',properties:{from:{type:'string'},status:{type:'string'},next_owner:{type:['string','null']}},required:['from','status']}}
 ]}});
 if(m.method==='tools/call'){const n=m.params?.name,a=m.params?.arguments||{},p=policy();if(n==='team_roster')return result(m.id,{lead:p.lead,agents:p.agents,children:p.children,authority:p.authority,depth:p.depth});if(n==='guard_status')return result(m.id,status());if(n==='handoff_probe')return result(m.id,{valid:(p.children||[]).includes(a.from),returns_to:a.status==='needs_escalation'?'don-squad':(a.next_owner||'don-squad'),user_visible:false});return send({jsonrpc:'2.0',id:m.id,error:{code:-32601,message:'unknown tool'}})}
}
