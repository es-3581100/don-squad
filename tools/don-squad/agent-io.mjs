#!/usr/bin/env node
import crypto from 'node:crypto';

const SHA256_RE = /^[0-9a-f]{64}$/;
const PHASES = new Set(['input', 'before', 'after']);
const VERIFICATIONS = new Set(['computed', 'matched', 'mismatch', 'unavailable']);

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function nonEmptyString(value) {
  return typeof value === 'string' && value.length > 0;
}

function jsonSafe(value, path, errors, seen = new Set()) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) errors.push(`${path} must not contain a non-finite number`);
    return;
  }
  if (Array.isArray(value)) {
    if (seen.has(value)) { errors.push(`${path} must not contain cycles`); return; }
    seen.add(value);
    value.forEach((item, index) => jsonSafe(item, `${path}[${index}]`, errors, seen));
    seen.delete(value);
    return;
  }
  if (isObject(value)) {
    if (seen.has(value)) { errors.push(`${path} must not contain cycles`); return; }
    seen.add(value);
    for (const [key, item] of Object.entries(value)) jsonSafe(item, `${path}.${key}`, errors, seen);
    seen.delete(value);
    return;
  }
  errors.push(`${path} contains a non-JSON value`);
}

function requireStringArray(value, path, errors) {
  if (!Array.isArray(value)) { errors.push(`${path} must be an array`); return; }
  value.forEach((item, index) => {
    if (typeof item !== 'string') errors.push(`${path}[${index}] must be a string`);
  });
}

function validateArtifact(artifact, path, errors) {
  if (!isObject(artifact)) { errors.push(`${path} must be an object`); return; }
  if (!nonEmptyString(artifact.path)) errors.push(`${path}.path must be a non-empty string`);
  if (!PHASES.has(artifact.phase)) errors.push(`${path}.phase must be input, before, or after`);
  if (artifact.algorithm !== 'sha256') errors.push(`${path}.algorithm must be sha256`);
  if (!(artifact.digest === null || (typeof artifact.digest === 'string' && SHA256_RE.test(artifact.digest)))) {
    errors.push(`${path}.digest must be null or 64 lowercase hexadecimal characters`);
  }
  if (!VERIFICATIONS.has(artifact.verification)) {
    errors.push(`${path}.verification must be computed, matched, mismatch, or unavailable`);
  }
  if (!(artifact.reason === null || typeof artifact.reason === 'string')) errors.push(`${path}.reason must be string or null`);
  if ('expected_digest' in artifact && !(artifact.expected_digest === null || (typeof artifact.expected_digest === 'string' && SHA256_RE.test(artifact.expected_digest)))) {
    errors.push(`${path}.expected_digest must be null or 64 lowercase hexadecimal characters`);
  }
}

function validateVerification(record, path, errors) {
  if (!isObject(record)) { errors.push(`${path} must be an object`); return; }
  if (!nonEmptyString(record.command)) errors.push(`${path}.command must be a non-empty string`);
  if (typeof record.cwd !== 'string') errors.push(`${path}.cwd must be a string`);
  if (!(record.exit_code === null || Number.isInteger(record.exit_code))) errors.push(`${path}.exit_code must be integer or null`);
  if (!('result' in record)) errors.push(`${path}.result is required`);
  if ('evidence_reference' in record && typeof record.evidence_reference !== 'string') errors.push(`${path}.evidence_reference must be a string when present`);
}

function validateProvenance(provenance, errors) {
  if (!isObject(provenance)) { errors.push('provenance must be an object'); return; }
  if (!Array.isArray(provenance.artifacts)) errors.push('provenance.artifacts must be an array');
  else provenance.artifacts.forEach((artifact, index) => validateArtifact(artifact, `provenance.artifacts[${index}]`, errors));
  if (!(provenance.git === null || isObject(provenance.git))) errors.push('provenance.git must be an object or null');
  requireStringArray(provenance.limitations, 'provenance.limitations', errors);
}

export function validateAgentEnvelope(envelope, expected = {}) {
  const errors = [];
  if (!isObject(envelope)) return {valid: false, errors: ['envelope must be an object']};
  jsonSafe(envelope, 'envelope', errors);

  if (envelope.schema_version !== 'agent-io/v1') errors.push('schema_version must equal agent-io/v1');
  if (!['prompt', 'return'].includes(envelope.kind)) errors.push('kind must be prompt or return');
  for (const key of ['task_id', 'sender', 'recipient']) {
    if (!nonEmptyString(envelope[key])) errors.push(`${key} must be a non-empty string`);
  }
  if ('attempt_id' in envelope && !nonEmptyString(envelope.attempt_id)) errors.push('attempt_id must be a non-empty string when present');
  validateProvenance(envelope.provenance, errors);

  if (envelope.kind === 'prompt') {
    if (!nonEmptyString(envelope.objective)) errors.push('objective must be a non-empty string');
    for (const key of ['scope', 'constraints', 'acceptance_criteria', 'inputs']) requireStringArray(envelope[key], key, errors);
    if (!['json', 'yaml'].includes(envelope.return_format)) errors.push('return_format must be json or yaml');
  }

  if (envelope.kind === 'return') {
    if (!nonEmptyString(envelope.status)) errors.push('status must be a non-empty string');
    if (typeof envelope.reason !== 'string') errors.push('reason must be a string');
    if (!Array.isArray(envelope.evidence)) errors.push('evidence must be an array');
    else envelope.evidence.forEach((item, index) => {
      if (!isObject(item)) errors.push(`evidence[${index}] must be an object`);
    });
    if (!Array.isArray(envelope.verification)) errors.push('verification must be an array');
    else envelope.verification.forEach((item, index) => validateVerification(item, `verification[${index}]`, errors));
    if (!(envelope.next_owner === null || nonEmptyString(envelope.next_owner))) errors.push('next_owner must be a non-empty string or null');
  }

  const expectedFields = {
    kind: expected.kind,
    task_id: expected.task_id,
    attempt_id: expected.attempt_id,
    sender: expected.sender,
    recipient: expected.recipient,
  };
  for (const [key, value] of Object.entries(expectedFields)) {
    if (value !== undefined && envelope[key] !== value) errors.push(`${key} does not match expected value`);
  }

  return {valid: errors.length === 0, errors};
}

function sortedJSONValue(value) {
  if (Array.isArray(value)) return value.map(sortedJSONValue);
  if (isObject(value)) {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = sortedJSONValue(value[key]);
    return out;
  }
  return value;
}

export function emitAgentEnvelope(envelope, expected = {}) {
  const validation = validateAgentEnvelope(envelope, expected);
  if (!validation.valid) return {...validation, canonical_json: null, sha256: null, byte_length: null};
  const canonical_json = JSON.stringify(sortedJSONValue(envelope));
  const bytes = Buffer.from(canonical_json, 'utf8');
  return {
    valid: true,
    errors: [],
    canonical_json,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    byte_length: bytes.length,
  };
}

// Strict parser for validating already-authored JSON text. Unlike JSON.parse, this
// detects duplicate object keys before a return is accepted as evidence.
export function parseStrictJSON(text) {
  if (typeof text !== 'string') throw new TypeError('JSON input must be a string');
  let i = 0;
  const ws = () => { while (/\s/.test(text[i] ?? '')) i += 1; };
  const fail = message => { throw new SyntaxError(`${message} at character ${i}`); };
  const parseString = () => {
    const start = i;
    if (text[i] !== '"') fail('expected string');
    i += 1;
    let escaped = false;
    while (i < text.length) {
      const c = text[i];
      if (!escaped && c === '"') { i += 1; return JSON.parse(text.slice(start, i)); }
      if (!escaped && c === '\\') escaped = true; else escaped = false;
      i += 1;
    }
    fail('unterminated string');
  };
  const parseNumber = () => {
    const m = text.slice(i).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    if (!m) fail('invalid number');
    i += m[0].length;
    const n = Number(m[0]);
    if (!Number.isFinite(n)) fail('non-finite number');
    return n;
  };
  const parseValue = () => {
    ws();
    const c = text[i];
    if (c === '"') return parseString();
    if (c === '{') return parseObject();
    if (c === '[') return parseArray();
    if (text.startsWith('true', i)) { i += 4; return true; }
    if (text.startsWith('false', i)) { i += 5; return false; }
    if (text.startsWith('null', i)) { i += 4; return null; }
    if (c === '-' || /\d/.test(c ?? '')) return parseNumber();
    fail('unexpected token');
  };
  const parseArray = () => {
    const out = [];
    i += 1; ws();
    if (text[i] === ']') { i += 1; return out; }
    while (true) {
      out.push(parseValue()); ws();
      if (text[i] === ']') { i += 1; return out; }
      if (text[i] !== ',') fail('expected comma or closing bracket');
      i += 1;
    }
  };
  const parseObject = () => {
    const out = {};
    const keys = new Set();
    i += 1; ws();
    if (text[i] === '}') { i += 1; return out; }
    while (true) {
      ws();
      const key = parseString();
      if (keys.has(key)) fail(`duplicate key ${JSON.stringify(key)}`);
      keys.add(key); ws();
      if (text[i] !== ':') fail('expected colon');
      i += 1;
      out[key] = parseValue(); ws();
      if (text[i] === '}') { i += 1; return out; }
      if (text[i] !== ',') fail('expected comma or closing brace');
      i += 1;
    }
  };
  const value = parseValue();
  ws();
  if (i !== text.length) fail('trailing content');
  return value;
}

export function validateAgentJSON(text, expected = {}) {
  try {
    const envelope = parseStrictJSON(text);
    return {envelope, ...validateAgentEnvelope(envelope, expected)};
  } catch (error) {
    return {envelope: null, valid: false, errors: [String(error?.message ?? error)]};
  }
}
