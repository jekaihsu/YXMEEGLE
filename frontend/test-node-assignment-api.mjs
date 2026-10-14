import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {assignmentFixture} from './fixtures/node-assignments.mjs';

const bundle = await build({entryPoints: [new URL('./src/nodeAssignmentApi.ts', import.meta.url).pathname], bundle: true, write: false, platform: 'node', format: 'esm'});
const path = new URL('./.node-assignment-api-test.mjs', import.meta.url);
await fs.writeFile(path, bundle.outputFiles[0].text);
let api;
try {api = await import(path.href)} finally {await fs.unlink(path)}
const signal = new AbortController().signal;
let requests = [], response;
globalThis.fetch = async (url, init) => {
  requests.push({url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null});
  return new Response(JSON.stringify(response.body), {status: response.status, headers: {'Content-Type': 'application/json'}});
};

test('list parses into chain order and preserves literal progress', async () => {
  response = {status: 200, body: assignmentFixture().list};
  const list = await api.fetchNodeAssignments('p/1', signal, () => true);
  assert.deepEqual(list.nodes.map(n => n.label), ['業務', 'PM', '確認單', '外業', '控制', '圖資', '報告', '計價', '結算']);
  assert.deepEqual(list.summary, {done: 4, total: 9, current_node: 'control'});
  assert.deepEqual(list.nodes[4].tasks, {done: 2, total: 5});
  assert.equal(requests.at(-1).url, '/api/projects/p%2F1/node-assignments');
});
test('mutations encode identifiers and send fresh UUIDs', async () => {
  requests = []; response = {status: 200, body: {code: 'ok'}};
  await api.mutateNodeAssignment('p1', {action: 'claim', nodeKey: 'control'}, signal, () => true);
  await api.mutateNodeAssignment('p1', {action: 'assign', nodeKey: 'control', assignees: ['ou_anna']}, signal, () => true);
  await api.mutateNodeAssignment('p1', {action: 'update_task', nodeKey: 'control', taskId: 'task/1', patch: {status: 'completed'}}, signal, () => true);
  assert.deepEqual(requests.map(r => [r.method, r.url]), [
    ['POST', '/api/projects/p1/node-assignments/nodes/control/claim'],
    ['POST', '/api/projects/p1/node-assignments/nodes/control/assign'],
    ['PATCH', '/api/projects/p1/node-assignments/tasks/task%2F1'],
  ]);
  assert.deepEqual(requests[1].body.assignees, ['ou_anna']);
  assert.equal(requests[2].body.status, 'completed');
  for (const r of requests) assert.match(r.body.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(new Set(requests.map(r => r.body.request_id)).size, 3);
});
test('422 errors preserve field messages', async () => {
  response = {status: 422, body: {code: 'validation', detail: [{loc: ['body', 'deadline'], msg: '期限必須為日期'}]}};
  await assert.rejects(api.mutateNodeAssignment('p1', {action: 'claim', nodeKey: 'control'}, signal, () => true), error => {
    assert.equal(error.message, '請檢查欄位內容後再試。');
    assert.deepEqual(error.fields, {deadline: '期限必須為日期'}); return true;
  });
});
test('404 and successful disabled responses disable the feature', async () => {
  for (const reply of [{status: 404, body: {code: 'disabled', detail: 'disabled'}}, {status: 200, body: {code: 'disabled'}}]) {
    response = reply;
    await assert.rejects(api.fetchNodeAssignments('p1', signal, () => true), error => api.assignmentsDisabled(error));
  }
});
test('malformed node payload becomes a local readable error', async () => {
  response = {status: 200, body: {...assignmentFixture().list, nodes: [{key: 'control'}]}};
  await assert.rejects(api.fetchNodeAssignments('p1', signal, () => true), {message: '節點資料格式不正確，請稍後重試。'});
});
test('detail refuses a response for a different node', async () => {
  response = {status: 200, body: assignmentFixture().detail};
  await assert.rejects(api.fetchNodeAssignmentDetail('p1', 'sales', signal, () => true), {message: '節點資料格式不正確，請稍後重試。'});
});
test('detail resolves person IDs to names and hides unresolved technical IDs', async () => {
  const detail = assignmentFixture().detail; detail.tasks[0].assignee = 'ou_wei'; detail.node.assigned_by = 'ou_anna'; detail.node.approver = 'ou_unknown';
  response = {status: 200, body: detail};
  const parsed = await api.fetchNodeAssignmentDetail('p1', 'control', signal, () => true);
  assert.equal(parsed.tasks[0].assignee.name, '陳威廷'); assert.equal(parsed.node.assigned_by.name, '林安娜'); assert.equal(parsed.node.approver.name, '姓名待確認');
});
