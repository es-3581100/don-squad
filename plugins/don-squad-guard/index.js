import { Plugin } from "@opencode/plugin";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import { spawn } from "node:child_process";

const cfgRoot=()=>process.env.XDG_CONFIG_HOME?path.join(process.env.XDG_CONFIG_HOME,"opencode"):path.join(os.homedir(),".config","opencode");
const stateRoot=()=>process.env.XDG_STATE_HOME?path.join(process.env.XDG_STATE_HOME,"don-squad"):path.join(os.homedir(),".local","state","don-squad");
const readJSON=(p,f={})=>{try{return JSON.parse(fs.readFileSync(p,"utf8"))}catch{return f}};
const writeJSON=(p,o)=>{fs.mkdirSync(path.dirname(p),{recursive:true});const t=p+".tmp-"+process.pid;fs.writeFileSync(t,JSON.stringify(o,null,2)+"\n",{mode:0o600});fs.renameSync(t,p)};
const append=(o)=>{const p=path.join(stateRoot(),"events","events.jsonl");fs.mkdirSync(path.dirname(p),{recursive:true});fs.appendFileSync(p,JSON.stringify({...o,ts:new Date().toISOString()})+"\n")};
const sidOf=(e)=>e?.sessionID||e?.session_id||e?.data?.sessionID||e?.data?.session_id||e?.data?.id||e?.session?.id||null;
const policy=()=>readJSON(path.join(cfgRoot(),"tools","don-squad","policy.json"),{});
const healthPath=()=>path.join(stateRoot(),"health.json");
const overridesDir=()=>path.join(stateRoot(),"guard","overrides");
const agentPath=(id)=>path.join(cfgRoot(),"agents",id+".md");
function condenseAsync(){const py=process.env.DON_SQUAD_RECORDER_PYTHON||"python3",script=path.join(cfgRoot(),"tools","don-squad","record_condense.py");try{const c=spawn(py,[script,"--state-root",stateRoot()],{stdio:"ignore"});c.on("error",()=>issue("medium","recorder_unavailable","Automatic Don-Squad receipt condenser could not start",{python:py}))}catch{issue("medium","recorder_unavailable","Automatic Don-Squad receipt condenser could not start",{python:py})}}
const sessionAgents=new Map(), sessionModels=new Map(), seenStart=new Set();
// Membership is an explicit part of the guard contract; do not infer it from a
// potentially truncated integrity manifest or mutable policy file.
const REQUIRED_AGENT_IDS = Object.freeze([
 "c-family", "coder-worker", "crossplatform-deployment", "don-squad", "go",
 "kolmafia-polyglot", "kotlin-family", "mobile-deployment", "planner",
 "project-planner-hygiene", "python", "researcher-reviewer", "rust",
 "ui-designer", "verifier"
]);
const INTEGRITY_CODES = new Set(["agent_sha_mismatch", "agent_missing", "integrity_manifest_invalid", "mcp_control_missing", "guard_policy_invalid"]);
const CRITICAL_SAFE_ACTIONS = new Set(["read", "glob", "grep", "webfetch", "websearch", "skill", "question"]);
const integrity=()=>readJSON(path.join(cfgRoot(),"tools","don-squad","integrity.json"),{});
const integrityPath=()=>path.join(cfgRoot(),"tools","don-squad","integrity.json");
function validHealthShape(h) {
 return !!h && typeof h==="object" && !Array.isArray(h) &&
  ["minor","medium","critical"].includes(h.severity) &&
  Array.isArray(h.issues) && h.issues.every(x=>
   !!x && typeof x==="object" && typeof x.code==="string" &&
   typeof x.active==="boolean" && ["minor","medium","critical"].includes(x.severity));
}
function loadHealthForStartup() {
 if (!fs.existsSync(healthPath())) return {severity:"minor",issues:[]};
 try {
  const h=JSON.parse(fs.readFileSync(healthPath(),"utf8"));
  if (!validHealthShape(h)) throw new Error("invalid health shape");
  return h;
 } catch {
  return {severity:"critical",issues:[{severity:"critical",code:"guard_health_invalid",message:"Previous guard health is malformed or unreadable",active:true,ts:new Date().toISOString()}]};
 }
}
function healthForEnforcement() {
 try {
  const h=JSON.parse(fs.readFileSync(healthPath(),"utf8"));
  if (!validHealthShape(h)) throw new Error("invalid health");
  // An active critical issue cannot be downgraded by stale summary metadata.
  if (h.issues.some(x=>x && x.active && x.severity==="critical")) return {...h,severity:"critical"};
  return h;
 } catch {return {severity:"critical",issues:[{code:"guard_health_unavailable",severity:"critical",active:true}]};}
}
function severityOf(issues) {
 const rank={minor:1,medium:2,critical:3};
 return issues.filter(x=>x.active).reduce((a,x)=>rank[x.severity]>rank[a]?x.severity:a,"minor");
}
function requiredManifest() {
 let manifest;
 try {manifest=JSON.parse(fs.readFileSync(integrityPath(),"utf8"));}
 catch(e) {throw new Error(`Manifest missing/unreadable/malformed: ${e.code || e.message}`);}
 if (!manifest || manifest.schema_version!=="don-squad.integrity.v1" || !manifest.agents || typeof manifest.agents!=="object" || Array.isArray(manifest.agents)) throw new Error("Unexpected manifest schema");
 const expected=new Set(REQUIRED_AGENT_IDS), actual=Object.keys(manifest.agents);
 const missing=REQUIRED_AGENT_IDS.filter(id=>!Object.hasOwn(manifest.agents,id));
 const unexpected=actual.filter(id=>!expected.has(id));
 if (missing.length || unexpected.length) throw new Error(`Incomplete manifest roster: missing=[${missing.join(",")}] unexpected=[${unexpected.join(",")}]`);
 for(const id of REQUIRED_AGENT_IDS) if(typeof manifest.agents[id]!=="string" || !/^[0-9a-f]{64}$/.test(manifest.agents[id])) throw new Error(`Invalid digest entry: ${id}`);
 return manifest.agents;
}
function startupFindings() {
 const findings=[], ts=new Date().toISOString();
 const add=(code,message,extra={})=>findings.push({code,message,...extra,severity:"critical",active:true,ts});
 try {
  const expected=requiredManifest();
  for(const id of REQUIRED_AGENT_IDS) {
   try {
    const got=fileSHA(agentPath(id));
    if (got!==expected[id]) add("agent_sha_mismatch",`Installed agent hash mismatch: ${id}`,{agent:id,expected:expected[id],observed:got});
   } catch(e) {add("agent_missing",`Installed agent missing or unreadable: ${id}`,{agent:id});}
  }
 } catch(e) {add("integrity_manifest_invalid",`Integrity manifest validation failed: ${e.message}`);}
 try {
  const guardPolicy=JSON.parse(fs.readFileSync(path.join(cfgRoot(),"tools","don-squad","policy.json"),"utf8"));
  if (!guardPolicy || guardPolicy.schema_version!=="don-squad.guard.v1" || guardPolicy.lead!=="don-squad" || !Array.isArray(guardPolicy.agents) || !Array.isArray(guardPolicy.critical_guard?.safe_actions)) throw new Error("unexpected policy schema");
  const ids=new Set(guardPolicy.agents);
  if (ids.size!==REQUIRED_AGENT_IDS.length || REQUIRED_AGENT_IDS.some(id=>!ids.has(id))) throw new Error("policy roster does not match required agents");
  if (guardPolicy.critical_guard.safe_actions.some(action=>!CRITICAL_SAFE_ACTIONS.has(action))) throw new Error("critical safe-action list includes a privileged action");
 } catch(e) {add("guard_policy_invalid",`Guard policy missing, unreadable, or invalid: ${e.code||e.message}`);}
 const control=path.join(cfgRoot(),"tools","don-squad","don-squad-control.mjs");
 try {if(!fs.statSync(control).isFile()) throw new Error("not a file");}
 catch {add("mcp_control_missing","Don-Squad MCP control executable missing or unreadable",{path:control});}
 return findings;
}
function verifyIntegrity() {
 const findings=startupFindings();
 const h=loadHealthForStartup();
 // Only an entirely completed scan may retire prior integrity findings. Other
 // active findings, including corrupt prior health, remain enforced.
 h.issues=[...h.issues.filter(x=>x && !INTEGRITY_CODES.has(x.code)),...findings];
 h.severity=severityOf(h.issues);
 writeJSON(healthPath(),h);
 append({type:"integrity.scan",agents_checked:findings.some(f=>f.code==="integrity_manifest_invalid")?0:REQUIRED_AGENT_IDS.length,critical_findings:findings.length});
 return !findings.some(f=>f.code==="mcp_control_missing");
}
function testKind(event){const i=event?.input||{};const c=String(i.command||i.cmd||"").toLowerCase();if(!c)return null;if(/(^|\s)go test(\s|$)/.test(c))return "go-test";if(/pytest|python(3)? -m pytest/.test(c))return "pytest";if(/cargo test/.test(c))return "cargo-test";if(/gradle(w)? .*test|gradle(w)? test/.test(c))return "gradle-test";if(/npm (run )?test|pnpm (run )?test|yarn test/.test(c))return "js-test";if(/mvn .*test|mvn test/.test(c))return "maven-test";return null}
function issue(severity,code,message,extra={}){const h=loadHealthForStartup();const rank={minor:1,medium:2,critical:3};h.issues=(h.issues||[]).filter(x=>!(x.code===code&&x.active));h.issues.push({severity,code,message,active:true,ts:new Date().toISOString(),...extra});h.severity=Object.values(h.issues).filter(x=>x.active).reduce((a,x)=>rank[x.severity]>rank[a]?x.severity:a,"minor");writeJSON(healthPath(),h);append({type:"issue",severity,code,message,...extra})}
function overrideValid(sessionID){const p=path.join(overridesDir(),sessionID+".json"),o=readJSON(p,null);if(!o)return false;return o.session_id===sessionID&&Date.parse(o.expires_at)>Date.now()&&o.confirmed===true}
function extended(model,p){const s=((model?.providerID||"")+"/"+(model?.id||"")+"#"+(model?.variant||"")).toLowerCase();return (p.depth?.extended_model_patterns||[]).some(x=>s.includes(String(x).toLowerCase()))}
async function parentID(ctx,sessionID){try{const s=await ctx.session.get({sessionID});return s?.parentID||s?.parent_id||s?.parent?.id||null}catch{return null}}
async function effectiveDepth(ctx,sessionID,target){const p=policy(),ro=new Set(p.read_only_agents||[]);let cur=sessionID,depth=0,guard=0;while(cur&&guard++<16){const a=sessionAgents.get(cur);if(a&&a!==p.lead&&!ro.has(a))depth+=1;cur=await parentID(ctx,cur)}if(target&&!ro.has(target))depth+=1;return depth}
function fileSHA(p){const b=fs.readFileSync(p);return crypto.createHash("sha256").update(b).digest("hex")}


export default Plugin.define({
 id:"don-squad.guard",
 async setup(ctx){
  fs.mkdirSync(stateRoot(),{recursive:true});
  const mcpExecutableReady=verifyIntegrity();
  await ctx.agent.transform((editor)=>{editor.default("don-squad");for(const id of ["build","plan"]){editor.update(id,(a)=>{a.mode="subagent";a.hidden=true})}});
  const control=path.join(cfgRoot(),"tools","don-squad","don-squad-control.mjs");
  if(mcpExecutableReady) await ctx.mcp.transform((editor)=>{editor.set("don-squad-control",{type:"local",command:[process.execPath,control]})});
  await ctx.session.hook("context",async(event)=>{sessionAgents.set(event.sessionID,event.agent);sessionModels.set(event.sessionID,event.model);if(!seenStart.has(event.sessionID)){seenStart.add(event.sessionID);const p=policy();append({type:"agent.start",session_id:event.sessionID,agent:event.agent,model:event.model,authority:p.authority?.[event.agent]||"unknown",agent_sha256:integrity().agents?.[event.agent]||null})}const p=policy(),h=healthForEnforcement();writeJSON(path.join(stateRoot(),"latest.json"),{session_id:event.sessionID,agent:event.agent,model:event.model,logic_level:event.model?.variant||null,authority:p.authority?.[event.agent]||"unknown",guard:h.severity||"minor",updated_at:new Date().toISOString()})});
  await ctx.permission.hook("evaluate",async(event)=>{const p=policy(),sid=event.sessionID,h=healthForEnforcement();if(h.severity==="critical"&&!overrideValid(sid)){const configured=new Set(Array.isArray(p.critical_guard?.safe_actions)?p.critical_guard.safe_actions:CRITICAL_SAFE_ACTIONS);if(!(CRITICAL_SAFE_ACTIONS.has(event.action)&&configured.has(event.action))){event.effect="deny";event.message="Don-Squad critical full-stop guard is active. Read-only diagnosis remains available. Use the local don-squad guard override flow for this exact session if you intentionally accept the risk.";append({type:"guard.denied",session_id:sid,agent:event.agent||null,action:event.action,resources:event.resources||[],severity:"critical"});return}}
    if(event.action==="subagent"){const target=event.resources?.[0]||null,model=sessionModels.get(sid),max=extended(model,p)?(p.depth?.extended_max||5):(p.depth?.standard_max||3),d=await effectiveDepth(ctx,sid,target);append({type:"depth.check",session_id:sid,agent:event.agent||null,target,depth:d,max_depth:max,model});if(d>max){event.effect="deny";event.message=`Don-Squad subagent depth ${d} exceeds configured maximum ${max}. Read-only agents count +0.`;issue("critical","depth_violation","Subagent depth limit exceeded",{session_id:sid,agent:event.agent||null,target,depth:d,max_depth:max})}}
    append({type:"action.request",session_id:sid,agent:event.agent||null,action:event.action,resources:event.resources||[],effect:event.effect})
  });
  await ctx.tool.hook("execute.before",async(event)=>{append({type:"tool.before",session_id:sidOf(event),tool:event.tool||null,test_kind:testKind(event)})});
  await ctx.tool.hook("execute.after",async(event)=>{const sid=sidOf(event);if(event.status==="error"){append({type:"tool.after",session_id:sid,tool:event.tool||null,status:"error",known:true,proven:false,error_type:event.error?.type||null,test_kind:testKind(event)});issue("minor","tool_error",`Tool failed: ${event.tool||"unknown"}`,{session_id:sid,tool:event.tool||null})}else append({type:"tool.after",session_id:sid,tool:event.tool||null,status:"completed",known:true,proven:true,test_kind:testKind(event)})});
  const controller=new AbortController();void(async()=>{try{for await(const ev of ctx.event.subscribe({signal:controller.signal})){if(ev.type==="session.idle"||ev.type==="session.execution.succeeded"||ev.type==="session.execution.failed"){const sid=sidOf(ev),a=sid?sessionAgents.get(sid):null,m=sid?sessionModels.get(sid):null;append({type:"agent.return",session_id:sid,agent:a||null,model:m||null,event_type:ev.type,proven:!!sid});if(sid)condenseAsync();}}}catch{}})();
  return ()=>controller.abort();
 }
});
