// Source-body corroboration only. NOT the full Effect.Permission.Service.ask.
import {readFileSync} from 'node:fs'
import {join,dirname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {createHash} from 'node:crypto'
import vm from 'node:vm'
const root=dirname(fileURLToPath(import.meta.url))
const pins={
  'permission-evaluate.ts':'ee68b53280eab9dcd3798af8645801f38a1ef4b22e1a1fc731542a90126fe227',
  'wildcard-match.ts':'e50c09ee80ef53478508b4642b23c00e95959b065be49a0c5ee97c30cd4e1d4f',
}
const load=(name)=>{
  const buf=readFileSync(join(root,'upstream_excerpts',name))
  if(createHash('sha256').update(buf).digest('hex')!==pins[name]) throw Error('PIN_MISMATCH')
  return buf.toString('utf8')
}
const matchJS=load('wildcard-match.ts').replace('export function match(input: string, pattern: string)', 'function match(input, pattern)')
const evalJS=load('permission-evaluate.ts').replace('export function evaluate(permission: string, pattern: string, ...rulesets: PermissionV1.Ruleset[]): PermissionV1.Rule', 'function evaluate(permission, pattern, ...rulesets)')
const match=vm.runInNewContext(matchJS+'\nmatch;',{process:{platform:process.platform}},{timeout:1000})
const evaluate=vm.runInNewContext(evalJS+'\nevaluate;',{Wildcard:{match}},{timeout:1000})
const configured=[{permission:'read',pattern:'*',action:'deny'}]
const oldApproved=[{permission:'read',pattern:'*',action:'allow'}]
const before=evaluate('read','synthetic',configured).action
const after=evaluate('read','synthetic',configured,oldApproved).action
if(before!=='deny'||after!=='allow')throw Error('CONTRACT_UNEXPECTED')
console.log(JSON.stringify({
  upstream_source_function_bodies_pinned:true,
  baseline_hard_deny:before,
  hard_deny_plus_later_approved:after,
  classification:'SOURCE_EVALUATOR_APPROVAL_PRECEDENCE_RISK_CORROBORATED',
  effect_service_ask_executed:false,
  normal_session_hook_executed:false,
},null,2))
