import assert from 'node:assert/strict';
import {afterEach, test} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture, projectFixture} from './fixtures/node-assignments.mjs';

const dom = new JSDOM('<div id="root"></div>', {url: 'http://localhost/'});
for (const key of ['window', 'document', 'location', 'history', 'sessionStorage', 'Event', 'HTMLElement', 'HTMLInputElement', 'HTMLTextAreaElement', 'HTMLSelectElement', 'navigator']) Object.defineProperty(globalThis, key, {value: dom.window[key], configurable: true});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);
globalThis.cancelAnimationFrame = clearTimeout;
HTMLElement.prototype.scrollIntoView = function () {};
const React = await import('react');
const {act} = React;
const {createRoot} = await import('react-dom/client');
const bundle = await build({stdin: {contents: "export {ProjectDetail, ApprovalForm, contractItemOrder, sourceFieldValue} from './src/ProjectDetail'; export {DailyRecords, dailyRecordOrder} from './src/DailyRecords'; export {auditRecordOrder} from './src/AuditTrail'; export {assignmentTarget, sortAssignmentTasks} from './src/nodeAssignmentApi'; export {invalidateSessionEpoch} from './src/api';", resolveDir: new URL('.', import.meta.url).pathname}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
const artifact = new URL('./.ux-case-detail-test.mjs', import.meta.url);
await fs.writeFile(artifact, bundle.outputFiles[0].text);
let ui;
try {ui = await import(artifact.href)} finally {await fs.unlink(artifact)}
let root;
afterEach(async () => {if (root) await act(async () => root.unmount()); root = null});
const reply = body => new Response(JSON.stringify(body), {headers: {'Content-Type': 'application/json'}});
function context(route = {tab: 'flow'}) {
  const {workspace, user} = projectFixture();
  return {w: workspace, s: {features: {node_assignment: true, change_extension: false, routines: false}, user, users: [user], mode: 'demo', auth_configured: false}, route: {view: 'project', project: 'p1', ...route}, busy: false, go() {}, notify() {}, registerDrafts() {}, run: async () => undefined, refresh: async () => {}};
}
async function mount(element) {
  root = createRoot(document.getElementById('root'));
  await act(async () => root.render(element));
  await act(async () => new Promise(resolve => setTimeout(resolve, 10)));
}
function sourceFixture() {
  const fixture = assignmentFixture();
  fixture.list.node_details = {control: {tasks: fixture.detail.tasks, assignable_people: fixture.detail.assignable_people}};
  fixture.list.fetched_at = '2026-10-15T08:00:00+08:00';
  return fixture;
}

test('home node and task targets preserve legacy identities', () => {
  assert.deepEqual(ui.assignmentTarget({node: 'control', task: 'recTask1'}), {nodeKey: 'control', taskId: 'recTask1'});
  assert.deepEqual(ui.assignmentTarget({task: 'recTask1'}), {nodeKey: '', taskId: 'recTask1'});
  assert.equal(ui.assignmentTarget({node: 'node_control', task: 'local-task'}, [{id: 'node_control', key: 'control'}]), undefined);
});
test('home deep link expands the real node and focuses the task without a legacy inspector', async () => {
  ui.invalidateSessionEpoch(); const fixture = sourceFixture();
  globalThis.fetch = async () => reply(fixture.list);
  await mount(React.createElement(ui.ProjectDetail, {c: context({tab: 'flow', node: 'control', task: 'recTask1'})}));
  assert.equal(document.querySelector('#flow-selected').getAttribute('aria-label'),'控制節點明細');
  assert.ok(document.querySelector('[data-assignment-task="recTask1"]'));
  assert.equal(document.querySelector('[aria-label="任務名稱"]').value,'控制點成果核對');
  assert.equal(document.querySelector('.task-inspector'), null);
  assert.ok(!document.body.textContent.includes('找不到此任務'));
  assert.match(document.querySelector('.pf-source').textContent,/Lark 節點與任務/);
});
test('a task-only link discovers its node from authorized embedded tasks', async () => {
  ui.invalidateSessionEpoch(); const fixture = sourceFixture();
  globalThis.fetch = async () => reply(fixture.list);
  await mount(React.createElement(ui.ProjectDetail, {c: context({tab: 'tasks', task: 'recTask1'})}));
  assert.equal(document.querySelector('#flow-selected').getAttribute('aria-label'),'控制節點明細');
  assert.equal(document.querySelector('[aria-label="任務名稱"]').value,'控制點成果核對');
});
test('unknown remote tasks have a readable scoped error', async () => {
  ui.invalidateSessionEpoch(); const fixture = sourceFixture();
  globalThis.fetch = async () => reply(fixture.list);
  await mount(React.createElement(ui.ProjectDetail, {c: context({tab: 'flow', node: 'control', task: 'recMissing'})}));
  assert.ok(document.body.textContent.includes('找不到此 Lark 任務'));
  assert.equal(document.querySelector('.task-drawer[data-kind=legacy]'), null);
});
test('zero Lark tasks remain separate from expandable local templates', async () => {
  ui.invalidateSessionEpoch(); const fixture = sourceFixture();
  fixture.list.node_details = Object.fromEntries(fixture.list.nodes.map(n=>[n.key,{tasks:[],assignable_people:[]}]));
  fixture.list.nodes = fixture.list.nodes.map(n => ({...n, tasks: {done: 0, total: 0}, progress: 0, derived_status: '未開始'}));
  fixture.list.summary = {done: 0, total: 9, current_node: 'sales'};
  globalThis.fetch = async () => reply(fixture.list);
  await mount(React.createElement(ui.ProjectDetail, {c:context({tab:'flow',node:'sales'})}));
  assert.equal(document.querySelectorAll('#flow-tasks .pf-task-open').length,0);
  assert.equal(document.querySelector('.pf-legacy').open,false);
  assert.match(document.querySelector('#flow-tasks').textContent,/尚無任務/);
});
test('an unavailable remote link does not pretend to focus local workflow', async () => {
  ui.invalidateSessionEpoch();
  const c=context({tab:'flow',node:'control',task:'recTask1'});c.s.features.node_assignment=false;
  await mount(React.createElement(ui.ProjectDetail,{c}));
  assert.ok(document.body.textContent.includes('節點指派尚未開放，無法定位此 Lark 節點或任務。'));
  assert.equal(document.querySelector('[data-assignment-task]'), null);
});
test('opening logs does not read assignments before the flow tab is selected', async () => {
  ui.invalidateSessionEpoch(); const fixture = sourceFixture(), requests = [];
  globalThis.fetch = async url => {requests.push(url); return reply(url.endsWith('/node-assignments') ? fixture.list : {items: [], total: 0})};
  const c = context({tab: 'logs'});
  await mount(React.createElement(ui.ProjectDetail, {c}));
  assert.equal(requests.filter(url => url.endsWith('/node-assignments')).length, 0);
  await act(async () => root.render(React.createElement(ui.ProjectDetail, {c: {...c, route: {...c.route, tab: 'flow'}}})));
  assert.equal(requests.filter(url => url.endsWith('/node-assignments')).length, 1);
});
test('disabled approval form has no creation controls or mutations', async () => {
  ui.invalidateSessionEpoch(); const c = context(); let writes = 0;
  c.run = async () => {writes++; return undefined};
  await mount(React.createElement(ui.ApprovalForm, {c, p: c.w.projects[0], type: 'change', onClose() {}}));
  assert.ok(document.body.textContent.includes('變更與展延尚未開放'));
  assert.equal(document.querySelector('form'), null);
  assert.equal(writes, 0);
});
test('daily reports preserve business date crew and unknown points', async () => {
  ui.invalidateSessionEpoch(); const c = context();
  globalThis.fetch = async () => reply({items: [{id: 'one', date: '2026-07-15', department: '水深D', person: '甲、乙', points: null, description: '測量', project_id: 'p1', project_code: 'C115264', review: {status: 'unknown'}}], total: 1, summary: {unmatched: 0}, coverage: {scope: 'visible_cases', project_only: true, unmatched_available: false}, last_sync: '2026-10-15T08:00:00+08:00'});
  await mount(React.createElement(ui.DailyRecords, {w: c.w, p: c.w.projects[0], go() {}}));
  assert.equal(document.querySelector('.daily-cards article header strong').textContent, '2026-07-15 · 水深D');
  assert.equal(document.querySelector('.daily-cards article header span').textContent, '甲、乙');
  assert.ok(document.body.textContent.includes('公布點數 來源未提供'));
  assert.ok(!document.body.textContent.includes('公布點數 0'));
});
test('literal date number and status sorts keep unknown values last', () => {
  const fixture = assignmentFixture().detail.tasks[0];
  const tasks = [{...fixture, id: 'recNull', deadline: null}, {...fixture, id: 'recDone', deadline: '2026-10-01', status: '已完成'}, {...fixture, id: 'recB', deadline: '2026-10-14', status: '待處理'}, {...fixture, id: 'recA', deadline: '2026-10-14', status: '待處理'}, {...fixture, id: 'recActive', deadline: '2026-10-14'}];
  assert.deepEqual(ui.sortAssignmentTasks(tasks, '2026-10-15').map(t => t.id), ['recActive', 'recA', 'recB', 'recDone', 'recNull']);
  assert.deepEqual([{id: 'none'}, {id: 'ten', item_number: '10'}, {id: 'two', item_number: '2'}].sort(ui.contractItemOrder).map(r => r.id), ['two', 'ten', 'none']);
  assert.deepEqual([{id: 'none'}, {id: 'a', date: '2026-10-15'}, {id: 'b', date: '2026-10-15'}].sort(ui.dailyRecordOrder).map(r => r.id), ['a', 'b', 'none']);
  assert.deepEqual([{id: 'none'}, {id: 'old', created_at: '2026-10-14'}, {id: 'new', created_at: '2026-10-15'}].sort(ui.auditRecordOrder).map(r => r.id), ['new', 'old', 'none']);
  assert.equal(ui.sourceFieldValue(null), '來源未提供');
  assert.equal(ui.sourceFieldValue([]), '來源未提供');
  assert.equal(ui.sourceFieldValue(0), '0');
  assert.equal(ui.sourceFieldValue('   '), '來源未提供');
  assert.equal(ui.sourceFieldValue(0.0000001), '0.0000001');
  assert.equal(ui.sourceFieldValue([{name: '甲'}, {name: '乙'}]), '甲、乙');
});
