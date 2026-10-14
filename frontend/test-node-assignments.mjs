import {fakeClock} from './fake-clock-fixture.mjs';
import assert from 'node:assert/strict';
import {test, afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture, projectFixture, visualAssignmentFixture} from './fixtures/node-assignments.mjs';

const dom = new JSDOM('<div id="root"></div>', {url: 'http://localhost/'});
for (const key of ['window', 'document', 'location', 'history', 'sessionStorage', 'Event', 'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement', 'HTMLSelectElement', 'navigator']) Object.defineProperty(globalThis, key, {value: dom.window[key], configurable: true});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);
globalThis.cancelAnimationFrame = clearTimeout;
HTMLElement.prototype.scrollIntoView = function () {};
const React = await import('react');
const {act} = React;
const {createRoot} = await import('react-dom/client');
const bundle = await build({stdin: {contents: "export {NodeAssignments} from './src/NodeAssignments'; export {ProjectDetail} from './src/ProjectDetail'; export {prefetchNodeAssignments} from './src/useNodeAssignments'; export {invalidateSessionEpoch} from './src/api';", resolveDir: new URL('.', import.meta.url).pathname}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
const path = new URL('./.node-assignments-test.mjs', import.meta.url);
await fs.writeFile(path, bundle.outputFiles[0].text);
let ui;
try {ui = await import(path.href)} finally {await fs.unlink(path)}
let root, fixture, requests, listReply, detailReply, mutationReply, holdMutation;
const reply = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
async function mount(options = {}) {
  ui.invalidateSessionEpoch(); fixture = assignmentFixture(); requests = []; listReply = options.listReply; detailReply = options.detailReply; mutationReply = options.mutationReply; holdMutation = null;
  if (options.change) options.change(fixture);
  globalThis.fetch = async (url, init = {}) => {
    const request = {url, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null}; requests.push(request);
    if (request.method !== 'GET') {if (holdMutation) await holdMutation; if (options.mutationFailure) throw options.mutationFailure(); return mutationReply ? reply(mutationReply.body, mutationReply.status) : reply({...fixture.detail, record_id: fixture.detail.node.record_id})}
    if (url.includes('/node-assignments/nodes/')) return detailReply ? reply(detailReply.body, detailReply.status) : reply({...fixture.detail, can: fixture.list.can.control, node: fixture.list.nodes.find(n => url.endsWith(`/nodes/${n.key}`))});
    if (url.endsWith('/node-assignments')) return listReply ? reply(listReply.body, listReply.status) : reply(fixture.list);
    return reply({detail: 'disabled'}, 404);
  };
  root = createRoot(document.getElementById('root'));
  await act(async () => root.render(React.createElement(ui.NodeAssignments, {projectId: 'p1', enabled: true, legacy: React.createElement('div', {id: 'legacy-flow'}, '原有案件流程與任務')})));
}
afterEach(async () => {if (root) {await act(async () => root.unmount()); root = null}});
const text = () => document.body.textContent;
const button = label => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === label);
const click = async element => {assert.ok(element, 'the requested control exists'); await act(async () => element.click())};
const expand = async () => click(document.querySelector('.na-row[aria-label^="控制節點"]'));
const mutations = () => requests.filter(r => r.method !== 'GET');
async function input(element, value) {
  assert.ok(element, 'the requested input exists');
  const prototype = element.tagName === 'SELECT' ? HTMLSelectElement.prototype : element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value); element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', {bubbles: true}))});
}
const formControl = label => [...document.querySelectorAll('.na-form label')].find(l => l.firstElementChild?.textContent.startsWith(label))?.querySelector('input,textarea,select');
const uuid = value => assert.match(value, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);

test('renders nine rows in chain order with literal task progress and 4/9 summary', async () => {
  await mount();
  assert.deepEqual([...document.querySelectorAll('.na-node-cell strong')].map(n => n.textContent), ['業務', 'PM', '確認單', '外業', '控制', '圖資', '報告', '計價', '結算']);
  assert.deepEqual([...document.querySelectorAll('.na-progress-cell strong')].map(n => n.textContent), ['3/3', '3/3', '3/3', '3/3', '2/5', '0/0', '0/0', '0/0', '0/0']);
  assert.equal(document.querySelector('.na-summary-count').textContent, '4/9');
  assert.equal(document.querySelector('.na-summary strong').textContent, '進行中');
  assert.equal(document.querySelectorAll('.na-flow-card').length, 9);
  assert.match(document.querySelector('[aria-current="step"]').getAttribute('aria-label'), /控制節點，進行中，林安娜、陳威廷/);
  assert.equal(document.getElementById('legacy-flow'), null);
  await click(document.querySelector('.na-summary'));
  assert.equal(document.activeElement.getAttribute('aria-label'), '案件節點清單');
});
test('expands inline into owners and tasks and collapses with its native button', async () => {
  await mount(); await expand();
  const detail = document.querySelector('[aria-label="控制節點明細"]');
  assert.equal(detail.querySelector('.na-people').textContent, '林林安娜陳陳威廷');
  assert.equal(detail.querySelector('.na-task-body strong').textContent, '控制點成果核對');
  assert.equal(detail.querySelector('.na-task-body p').textContent, '核對現場紀錄與座標。');
  assert.equal(detail.querySelector('select').value, '進行中');
  assert.equal(document.querySelector('.na-row[aria-expanded="true"]').getAttribute('aria-controls'), detail.parentElement.id);
  await expand(); assert.equal(document.querySelector('[aria-label="控制節點明細"]'), null);
});
test('claim applies the mutation envelope and revalidates only the list', async () => {
  await mount(); await expand(); await click(button('認領節點'));
  assert.equal(mutations()[0].url, '/api/projects/p1/node-assignments/nodes/control/claim');
  assert.equal(mutations()[0].method, 'POST'); uuid(mutations()[0].body.request_id);
  assert.deepEqual(Object.keys(mutations()[0].body), ['expected_revision', 'request_id']);
  assert.equal(requests.filter(r => r.url.endsWith('/node-assignments') && r.method === 'GET').length, 2);
  assert.equal(requests.filter(r => r.url.endsWith('/nodes/control') && r.method === 'GET').length, 1);
  assert.equal(document.querySelector('.na-notice').textContent, '已儲存變更。');
});
test('assign selects people and sends IDs with another fresh UUID', async () => {
  await mount(); await expand(); await click(button('認領節點')); await click(button('指派負責人'));
  const checkboxes = document.querySelectorAll('.na-person-options input');
  await click(checkboxes[1]); await click(button('儲存指派'));
  assert.equal(mutations()[1].url, '/api/projects/p1/node-assignments/nodes/control/assign');
  assert.deepEqual(mutations()[1].body.owner_open_ids, ['ou_anna']); uuid(mutations()[1].body.request_id);
  assert.notEqual(mutations()[1].body.request_id, mutations()[0].body.request_id);
  assert.equal(requests.filter(r => r.url.endsWith('/node-assignments') && r.method === 'GET').length, 3);
});
test('assignment requires at least one owner', async () => {
  await mount(); await expand(); await click(button('指派負責人'));
  for (const checkbox of document.querySelectorAll('.na-person-options input')) await click(checkbox);
  await click(button('儲存指派'));
  assert.equal(document.querySelector('.na-field-error').textContent, '請選擇 1 至 20 位負責人。'); assert.equal(mutations().length, 0);
});
test('task creation validates required fields before sending', async () => {
  await mount(); await expand(); await click(button('新增任務')); await click(button('建立任務'));
  assert.deepEqual([...document.querySelectorAll('.na-field-error')].map(e => e.textContent), ['請填寫任務名稱。']);
  assert.equal(mutations().length, 0);
  for (const element of document.querySelectorAll('[aria-invalid="true"]')) assert.ok(document.getElementById(element.getAttribute('aria-describedby')));
});
test('creates a task with literal fields and a date-only deadline', async () => {
  await mount(); await expand(); await click(button('新增任務'));
  await input(formControl('任務名稱'), '  新控制點核對  '); await input(formControl('任務說明'), '完成現場紀錄');
  await input(formControl('負責人'), 'ou_anna'); await input(formControl('部門'), '測量部'); await input(formControl('期限'), '2026-10-23');
  await click(button('建立任務'));
  const request = mutations()[0];
  assert.equal(request.url, '/api/projects/p1/node-assignments/nodes/control/tasks'); uuid(request.body.request_id);
  const {request_id, ...payload} = request.body;
  assert.deepEqual(payload, {title: '新控制點核對', detail: '完成現場紀錄', assignee_open_id: 'ou_anna', department: '測量部', deadline: '2026-10-23'});
  assert.equal(document.querySelector('.na-form'), null);
});
test('updates task status using PATCH and refetches', async () => {
  await mount(); await expand(); await input(document.querySelector('.na-task-status select'), '已完成');
  const request = mutations()[0]; assert.equal(request.method, 'PATCH'); assert.equal(request.url, '/api/projects/p1/node-assignments/nodes/control/tasks/recTask1'); assert.equal(request.body.status, '已完成'); uuid(request.body.request_id);
  assert.equal(requests.filter(r => r.url.endsWith('/node-assignments') && r.method === 'GET').length, 2);
});
test('permission-denied controls are disabled and explain why', async () => {
  await mount({change: f => {f.list.can.control = {claim: false, assign: false, complete: false, approve: false, reject: false, create_task: false}; f.detail.tasks[0].can.edit_status = false; f.detail.tasks[0].can.cancel = false}}); await expand();
  for (const label of ['認領節點', '指派負責人', '新增任務', '完成節點', '核准', '退回']) {
    const control = button(label); assert.equal(control.disabled, true); assert.equal(document.getElementById(control.getAttribute('aria-describedby')).textContent, '目前沒有此操作權限，或節點狀態不允許此操作。');
    assert.equal(control.parentElement.getAttribute('tabindex'), '0');
  }
  assert.equal(document.querySelector('.na-task-status select').disabled, true); assert.equal(mutations().length, 0);
});
test('409 refetches and shows someone else changed this message', async () => {
  await mount({mutationReply: {status: 409, body: {code: 'revision_conflict', detail: 'version changed'}}}); await expand(); await click(button('認領節點'));
  assert.equal(document.querySelector('.na-notice').textContent, '資料已被他人更新，已為你重新載入');
  assert.equal(requests.filter(r => r.url.endsWith('/node-assignments') && r.method === 'GET').length, 2);
});
test('422 maps server field errors onto the open form', async () => {
  await mount({mutationReply: {status: 422, body: {code: 'validation', detail: [{loc: ['body', 'reason'], msg: '請補充交付項目'}]}}}); await expand(); await click(button('退回'));
  await input(document.querySelector('.na-form textarea'), '成果缺少'); await click(button('確認退回'));
  assert.equal(document.querySelector('.na-error').textContent, '請檢查欄位內容後再試。');
  assert.equal(document.querySelector('.na-field-error').textContent, '請補充交付項目');
  assert.equal(document.querySelector('.na-form textarea').value, '成果缺少');
});
test('node complete approve and reject send the requested action', async () => {
  await mount(); await expand(); await click(button('完成節點')); await click(button('核准')); await click(button('退回')); await click(button('確認退回'));
  assert.equal(document.querySelector('.na-field-error').textContent, '請填寫退回原因。');
  await input(document.querySelector('.na-form textarea'), '  請補齊成果  '); await click(button('確認退回'));
  assert.deepEqual(mutations().map(r => r.url), ['/api/projects/p1/node-assignments/nodes/control/complete', '/api/projects/p1/node-assignments/nodes/control/approve', '/api/projects/p1/node-assignments/nodes/control/reject']);
  assert.equal(mutations()[2].body.reason, '請補齊成果'); assert.equal(new Set(mutations().map(r => r.body.request_id)).size, 3);
});
test('pending mutation disables controls and prevents repeat submissions', async () => {
  await mount(); await expand(); let release; holdMutation = new Promise(resolve => {release = resolve});
  await click(button('認領節點')); assert.equal(button('認領節點').disabled, true); assert.ok(text().includes('儲存中…'));
  await click(button('認領節點')); assert.equal(mutations().length, 1);
  await act(async () => release()); assert.equal(button('認領節點').disabled, false);
});
test('Lark permission read errors keep the graph skeleton', async () => {
  await mount({listReply: {status: 403, body: {code: 'lark_permission', detail: 'missing scope'}}});
  assert.equal(document.querySelector('.na-error span').textContent, 'Lark 權限不足，請聯絡管理員');
  assert.equal(document.getElementById('legacy-flow'), null);
});
test('Lark permission mutation errors keep the node list usable', async () => {
  await mount({mutationReply: {status: 403, body: {code: 'lark_permission', detail: 'missing scope'}}}); await expand(); await click(button('認領節點'));
  assert.equal(document.querySelector('.na-error span').textContent, 'Lark 權限不足，請聯絡管理員'); assert.equal(document.querySelectorAll('.na-row').length, 9); assert.equal(button('認領節點').disabled, false);
});
test('stale response displays the synchronization banner', async () => {
  await mount({change: f => {f.list.stale = true}});
  assert.equal(document.querySelector('.na-stale span').textContent, '目前顯示上次同步的資料，Lark 資料可能尚未更新。');
});
test('feature disabled by 404 or code leaves the original flow unchanged', async () => {
  for (const listReply of [{status: 404, body: {code: 'disabled', detail: 'disabled'}}, {status: 200, body: {code: 'disabled'}}]) {
    await mount({listReply}); assert.equal(document.getElementById('root').innerHTML, '<div id="legacy-flow">原有案件流程與任務</div>'); await act(async () => root.unmount()); root = null;
  }
});
test('empty nodes and empty tasks show explicit empty states', async () => {
  await mount({change: f => {f.list.nodes = []; f.list.summary = {done: 0, total: 0, current_node: null}}});
  assert.equal(document.querySelector('.na-empty').textContent, '尚未建立節點指派。重新讀取後再確認。');
  await act(async () => root.unmount()); root = null;
  await mount({change: f => {f.detail.tasks = []}}); await expand(); assert.equal(document.querySelector('.na-empty').textContent, '此節點尚無任務。新增任務後即可追蹤交付進度。');
});
test('detail failure stays local and can retry', async () => {
  await mount({detailReply: {status: 500, body: {detail: '節點讀取失敗'}}}); await expand();
  assert.equal(document.querySelector('.na-detail .na-error span').textContent, '節點讀取失敗'); assert.equal(document.querySelectorAll('.na-row').length, 9);
  detailReply = null; await click(button('重試')); assert.equal(document.querySelector('.na-task-body strong').textContent, '控制點成果核對');
});
test('completed case summary displays 已完成', async () => {
  await mount({change: f => {f.list.summary.done = 9}}); assert.equal(document.querySelector('.na-summary-count').textContent, '9/9'); assert.equal(document.querySelector('.na-summary strong').textContent, '已完成');
});
test('ProjectDetail integration leaves original stages and selected-node section intact on 404', async () => {
  await mount({listReply: {status: 404, body: {code: 'disabled', detail: 'disabled'}}});
  const {workspace, user} = projectFixture();
  const c = {w: workspace, s: {features: {node_assignment: true}, user, users: [user], mode: 'demo', auth_configured: false}, route: {view: 'project', project: 'p1', tab: 'flow', node: 'node_control'}, busy: false, go() {}, notify() {}, registerDrafts() {}, run: async () => undefined, refresh: async () => {}};
  await act(async () => root.render(React.createElement(ui.ProjectDetail, {c})));
  assert.deepEqual([...document.querySelectorAll('.stage-button strong')].map(n => n.textContent), ['業務', 'PM', '確認單', '外業', '控制', '圖資', '報告', '計價', '結算']);
  assert.equal(document.querySelector('.flow-heading h2').textContent, '案件流程');
  assert.equal(document.querySelector('.node-section .node-title h2').textContent, '控制進行中');
  assert.equal(document.querySelector('.flow-operations h2').textContent, '本階段交付與確認');
  assert.equal(document.querySelector('.node-assignments'), null); assert.equal(document.querySelector('.na-loading'), null);
  assert.equal(document.querySelector('.project-discussion h2').textContent, '案件討論');
});
test('ProjectDetail supports assignments when the legacy project has no nodes', async () => {
  await mount(); const {workspace, user} = projectFixture(); workspace.projects[0].nodes = [];
  const c = {w: workspace, s: {features: {node_assignment: true}, user, users: [user], mode: 'demo', auth_configured: false}, route: {view: 'project', project: 'p1', tab: 'flow'}, busy: false, go() {}, notify() {}, registerDrafts() {}, run: async () => undefined, refresh: async () => {}};
  await act(async () => root.render(React.createElement(ui.ProjectDetail, {c})));
  assert.equal(document.querySelectorAll('.na-row').length, 9); assert.equal(text().includes('尚未建立案件流程'), false); assert.equal(document.querySelector('.major-approval-summary h2').textContent, '重大事項審批');
});
test('task status validation attaches the server message to its select', async () => {
  await mount({mutationReply: {status: 422, body: {code: 'validation', detail: {status: '請先補齊成果'}}}}); await expand(); await input(document.querySelector('.na-task-status select'), '已完成');
  const select = document.querySelector('.na-task-status select'); assert.equal(select.getAttribute('aria-invalid'), 'true'); assert.equal(document.getElementById(select.getAttribute('aria-describedby')).textContent, '請先補齊成果'); assert.equal(select.value, '進行中');
});
test('failed list refresh keeps rows but blocks stale mutation permissions until retry', async () => {
  await mount(); await expand(); listReply = {status: 500, body: {detail: '清單更新失敗'}}; await click(button('重新讀取'));
  assert.equal(document.querySelector('.na-error span').textContent, '清單更新失敗'); assert.equal(document.querySelectorAll('.na-row').length, 9); assert.equal(button('認領節點').disabled, true);
  listReply = null; await click(button('重試')); assert.equal(button('認領節點').disabled, false); assert.equal(document.querySelector('.na-error'), null);
});
test('initial loading shows the real graph skeleton without legacy', async () => {
  await mount(); let release; const waiting = new Promise(resolve => {release = resolve});
  globalThis.fetch = async () => {await waiting; return reply(assignmentFixture().list)};
  await act(async () => root.render(React.createElement(ui.NodeAssignments, {key: 'loading', projectId: 'p2', enabled: true, legacy: React.createElement('div', {id: 'legacy-flow'}, '原有案件流程與任務')})));
  try {assert.ok(!document.querySelector('.na-loading')); assert.equal(document.getElementById('legacy-flow'), null); assert.equal(document.querySelectorAll('.is-skeleton').length, 9)}
  finally {await act(async () => release())}
  await act(async () => {}); assert.equal(document.querySelector('.na-summary-count').textContent, '4/9');
});
test('write gate disables mutations and displays the server reason', async () => {
  await mount({change: f => {f.list.writes_enabled = false; f.list.writes_disabled_reason = 'external_enabled 已關閉'}}); await expand();
  assert.ok(text().includes('external_enabled 已關閉'));
  for (const control of document.querySelectorAll('.na-detail button, .na-detail select')) assert.equal(control.disabled, true);
  assert.equal(mutations().length, 0);
});
test('task permissions allow member status edits independently of node completion', async () => {
  await mount({change: f => {f.list.can.control.complete = false; f.detail.tasks[0].can.cancel = false; f.detail.assignable_people = []}}); await expand();
  assert.equal(button('完成節點').disabled, true);
  const select = document.querySelector('.na-task-status select'); assert.equal(select.disabled, false);
  assert.equal([...select.options].some(o => o.value === '取消'), false);
  await input(select, '已完成'); assert.equal(mutations()[0].body.expected_revision, '9b0c1d2e3f405162');
});
test('members create self-assigned tasks with optional fields omitted', async () => {
  await mount({change: f => {f.detail.assignable_people = []}}); await expand(); await click(button('新增任務'));
  assert.equal(formControl('負責人'), undefined);
  await input(formControl('任務名稱'), '自己的任務'); await click(button('建立任務'));
  const {request_id, ...body} = mutations()[0].body; uuid(request_id); assert.deepEqual(body, {title: '自己的任務'});
});
test('uncertain outcomes retry the exact request ID and body, then a new action gets a new ID', async () => {
  for (const code of ['outcome_unknown', 'readback_mismatch']) {
    await mount({mutationReply: {status: code === 'outcome_unknown' ? 502 : 409, body: {code, detail: 'uncertain'}}}); await expand(); await click(button('認領節點'));
    assert.ok(text().includes('請重試此操作')); assert.equal(requests.filter(r => r.url.endsWith('/node-assignments')).length, 1);
    mutationReply = null; await click(button('重試'));
    assert.deepEqual(mutations()[1].body, mutations()[0].body);
    await click(button('認領節點')); assert.notEqual(mutations()[2].body.request_id, mutations()[0].body.request_id);
    await act(async () => root.unmount()); root = null;
  }
});
test('illegal transitions do not masquerade as revision conflicts', async () => {
  await mount({mutationReply: {status: 409, body: {code: 'illegal_transition', detail: 'invalid status'}}}); await expand(); await click(button('完成節點'));
  assert.ok(text().includes('目前狀態不允許此操作')); assert.equal(document.querySelector('.na-notice'), null);
});
test('node revisions come from detail and refresh before the next action', async () => {
  await mount(); fixture.detail.node = {...fixture.detail.node, revision: 'aaaaaaaaaaaaaaaa'};
  // Detail replies use the current overview node, as the real server does after a fresh read.
  fixture.list.nodes.find(n => n.key === 'control').revision = 'aaaaaaaaaaaaaaaa';
  await expand(); await click(button('認領節點')); assert.equal(mutations()[0].body.expected_revision, 'aaaaaaaaaaaaaaaa');
  fixture.list.nodes.find(n => n.key === 'control').revision = 'bbbbbbbbbbbbbbbb';
  await click(button('重新讀取')); await click(button('完成節點')); assert.equal(mutations()[1].body.expected_revision, 'bbbbbbbbbbbbbbbb');
});

test('non-assignable owners are excluded from assignment submissions', async () => {
  await mount({change: f => {f.detail.assignable_people = f.detail.assignable_people.slice(0, 1)}}); await expand(); await click(button('指派負責人'));
  await click(button('儲存指派')); assert.deepEqual(mutations()[0].body.owner_open_ids, ['ou_anna']);
});
test('managers can create unassigned tasks in a node department', async () => {
  await mount({change: f => {f.detail.node.departments = ['外業', '水深A']}}); await expand(); await click(button('新增任務'));
  assert.ok(text().includes('未選擇則建立未指派任務')); assert.equal(text().includes('未選擇則由自己負責'), false);
  assert.deepEqual([...formControl('部門').options].map(o => o.value), ['', '外業', '水深A']);
  await input(formControl('任務名稱'), '未指派任務'); await input(formControl('部門'), '水深A'); await click(button('建立任務'));
  assert.equal(mutations()[0].body.department, '水深A'); assert.equal('assignee_open_id' in mutations()[0].body, false);
});
test('missing tasks show the server message and refresh without disabling the panel', async () => {
  await mount({mutationReply: {status: 404, body: {code: 'not_found', detail: '此節點沒有這個任務，請重新整理'}}}); await expand(); await input(document.querySelector('.na-task-status select'), '已完成');
  assert.equal(document.querySelectorAll('.na-row').length, 9); assert.ok(text().includes('此節點沒有這個任務，請重新整理'));
  assert.equal(requests.filter(r => r.url.endsWith('/node-assignments')).length, 2);
});
test('string validation detail is displayed in the task form', async () => {
  await mount({mutationReply: {status: 422, body: {code: 'invalid', detail: '請選擇任務所屬部門'}}}); await expand(); await click(button('新增任務'));
  await input(formControl('任務名稱'), '任務'); await click(button('建立任務')); assert.ok(text().includes('請選擇任務所屬部門'));
});
for (const kind of ['timeout', 'network', 'abort']) test(`${kind} retries retain the ID for the same form and replace it for changed values`, async () => {
  let fail = true;
  const timer = globalThis.setTimeout;
  if (kind === 'timeout') globalThis.setTimeout = (fn, ms, ...args) => timer(fn, ms === 20000 ? 1 : ms, ...args);
  try {
    await mount({mutationFailure: () => kind === 'abort' ? new DOMException('aborted', 'AbortError') : new TypeError('Failed to fetch')});
    const fetch = globalThis.fetch;
    globalThis.fetch = (url, init) => init?.method === 'POST' && kind === 'timeout' && fail ? new Promise(() => {requests.push({url, method: 'POST', body: JSON.parse(init.body)})}) : fetch(url, init);
    await expand(); await click(button('新增任務')); await input(formControl('任務名稱'), '任務'); await click(button('建立任務'));
    if (kind === 'timeout') await act(async () => {await new Promise(resolve => timer(resolve, 10))});
    await click(button('建立任務'));
    if (kind === 'timeout') await act(async () => {await new Promise(resolve => timer(resolve, 10))});
    assert.deepEqual(mutations()[1].body, mutations()[0].body);
    await input(formControl('任務名稱'), '不同任務'); await click(button('建立任務'));
    if (kind === 'timeout') await act(async () => {await new Promise(resolve => timer(resolve, 10))});
    assert.notEqual(mutations()[2].body.request_id, mutations()[0].body.request_id); fail = false;
  } finally {globalThis.setTimeout = timer}
});
for (const status of [403, 404, 409, 413, 422, 429]) test(`definitive ${status} clears the retained attempt`, async () => {
  await mount({mutationReply: {status: 502, body: {code: 'outcome_unknown', detail: '未知'}}}); await expand(); await click(button('認領節點'));
  mutationReply = {status, body: {code: 'invalid', detail: '拒絕'}}; await click(button('認領節點'));
  assert.equal(mutations()[1].body.request_id, mutations()[0].body.request_id);
  await click(button('認領節點')); assert.notEqual(mutations()[2].body.request_id, mutations()[0].body.request_id);
});

for (const response of [
  {status: 409, code: 'busy'}, {status: 502}, {status: 503}, {status: 504},
  {status: 503, code: 'lark_unavailable'}, {status: 503, code: 'roster_unavailable'},
]) test(`uncertain create then ${response.status}/${response.code} keeps the retry ID`, async () => {
  await mount({mutationReply: {status: 408, body: {code: 'client_timeout', detail: 'timeout'}}});
  await expand(); await click(button('新增任務')); await input(formControl('任務名稱'), '任務'); await click(button('建立任務'));
  mutationReply = {status: response.status, body: {code: response.code, detail: 'retry later'}};
  await click(button('建立任務')); await click(button('建立任務'));
  assert.deepEqual(mutations()[2].body, mutations()[0].body);
});
for (const form of [
  {open: '新增任務', submit: '建立任務', field: '任務名稱'},
  {open: '指派負責人', submit: '儲存指派'},
  {open: '退回', submit: '確認退回', field: '退回原因'},
]) for (const close of ['取消', form.open]) test(`${form.open} ${close} abandons the uncertain retry`, async () => {
  await mount({mutationReply: {status: 502, body: {code: 'outcome_unknown', detail: 'unknown'}}}); await expand();
  await click(button(form.open)); if (form.field) await input(formControl(form.field), '任務'); await click(button(form.submit));
  await click(button(close)); await click(button(form.open));
  if (form.field) await input(formControl(form.field), '任務'); await click(button(form.submit));
  assert.notEqual(mutations()[1].body.request_id, mutations()[0].body.request_id);
});

for (const code of ['lark_unconfigured', 'writes_disabled']) test(`pre-write ${code} clears the retained attempt`, async () => {
  await mount({mutationReply: {status: 408, body: {code: 'client_timeout', detail: 'timeout'}}}); await expand(); await click(button('認領節點'));
  mutationReply = {status: 503, body: {code, detail: 'disabled'}};
  await click(button('認領節點')); await click(button('認領節點'));
  assert.notEqual(mutations()[2].body.request_id, mutations()[0].body.request_id);
});

test('absent or false session feature renders legacy with no assignment request', async () => {
  await mount();
  const {workspace, user} = projectFixture();
  for (const features of [undefined, {node_assignment: false}]) {
    requests = [];
    const c = {w: workspace, s: {features, user, users: [user], mode: 'demo', auth_configured: false}, route: {view: 'project', project: 'p1', tab: 'flow'}, busy: false, go() {}, notify() {}, registerDrafts() {}, run: async () => undefined, refresh: async () => {}};
    await act(async () => root.render(React.createElement(ui.ProjectDetail, {c})));
    assert.ok(document.querySelector('.workflow'));
    assert.equal(document.querySelector('.node-assignments'), null);
    assert.equal(requests.length, 0);
  }
});
test('cached reopen paints instantly and session invalidation removes cached data', async () => {
  await mount();
  await act(async () => root.unmount()); root = createRoot(document.getElementById('root'));
  let release;
  globalThis.fetch = async () => {await new Promise(resolve => {release = resolve}); return reply(fixture.list)};
  const props = {projectId: 'p1', enabled: true, legacy: React.createElement('div', {id: 'legacy-flow'})};
  await act(async () => root.render(React.createElement(ui.NodeAssignments, props)));
  assert.equal(document.querySelectorAll('.na-flow-card:not(.is-skeleton)').length, 9);
  assert.ok(text().includes('更新中…'));
  await act(async () => release());
  await act(async () => root.unmount()); ui.invalidateSessionEpoch(); root = createRoot(document.getElementById('root'));
  await act(async () => root.render(React.createElement(ui.NodeAssignments, props)));
  assert.equal(document.querySelectorAll('.is-skeleton').length, 9);
  assert.equal(document.getElementById('legacy-flow'), null);
  await act(async () => release());
});
test('no request on another tab; opening flow makes one shared request', async () => {
  await mount(); ui.invalidateSessionEpoch(); requests = [];
  const {workspace, user} = projectFixture();
  let release;
  globalThis.fetch = async url => {if (!url.endsWith('/node-assignments')) return reply({items: [], total: 0}); requests.push({url, method: 'GET'}); await new Promise(resolve => {release = resolve}); return reply(fixture.list)};
  const c = {w: workspace, s: {features: {node_assignment: true}, user, users: [user], mode: 'demo', auth_configured: false}, route: {view: 'project', project: 'p1', tab: 'logs'}, busy: false, go() {}, notify() {}, registerDrafts() {}, run: async () => undefined, refresh: async () => {}};
  await act(async () => root.render(React.createElement(ui.ProjectDetail, {c})));
  assert.equal(requests.length, 0, 'no node-assignment request while another tab is open');
  await act(async () => root.render(React.createElement(ui.ProjectDetail, {c: {...c, route: {...c.route, tab: 'flow'}}})));
  assert.equal(requests.length, 1, 'opening flow issues exactly one shared request');
  assert.equal(document.querySelectorAll('.is-skeleton').length, 9);
  assert.equal(document.querySelector('.workflow'), null);
  await act(async () => release());
});
test('embedded detail expands without a GET and mutations paint before revalidation', async () => {
  await mount({change: f => {f.list.node_details = {control: {tasks: f.detail.tasks, assignable_people: f.detail.assignable_people}}}});
  await expand();
  assert.equal(requests.filter(r => r.url.includes('/nodes/')).length, 0);
  let release;
  const original = globalThis.fetch;
  fixture.detail.tasks[0].title = '已儲存的新成果';
  globalThis.fetch = async (url, init) => {
    if (!init?.method && url.endsWith('/node-assignments')) {requests.push({url, method: 'GET'}); await new Promise(resolve => {release = resolve}); return reply(fixture.list)}
    return original(url, init);
  };
  await click(button('認領節點'));
  assert.equal(document.querySelector('.na-task-body strong').textContent, '已儲存的新成果');
  assert.equal(requests.filter(r => r.url.includes('/nodes/') && r.method === 'GET').length, 0);
  await act(async () => release());
});
test('graph groups parallel production cards and exposes colors, owners, progress and overdue deadlines', async () => {
  const visual = visualAssignmentFixture();
  await mount({change: f => Object.assign(f, visual)});
  assert.equal(document.querySelectorAll('.na-flow-group').length, 2);
  assert.deepEqual([...document.querySelectorAll('.na-production-cards .na-card-top>strong')].map(n => n.textContent), ['外業', '控制', '圖資', '報告']);
  assert.equal(document.querySelectorAll('.na-production-cards .na-flow-arrow').length, 0);
  const card = document.querySelector('.na-flow-card[aria-current="step"]');
  assert.ok(card.classList.contains('is-current'));
  assert.ok(card.querySelector('.na-status-active'));
  assert.ok(card.querySelector('.na-avatar').className.includes('na-person-color-'));
  assert.ok(card.textContent.includes('3/5 項任務60%'));
  assert.ok(card.querySelector('.is-overdue').textContent.includes('逾期'));
  assert.ok(card.querySelector('.na-warning-dot'));
  assert.equal(document.querySelectorAll('.na-flow-arrow.is-done').length, 3);
  // Native buttons expose keyboard activation and the selected panel relationship.
  card.focus(); assert.equal(document.activeElement, card);
  await click(card);
  assert.equal(card.getAttribute('aria-expanded'), 'true');
  assert.ok(card.classList.contains('is-selected'));
  assert.ok(document.querySelector('[aria-label="外業節點明細"]'));
});


test('flow owners use the shared avatar and recover to the initial on image failure', async () => {
  await mount({change: fixture => {fixture.list.nodes[1].owners = [{open_id: 'ou_photo', name: '王怡婷', avatar_url: 'https://s16-imfile-sg.feishucdn.com/photo'}]}});
  const img = document.querySelector('.na-flow-card .na-avatar img');
  assert.equal(img.getAttribute('src'), 'https://s16-imfile-sg.feishucdn.com/photo');
  assert.equal(img.getAttribute('alt'), '王怡婷');
  const avatar = img.parentElement;
  await act(async () => img.dispatchEvent(new Event('error')));
  assert.equal(avatar.textContent, '王');
  assert.equal(avatar.querySelector('img'), null);
});

test('automatic refresh preserves a focused status select and never blocks idle controls',async()=>{
 const clock=fakeClock(dom.window);
 try{
  await mount();await expand();
  const select=document.querySelector('.na-task-status select');assert.ok(select);
  select.focus();const count=requests.length;
  await act(async()=>clock.advance(60000));
  assert.equal(requests.length,count,'focused node panel skips polling');
  assert.equal(document.activeElement,select);assert.equal(select.disabled,false);
  select.blur();let finish;const original=globalThis.fetch;
  globalThis.fetch=(url,init)=>url.endsWith('/node-assignments')?new Promise(resolve=>{finish=resolve}):original(url,init);
  await act(async()=>clock.advance(60000));
  assert.equal(select.disabled,false,'idle background read does not block status edits');
  await act(async()=>finish(reply(fixture.list)));
  await click(button('重新讀取'));
  await act(async()=>document.dispatchEvent(new Event('visibilitychange')));
  await act(async()=>finish(reply(fixture.list)));
  assert.equal(button('重新讀取')?.disabled,false,'visibility polling cannot leave manual refresh stuck');
 }finally{clock.restore()}
});
