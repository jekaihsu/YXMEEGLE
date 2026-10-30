import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {assignmentFixture, documentedAssignmentFixture} from './fixtures/node-assignments.mjs';

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

test('list keeps the server order and unknown keys and preserves literal progress', async () => {
  response = {status: 200, body: assignmentFixture().list};
  const list = await api.fetchNodeAssignments('p/1', signal, () => true);
  assert.deepEqual(list.nodes.map(n => n.label), ['業務', 'PM', '確認單', '外業', '控制', '圖資', '報告', '計價', '結算']);
  assert.deepEqual(list.summary, {done: 4, total: 9, current_node: 'control'});
  assert.deepEqual(list.nodes[4].tasks, {done: 2, total: 5});
  assert.equal(requests.at(-1).url, '/api/projects/p%2F1/node-assignments');
});
test('T03 a workflow with another node count and a long unknown node name renders in server order', async () => {
  const fixture = assignmentFixture().list;
  const picked = [fixture.nodes[2], fixture.nodes[0], {...fixture.nodes[4], key: 'custom_review', label: '第三方獨立複核與外部單位會審'}];
  response = {status: 200, body: {...fixture, nodes: picked, summary: {done: 0, total: 3, current_node: 'custom_review'}}};
  const list = await api.fetchNodeAssignments('p1', signal, () => true);
  assert.deepEqual(list.nodes.map(n => n.key), ['confirmation', 'sales', 'custom_review']);
  assert.equal(list.nodes[2].label, '第三方獨立複核與外部單位會審');
});
test('mutations encode identifiers and send fresh UUIDs', async () => {
  requests = []; response = {status: 200, body: assignmentFixture().detail};
  await api.mutateNodeAssignment('p1', {action: 'claim', nodeKey: 'control', expected_revision: '3f2a9c0d1b7e4a55'}, signal, () => true);
  await api.mutateNodeAssignment('p1', {action: 'assign', nodeKey: 'control', expected_revision: '3f2a9c0d1b7e4a55', owner_open_ids: ['ou_anna']}, signal, () => true);
  await api.mutateNodeAssignment('p1', {action: 'update_task', nodeKey: 'control', expected_revision: '3f2a9c0d1b7e4a55', taskId: 'task/1', patch: {status: '已完成'}}, signal, () => true);
  assert.deepEqual(requests.map(r => [r.method, r.url]), [
    ['POST', '/api/projects/p1/node-assignments/nodes/control/claim'],
    ['POST', '/api/projects/p1/node-assignments/nodes/control/assign'],
    ['PATCH', '/api/projects/p1/node-assignments/nodes/control/tasks/task%2F1'],
  ]);
  assert.deepEqual(requests[1].body.owner_open_ids, ['ou_anna']);
  assert.equal(requests[2].body.status, '已完成');
  for (const r of requests) assert.match(r.body.request_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(new Set(requests.map(r => r.body.request_id)).size, 3);
});
test('422 errors preserve field messages', async () => {
  response = {status: 422, body: {code: 'validation', detail: [{loc: ['body', 'deadline'], msg: '期限必須為日期'}]}};
  await assert.rejects(api.mutateNodeAssignment('p1', {action: 'claim', nodeKey: 'control', expected_revision: '3f2a9c0d1b7e4a55'}, signal, () => true), error => {
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

test('parses the exact documented overview and detail JSON', async () => {
  const fixture = documentedAssignmentFixture(); response = {status: 200, body: fixture.list};
  const list = await api.fetchNodeAssignments('p1', signal, () => true);
  assert.deepEqual(list.nodes[0], fixture.list.nodes[0]); assert.deepEqual(list.roster, {available: true, stale: false});
  response.body = fixture.detail;
  const detail = await api.fetchNodeAssignmentDetail('p1', 'field', signal, () => true);
  assert.deepEqual(detail.can, {...fixture.list.can.field, legacy_complete:false});
  assert.deepEqual(detail.tasks[0], {...fixture.detail.tasks[0], record_id: fixture.detail.tasks[0].id});
});
test('missing node rows preserve null revisions and send null expected_revision', async () => {
  const fixture = assignmentFixture(); const node = fixture.list.nodes.find(n => n.key === 'settlement'); node.status = null;
  response = {status: 200, body: fixture.list};
  const list = await api.fetchNodeAssignments('p1', signal, () => true); assert.equal(list.nodes[8].revision, null); assert.equal(list.nodes[8].record_id, null); assert.equal(list.nodes[8].status, null);
  response.body = {...fixture.detail, node};
  await api.mutateNodeAssignment('p1', {action: 'claim', nodeKey: 'settlement', expected_revision: null}, signal, () => true);
  assert.equal(requests.at(-1).body.expected_revision, null);
});
test('mutation returns the parsed full detail envelope', async () => {
  const fixture = assignmentFixture(); response = {status: 200, body: {...fixture.detail, record_id: 'recTask1'}};
  const detail = await api.mutateNodeAssignment('p1', {action: 'update_task', nodeKey: 'control', taskId: 'recTask1', expected_revision: '9b0c1d2e3f405162', patch: {status: '已完成'}}, signal, () => true);
  assert.equal(detail.record_id, 'recTask1'); assert.equal(detail.node.revision, '3f2a9c0d1b7e4a55'); assert.equal(detail.tasks[0].revision, '9b0c1d2e3f405162'); assert.equal(requests.at(-1).body.expected_revision, '9b0c1d2e3f405162');
});

test('string invalid detail survives and ordinary 404 does not disable assignments', async () => {
  for (const [status, code, detail] of [[422, 'invalid', '請選擇任務所屬部門'], [404, 'not_found', '沒有這個任務']]) {
    response = {status, body: {code, detail}};
    await assert.rejects(api.mutateNodeAssignment('p1', {action: 'claim', nodeKey: 'control', expected_revision: null}, signal, () => true), error => {
      assert.equal(error.message, detail); assert.equal(api.assignmentsDisabled(error), false); return true;
    });
  }
});

test('overview parses embedded tasks and people, and supports older envelopes', async () => {
  const f = assignmentFixture();
  f.list.node_details = {control: {tasks: f.detail.tasks, assignable_people: f.detail.assignable_people}};
  response = {status: 200, body: f.list};
  const list = await api.fetchNodeAssignments('p1', signal, () => true);
  const detail = api.overviewDetail(list, list.nodes[4]);
  assert.equal(detail.tasks[0].title, '控制點成果核對');
  assert.equal(detail.assignable_people[0].open_id, 'ou_anna');
  assert.equal(detail.node.revision, list.nodes[4].revision);
  assert.deepEqual(detail.can, list.can.control);
  delete f.list.node_details;
  response.body = f.list;
  const older = await api.fetchNodeAssignments('p1', signal, () => true);
  assert.equal(api.overviewDetail(older, older.nodes[4]), undefined);
  f.list.node_details = {control: {tasks: 'invalid', assignable_people: []}};
  await assert.rejects(api.fetchNodeAssignments('p1', signal, () => true), {message: '節點資料格式不正確，請稍後重試。'});
});
test('auto_done is carried as rule and reason, null stays null and a malformed one is rejected', async () => {
  const body = assignmentFixture().list;
  const at = key => body.nodes.find(n => n.key === key);
  at('sales').auto_done = {rule: 'c_code', reason: '工編以 C 開頭，業務階段已完成'};
  at('pm').auto_done = null;
  response = {status: 200, body};
  const list = await api.fetchNodeAssignments('p1', signal, () => true);
  const parsed = key => list.nodes.find(n => n.key === key);
  assert.deepEqual(parsed('sales').auto_done, {rule: 'c_code', reason: '工編以 C 開頭，業務階段已完成'});
  assert.equal(parsed('pm').auto_done, null);
  assert.equal(parsed('field').auto_done, undefined);
  at('sales').auto_done = {rule: 1};
  await assert.rejects(api.fetchNodeAssignments('p1', signal, () => true));
});
