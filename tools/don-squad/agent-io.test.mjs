#!/usr/bin/env node
import assert from 'node:assert/strict';
import {emitAgentEnvelope, parseStrictJSON, validateAgentEnvelope, validateAgentJSON} from './agent-io.mjs';

const good = {
  schema_version: 'agent-io/v1',
  kind: 'return',
  task_id: 'tsk_123',
  attempt_id: 'att_456',
  sender: 'verifier',
  recipient: 'don-squad',
  status: 'completed',
  reason: 'Verified.',
  evidence: [{type: 'VERIFIED', result: 'ok'}],
  next_owner: 'don-squad',
  verification: [{command: 'true', cwd: '/tmp', exit_code: 0, result: 'ok'}],
  provenance: {artifacts: [], git: null, limitations: []},
};

assert.deepEqual(validateAgentEnvelope(good, {task_id: 'tsk_123', sender: 'verifier', recipient: 'don-squad'}), {valid: true, errors: []});

const emitted = emitAgentEnvelope(good);
assert.equal(emitted.valid, true);
assert.equal(typeof emitted.canonical_json, 'string');
assert.equal(emitted.sha256.length, 64);
assert.deepEqual(parseStrictJSON(emitted.canonical_json), JSON.parse(emitted.canonical_json));

for (const [field, replacement] of [['evidence', {}], ['verification', {}]]) {
  const bad = structuredClone(good); bad[field] = replacement;
  const result = validateAgentEnvelope(bad);
  assert.equal(result.valid, false);
  assert(result.errors.some(error => error.includes(`${field} must be an array`)));
}

const badArtifacts = structuredClone(good); badArtifacts.provenance.artifacts = {};
assert.equal(validateAgentEnvelope(badArtifacts).valid, false);
const badLimitations = structuredClone(good); badLimitations.provenance.limitations = 'none';
assert.equal(validateAgentEnvelope(badLimitations).valid, false);
assert.equal(validateAgentEnvelope(good, {task_id: 'tsk_DIFFERENT'}).valid, false);

const duplicate = '{"schema_version":"agent-io/v1","schema_version":"agent-io/v1"}';
assert.throws(() => parseStrictJSON(duplicate), /duplicate key/);
assert.equal(validateAgentJSON('{"evidence":{},}').valid, false);

console.log(JSON.stringify({status: 'passed', tests: 9}));
