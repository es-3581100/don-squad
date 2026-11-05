// STARTUP-020: V1-only critical quarantine with no native read capability.
// The native V1 agent permission frontmatter is the independent hard-stop;
// this hook is supplemental defense-in-depth, NOT permission-engine coverage.
// Do not use this guard to authorize a mutating agent or a live release.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';

const AGENTS = Object.freeze([
  'c-family', 'coder-worker', 'crossplatform-deployment', 'don-squad', 'go',
  'kolmafia-polyglot', 'kotlin-family', 'mobile-deployment', 'planner',
  'project-planner-hygiene', 'python', 'researcher-reviewer', 'rust',
  'ui-designer', 'verifier'
]);
const ALLOWED_CRITICAL_TOOLS = new Set(['question']);
const configRoot = () => process.env.OPENCODE_CONFIG_DIR
  ? path.resolve(process.env.OPENCODE_CONFIG_DIR)
  : path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'opencode');
const stateRoot = () => path.join(process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local', 'state'), 'don-squad');
const healthPath = () => path.join(stateRoot(), 'health.json');
const pathInConfig = (...parts) => path.join(configRoot(), ...parts);
const sha256 = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const now = () => new Date().toISOString();

function guardedJSON(filename) {
  const entry = fs.lstatSync(filename);
  if (!entry.isFile() || entry.isSymbolicLink()) throw new Error('not an ordinary file');
  return JSON.parse(fs.readFileSync(filename, 'utf8'));
}
function pushIssue(issues, code, message, agent = undefined) {
  issues.push({severity:'critical', code, message, active:true, ...(agent ? {agent} : {})});
}
function scanInstalled(projectDirectory) {
  const issues = [];
  let expected = null;
  try {
    const m = guardedJSON(pathInConfig('tools', 'don-squad', 'integrity.json'));
    if (!m || m.schema_version !== 'don-squad.integrity.v1' ||
        !m.agents || typeof m.agents !== 'object' || Array.isArray(m.agents)) throw new Error('invalid schema');
    const got = Object.keys(m.agents);
    if (got.length !== AGENTS.length || AGENTS.some(a => !Object.hasOwn(m.agents,a)) ||
        got.some(a => !AGENTS.includes(a)) ||
        AGENTS.some(a => typeof m.agents[a] !== 'string' || !/^[0-9a-f]{64}$/.test(m.agents[a]))) {
      throw new Error('incomplete/invalid agent roster');
    }
    expected = m.agents;
  } catch {
    pushIssue(issues,'integrity_manifest_invalid','Required integrity manifest invalid or unreadable');
  }
  if (expected) {
    for (const agent of AGENTS) {
      try {
        const p=pathInConfig('agents', `${agent}.md`);
        const f=fs.lstatSync(p);
        if (!f.isFile() || f.isSymbolicLink()) throw new Error('not a regular file');
        if (sha256(fs.readFileSync(p)) !== expected[agent]) {
          pushIssue(issues,'agent_sha_mismatch','Installed agent differs from approved SHA',agent);
        }
      } catch {
        pushIssue(issues,'agent_unavailable','Agent missing or unreadable',agent);
      }
    }
  }
  try {
    const p=guardedJSON(pathInConfig('tools','don-squad','policy.json'));
    if (!p || p.schema_version!=='don-squad.guard.v1' || p.lead!=='don-squad' ||
        !Array.isArray(p.agents) || p.agents.length!==AGENTS.length ||
        new Set(p.agents).size!==AGENTS.length || AGENTS.some(a=>!p.agents.includes(a)) ||
        !Array.isArray(p.critical_guard?.safe_actions) ||
        p.critical_guard.safe_actions.length !== ALLOWED_CRITICAL_TOOLS.size ||
        new Set(p.critical_guard.safe_actions).size !== ALLOWED_CRITICAL_TOOLS.size ||
        p.critical_guard.safe_actions.some(a=>!ALLOWED_CRITICAL_TOOLS.has(a))) {
      throw new Error('invalid policy');
    }
  } catch { pushIssue(issues,'guard_policy_invalid','Guard policy invalid or unreadable'); }
  try {
    const p=pathInConfig('tools','don-squad','don-squad-control.mjs');
    const f=fs.lstatSync(p);
    if (!f.isFile() || f.isSymbolicLink()) throw new Error('invalid MCP target');
  } catch { pushIssue(issues,'mcp_control_missing','Required MCP control target is missing'); }
  // A project-local agent definition can override the globally hashed bytes.
  // Without a verified effective-source resolver we must not claim that the
  // global SHA alone authenticates the effective agent.
  const start = path.resolve(projectDirectory || process.cwd());
  let at = start;
  for (let i=0; i<64; i++) {
    for (const folder of ['agents','agent']) {
      for (const agent of AGENTS) {
        const candidate=path.join(at,'.opencode',folder,`${agent}.md`);
        if (fs.existsSync(candidate)) {
          pushIssue(issues,'project_agent_override_unverified',
            'Project/ancestor agent override requires explicit effective-source review',agent);
        }
      }
    }
    const parent=path.dirname(at);
    if (parent===at) break;
    at=parent;
  }
  if (['OPENCODE_CONFIG','OPENCODE_CONFIG_CONTENT','OPENCODE_PERMISSION'].some(k=>process.env[k])) {
    pushIssue(issues,'runtime_config_overlay_unverified',
      'Runtime configuration/permission overlay requires explicit review');
  }
  return issues;
}
function priorHealthIssues() {
  if (!fs.existsSync(healthPath())) return [];
  try {
    const h=guardedJSON(healthPath());
    if (!h || typeof h!=='object' || !Array.isArray(h.issues) ||
        !['minor','medium','critical'].includes(h.severity) ||
        h.issues.some(i => !i || typeof i!=='object' ||
          typeof i.code!=='string' || typeof i.active!=='boolean' ||
          !['minor','medium','critical'].includes(i.severity))) throw new Error('invalid shape');
    // Preserve unrelated critical findings, never silently discard warnings from another producer.
    return h.issues.filter(i=>i && i.active===true && ![
      'integrity_manifest_invalid','agent_sha_mismatch','agent_unavailable',
      'guard_policy_invalid','mcp_control_missing'
    ].includes(i.code));
  } catch {
    const issues=[];
    pushIssue(issues,'guard_health_invalid','Prior health state invalid or unreadable');
    return issues;
  }
}
function refreshHealth(projectDirectory, requireExisting = false) {
  const missingAfterStartup = requireExisting && !fs.existsSync(healthPath());
  const issues=[...priorHealthIssues(), ...scanInstalled(projectDirectory)];
  if (missingAfterStartup) pushIssue(issues,'guard_health_unavailable','Guard health disappeared after initialization');
  const severity=issues.some(x=>x.severity==='critical' && x.active) ? 'critical' :
    issues.some(x=>x.severity==='medium' && x.active) ? 'medium' : 'minor';
  const h={schema_version:'don-squad-v1-startup/1', severity, issues, checked_at:now(),
    enforcement:'v1-native-permissions-plus-tool-hook', agent_count:AGENTS.length};
  const dest=healthPath();
  fs.mkdirSync(path.dirname(dest), {recursive:true,mode:0o700});
  const temp=dest+'.'+process.pid+'.'+crypto.randomUUID()+'.tmp';
  fs.writeFileSync(temp, JSON.stringify(h,null,2)+'\n', {mode:0o600,flag:'wx'});
  fs.renameSync(temp,dest);
  return h;
}

// In STARTUP-020 the native V1 lead disables 'read' entirely: the
// V1 read tool has a confirmed lexical-symlink bypass in debug execution.
// This guard does not attempt to make filesystem path validation authoritative.

// The only export is the V1 plugin factory so V1 auto-discovery does not mistake
// utility functions for plugin entrypoints. No V2 SDK import or setup(ctx).
export const DonSquadV1StartupGuard = async (ctx = {}) => {
  const projectDirectory=ctx.directory || process.cwd();
  refreshHealth(projectDirectory);
  return {
    'tool.execute.before': async (input, output) => {
      // Rescan on each call so a post-start file edit or corrupt health state
      // cannot silently lift a critical stop.
      const h=refreshHealth(projectDirectory,true);
      if (h.severity!=='critical') return;
      const tool=String(input?.tool ?? '');
      if (!ALLOWED_CRITICAL_TOOLS.has(tool)) {
        throw new Error('Don-Squad critical integrity state: tool blocked; operator questions only');
      }
    }
  };
};
