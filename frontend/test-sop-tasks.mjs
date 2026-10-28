import assert from 'node:assert/strict';
import {test, afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom = new JSDOM('<div id="root"></div>', {url: 'http://localhost/', pretendToBeVisual: true});
for (const k of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','Element','HTMLElement','Node','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','navigator','DOMException']) Object.defineProperty(globalThis, k, {value: dom.window[k], configurable: true});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.getComputedStyle = dom.window.getComputedStyle;
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);
HTMLElement.prototype.scrollIntoView = function () {};
HTMLElement.prototype.getClientRects = function () {return [{width: 40, height: 40}]};
const React = await import('react'); const {act} = React; const {createRoot} = await import('react-dom/client');
const bundle = await build({stdin: {contents: "export * from './src/sopTaskApi';export * from './src/sopTaskModel';export {useSopTasks,defaultImportNodes} from './src/useSopTasks';export {SopTasks} from './src/SopTasks';export {invalidateSessionEpoch} from './src/api';", resolveDir: import.meta.dirname}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
const path = new URL('./.sop-tasks-test.mjs', import.meta.url); await fs.writeFile(path, bundle.outputFiles[0].text); let ui; try {ui = await import(path.href)} finally {await fs.unlink(path)}
const examples = JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json', import.meta.url), 'utf8'));
const clone = v => JSON.parse(JSON.stringify(v));
const NODES = ['sales','pm','confirmation','field','control','mapping','report','pricing','settlement'];
const zero = () => ({done: 0, total: 0, unresolved: 0, not_applicable: 0, archived: 0});

function task(id, patch = {}) {
 const t = clone(examples.sop_tasks.tasks[0]);
 return {...t, id, ...patch, is_shared: patch.is_shared ?? (patch.nodes?.length > 1 || t.is_shared), is_conditional: patch.is_conditional ?? (patch.applicability === 'unresolved' || t.is_conditional), local: {...t.local, ...(patch.local || {})}, origin: {...t.origin, ...(patch.origin || {})}};
}
function overview(tasks) {
 const o = clone(examples.sop_tasks);
 const counts = list => {const active = list.filter(t => t.state !== 'archived'), app = active.filter(t => t.applicability === 'applicable'); return {done: app.filter(t => t.state === 'done').length, total: app.length, unresolved: active.filter(t => t.applicability === 'unresolved').length, not_applicable: active.filter(t => t.applicability === 'not_applicable').length, archived: list.length - active.length}};
 return {...o, scope: {node_key: null}, tasks, case_counts: counts(tasks), counts: counts(tasks), node_counts: Object.fromEntries(NODES.map(k => [k, counts(tasks.filter(t => t.nodes.some(n => n.node_key === k)))]))};
}
const link = (node_key, order) => ({node_key, node_id: `p1-${node_key}`, order});
const outcome = (key, title, patch = {}) => ({...clone(examples.preview.outcomes[1]), source_row_key: key, title, ...patch});
function previewFixture(body) {
 const p = clone(examples.preview);
 p.preview_id = `preview-${body.row_keys ? 'custom' : 'default'}`;
 p.nodes = NODES.map(k => ({node_key: k, node_id: `p1-${k}`}));
 p.outcomes = [
  outcome('meegle-v137:A:0', 'Start', {disposition: 'routing_reference', outcome: 'routing_reference', selected: false, links_to_add: []}),
  outcome('meegle-v137:A:1', '業主提出報價需求'),
  outcome('meegle-v137:A:7', '下包提出報價', {selected: false, outcome: 'excluded', applicability: 'unresolved', links_to_add: []}),
  outcome('meegle-v137:A:22', '確認單修正', {applicability: 'unresolved'}),
  outcome('meegle-v137:A:42', '範本待審項目', {disposition: 'review_required', outcome: 'review_required', selected: false, links_to_add: []}),
  outcome('meegle-v137:A:2', '建立報價編號', {selected: false, outcome: 'excluded', links_to_add: []}),
 ];
 const selected = body.row_keys || ['meegle-v137:A:1', 'meegle-v137:A:22'];
 p.outcomes = p.outcomes.map(o => o.disposition === 'task' ? {...o, selected: selected.includes(o.source_row_key), outcome: selected.includes(o.source_row_key) ? 'new' : 'excluded'} : o);
 p.selection = {...p.selection, node_keys: body.node_keys || NODES, row_keys: [...selected].sort()};
 p.counts = {new_tasks: selected.length, existing_tasks: 0, added_links: selected.length};
 return p;
}

let root, c, server, calls;
const tick = () => new Promise(r => setTimeout(r, 10));
const response = (b, s = 200) => new Response(JSON.stringify(b), {status: s, headers: {'Content-Type': 'application/json'}});
function Harness() {const sop = ui.useSopTasks('p1', 'w1'); const [importing, setImporting] = React.useState(null); return React.createElement(ui.SopTasks, {c, p: {id: 'p1', pm_id: 'pm', collaborator_ids: ['member'], nodes: []}, nodeKey: c.route.node, sop, importing, setImporting})}
const render = () => root.render(React.createElement(Harness));
async function mount({tasks = [task('t1')], route = {}, role = 'pm', overviewStatus = 200, extra = {}} = {}) {
 ui.invalidateSessionEpoch();
 server = {overview: {...overview(tasks), ...extra}, apply: [], run: [], patch: []};
 calls = [];
 c = {s: {user: {id: 'pm', role, capabilities: ['sop_task_read']}, workspace_id: 'w1'}, w: {users: [{id: 'pm', name: '王經理', role: 'pm', capabilities: ['sop_task_work']}, {id: 'member', name: '林組員', role: 'member', capabilities: ['sop_task_work']}, {id: 'outsider', name: '外部', role: 'member', capabilities: ['sop_task_work']}]},
  route: {view: 'project', project: 'p1', tab: 'flow', node: 'sales', ...route}, go(next) {c = {...c, route: next}; render()}};
 globalThis.fetch = async (url, init = {}) => {
  const method = init.method || 'GET', body = init.body ? JSON.parse(init.body) : null;
  calls.push({url, method, body});
  if (url === '/api/projects/p1/sop-tasks' && method === 'GET' && server.overviewHold) await server.overviewHold;
  if (url === '/api/projects/p1/sop-tasks' && method === 'GET' && server.overviewOk) return response(server.overview);
  if (url === '/api/projects/p1/sop-tasks' && method === 'GET' && server.overviewFail) return response({code: 'upstream'}, 502);
  if (url === '/api/projects/p1/sop-tasks' && method === 'GET') return overviewStatus === 200 ? response(server.overview) : response({code: 'sop_import_forbidden'}, overviewStatus);
  if (url.split('?')[0].endsWith('/sop-assignees')) return response({people:[{id:'pm',name:'王經理',case_roles:['pm']},{id:'member',name:'林組員',case_roles:['collaborator']}]});
  if (url === '/api/sop-templates') return response({templates: [{...examples.preview.template, name: 'Plumb 案件 SOP', is_default: true}]});
  if (url.endsWith('/sop-import/preview')) return response(previewFixture(body));
  if (url.endsWith('/sop-import/apply')) {server.apply.push(body); return server.applyReply ? server.applyReply(body) : response({...examples.apply, request_id: body.request_id})}
  if (url.includes('/sop-import/runs/')) {server.run.push(url); if (server.hold) await server.hold; return server.runReply ? server.runReply(url) : response({...examples.apply, request_id: decodeURIComponent(url.split('/').at(-1))})}
  if (url.endsWith('/sop-tasks/close-node')) {server.close = [...(server.close || []), body]; return response({closed: 1, left_open: {shared: 0, unresolved: 0}, checklist_revision: 5})}
  if (url.endsWith('/cleanup-test')) {server.cleanup = [...(server.cleanup || []), body]; if(server.cleanupReply)return server.cleanupReply(body);server.overview = overview([]);return response({task_id:'t1',removed:true,replayed:false,checklist_revision:10})}
  if (url === '/api/projects/p1/sop-tasks' && method === 'POST') {server.created=body;return response({task_id:'created',checklist_revision:10})}
  if (url.endsWith('/transition')) {server.transitions = [...(server.transitions || []), body]; if (server.hold) await server.hold; return server.transitionReply ? server.transitionReply(body) : response({task_id: 't1', revision: body.expected_revision + 1, checklist_revision: 9, state: 'in_progress', applicability: 'applicable', task: task('t1', {state: 'in_progress', revision: body.expected_revision + 1, allowed_actions: ['block', 'complete']})})}
  if (method === 'PATCH') {server.patch.push(body); return server.patchReply ? server.patchReply(body) : response({task_id: 't1', revision: body.expected_revision + 1, checklist_revision: 9, state: 'pending', applicability: 'applicable'})}
  return response({code: 'not_found'}, 404);
 };
 root = createRoot(document.getElementById('root'));
 await act(async () => {render(); await tick()});
}
afterEach(async () => {if (root) {await act(async () => root.unmount()); root = null} document.body.innerHTML = '<div id="root"></div>'});
const button = t => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === t);
const dialog = () => document.querySelector('[role=dialog]');
const click = async b => {assert.ok(b, 'control exists'); assert.equal(b.disabled, false, `${b.textContent} enabled`); b.focus(); await act(async () => {b.click(); await tick()})};
const type = async (el, v) => act(async () => {Object.getOwnPropertyDescriptor(el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set.call(el, v); el.dispatchEvent(new Event('input', {bubbles: true})); await tick()});

test('parsers accept the backend example payloads and reject foreign node keys', () => {
 const o = ui.parseOverview(examples.sop_tasks);
 assert.deepEqual([o.startNode, o.checklistRevision, o.tasks[0].title, o.tasks[0].dueDate, o.tasks[0].manual, o.tasks[0].nodes[0].node_key], ['sales', 1, '業主提出報價需求', null, false, 'sales']);
 assert.deepEqual(o.caseCounts, {done: 0, total: 1, unresolved: 0, not_applicable: 0, archived: 0});
 assert.deepEqual(ui.parsePreview(examples.preview).counts, {new_tasks: 1, existing_tasks: 0, added_links: 1});
 assert.equal(ui.parsePreview({...examples.preview, expires_at: 1792496832.94495}).expiresAt, 1792496832.94495);
 const receipt = ui.parseReceipt(examples.apply);
 assert.deepEqual([receipt.created.length, receipt.existing.length, receipt.links, receipt.unresolved.dates], [1, 0, 1, 1]);
 const foreign = clone(examples.sop_tasks); foreign.tasks[0].nodes[0].node_key = 'N01';
 assert.throws(() => ui.parseOverview(foreign), e => e.code === 'malformed');
 assert.throws(() => ui.parseOverview({...examples.sop_tasks, task_source: 'lark'}), e => e.code === 'malformed');
});

test('case order is canonical node then source order, manual after template; node scope uses that node order', () => {
 const tasks = ui.parseOverview(overview([
  task('manual', {nodes: [link('sales', 10000)], origin: {template_family_id: 'manual'}}),
  task('pm-2', {nodes: [link('pm', 2)]}),
  task('sales-5', {nodes: [link('sales', 5)]}),
  task('shared', {nodes: [link('control', 40), link('report', 41)]}),
  task('sales-3', {nodes: [link('sales', 3)]}),
 ])).tasks;
 assert.deepEqual(ui.orderTasks(tasks).map(t => t.id), ['sales-3', 'sales-5', 'pm-2', 'shared', 'manual']);
 assert.deepEqual(ui.visibleTasks(tasks, {scope: 'report', filters: [], history: false}, 'pm').map(t => t.id), ['shared']);
});

test('counts follow PRD 8.3 and an empty applicable set is not 100 percent', () => {
 const tasks = ui.parseOverview(overview([
  task('a', {state: 'done'}), task('b', {state: 'done'}), task('c', {state: 'blocked'}), task('d'),
  task('e', {applicability: 'unresolved'}), task('f', {applicability: 'not_applicable'}), task('g', {state: 'archived'}),
 ])).tasks;
 const counts = ui.countTasks(tasks);
 assert.deepEqual(counts, {done: 2, total: 4, unresolved: 1, not_applicable: 1, archived: 1});
 assert.equal(ui.progressLabel(counts), '2/4');
 assert.equal(ui.checklistComplete(counts), false);
 assert.equal(ui.progressLabel(ui.countTasks([])), '無適用任務');
 assert.equal(ui.checklistComplete(ui.countTasks(tasks.filter(t => t.state === 'done'))), true);
});

test('filters select mine, unassigned, overdue, pending and archived history', () => {
 const tasks = ui.parseOverview(overview([
  task('mine', {participants: {executor: 'pm'}}), task('theirs', {participants: {executor: 'member'}, overdue: true}),
  task('open', {applicability: 'unresolved'}), task('old', {state: 'archived'}),
 ])).tasks;
 const ids = (filters, history = false) => ui.visibleTasks(tasks, {filters, history}, 'pm').map(t => t.id).sort();
 assert.deepEqual(ids(['mine']), ['mine']);
 assert.deepEqual(ids(['unassigned']), ['open']);
 assert.deepEqual(ids(['overdue']), ['theirs']);
 assert.deepEqual(ids(['pending']), ['open']);
 assert.deepEqual(ids([], true), ['old']);
});

test('import grouping, decision blockers and the preview body', () => {
 const preview = ui.parsePreview(previewFixture({}));
 const {groups, references} = ui.groupOutcomes(preview);
 assert.deepEqual(groups.map(g => [g.label, g.rows.map(r => r.title)]), [['新增', ['業主提出報價需求']], ['待確認', ['下包提出報價', '確認單修正']], ['已排除', ['建立報價編號']], ['需範本審核', ['範本待審項目']]]);
 assert.equal(references, 1);
 const defaults = new Set(preview.rowKeys), selected = new Set([...defaults, 'meegle-v137:A:7']);
 assert.deepEqual(ui.selectionBlockers(preview, selected, {}, defaults), {'meegle-v137:A:7': '需填寫適用原因'});
 assert.deepEqual(ui.selectionBlockers(preview, new Set(['meegle-v137:A:42']), {}, defaults), {'meegle-v137:A:42': '此列不可匯入'});
 const existing = ui.parsePreview({...previewFixture({}), outcomes: [outcome('meegle-v137:A:7', '下包提出報價', {selected: false, outcome: 'excluded', applicability: 'applicable', existing_task_id: 'old', existing_state: 'pending', links_to_add: []})]});
 assert.deepEqual(ui.selectionBlockers(existing, new Set(['meegle-v137:A:7']), {}, new Set()), {'meegle-v137:A:7': '需填寫適用原因'});
 assert.deepEqual(ui.previewBody(preview, selected, {'meegle-v137:A:7': ' 有下包 '}, defaults).applicability_decisions, {'meegle-v137:A:7': {value: 'applicable', reason: '有下包'}});
 assert.deepEqual(ui.defaultImportNodes('sales'), NODES);
 assert.deepEqual(ui.defaultImportNodes('field'), NODES.slice(3));
 assert.deepEqual(ui.defaultImportNodes('field', 'pm'), ['pm']);
});

test('task actions use the per-task server actions', () => {
 const [imported] = ui.parseOverview(overview([task('t', {allowed_actions:['block','edit']})])).tasks;
 assert.deepEqual(ui.taskActions(imported).map(a=>a.action), ['block']);
 assert.deepEqual(ui.taskActions({...imported, allowedActions:[]}), []);
});

test('the section lists the node tasks with executor, state, due and badges', async () => {
 await mount({tasks: [task('t1'), task('shared', {title: '共用檢核', participants: {executor: 'member'}, nodes: [link('sales', 9), link('pm', 9)], applicability: 'unresolved'})]});
 const section = document.querySelector('#sop-tasks');
 assert.equal(section.querySelector('h3').firstChild.textContent, '任務');
 assert.deepEqual([...section.querySelectorAll('.pf-task-open strong')].map(s => s.textContent), ['業主提出報價需求', '共用檢核']);
 assert.equal(section.querySelector('[data-sop-task=t1] .pf-task-open>span').textContent, '未指派 · 待處理 · 期限待確認未啟用');
 assert.equal(section.querySelector('[data-sop-task=shared] .pf-task-open>span').textContent, '林組員 · 待處理 · 期限待確認未啟用共用條件');
 assert.equal(section.querySelector('.sop-progress').textContent, '0/1');
 await click(button('全案'));
 assert.equal(section.querySelector('[data-sop-task=shared] small').textContent, '報價、PM 派工');
 await click(button('未指派'));
 assert.match(document.querySelector('.sop-counts').textContent, /^篩選後 1 項/);
});

test('an empty case shows plain labels and a denied read shows the denial', async () => {
 await mount({tasks: []});
 assert.equal(document.querySelector('.sop-progress').textContent, '無適用任務');
 assert.equal(document.querySelector('#sop-tasks .pf-empty'), null);assert.ok(button('新增任務'));
 await act(async () => root.unmount()); root = null;
 await mount({overviewStatus: 403});
 assert.match(document.querySelector('#sop-tasks').textContent, /sop_task_read.*sop_task_read_source/);
});

test('quote-stage import starts from 報價, needs a reason for subcontract rows, and recovers a lost apply by request id', async () => {
 await mount({tasks: []});
 await click(button('匯入預設任務'));
 assert.match(dialog().textContent, /從 報價 開始/);
 assert.equal(dialog().querySelector('input[type=radio]').checked, true);
 assert.equal(dialog().querySelector('.sop-nodes'), null);
 await click(button('下一步'));
 assert.deepEqual(calls.filter(r => r.url.endsWith('/preview')).map(r => r.body), [{template_version_id: examples.preview.template.version_id, node_keys: ['sales']}]);
 assert.deepEqual([...dialog().querySelectorAll('.sop-group legend')].map(l => l.textContent), ['新增 1', '待確認 2', '已排除 1', '需範本審核 1']);
 const sub = dialog().querySelector('[data-row="meegle-v137:A:7"] input[type=checkbox]');
 await act(async () => {sub.click(); await tick()});
 assert.equal(dialog().querySelector('[data-row="meegle-v137:A:7"] .sop-blocker').textContent, '需填寫適用原因');
 assert.equal(button('下一步').disabled, true);
 await type(dialog().querySelector('[data-row="meegle-v137:A:7"] .sop-reason input'), '本案有下包');
 await click(button('下一步'));
 assert.deepEqual(calls.filter(r => r.url.endsWith('/preview')).at(-1).body.applicability_decisions, {'meegle-v137:A:7': {value: 'applicable', reason: '本案有下包'}});
 assert.match(dialog().textContent, /新增任務3/);
 let release; server.hold = new Promise(r => release = r);
 server.applyReply = () => {throw new TypeError('network down')};
 await click(button('確認匯入'));
 assert.equal(dialog().querySelector('[role=status]').textContent, '正在確認匯入結果');
 await act(async () => {release(); await tick()});
 assert.equal(server.apply.length, 1);
 assert.equal(server.run[0], `/api/projects/p1/sop-import/runs/${server.apply[0].request_id}`);
 assert.deepEqual([...dialog().querySelectorAll('.ds-row')].map(r => r.textContent), ['已建立1', '已存在0', '新增節點連結1', '期限待確認1', '人員未指派1']);
 const before = calls.filter(r => r.url.endsWith('/sop-tasks')).length;
 assert.ok(before >= 2, 'overview refreshed after apply');
 await click(button('開啟匯入任務'));
 assert.equal(dialog(), null);
 assert.equal(c.route.tab,'flow');
});

test('an apply the server never recorded is retried with the same preview and request ids', async () => {
 await mount({tasks: []});
 await click(button('匯入預設任務')); await click(button('下一步')); await click(button('下一步'));
 server.applyReply = () => response({code: 'import_unavailable'}, 503);
 server.runReply = () => response({code: 'run_not_found'}, 404);
 await click(button('確認匯入'));
 assert.match(dialog().textContent, /匯入尚未完成，可重試/);
 server.applyReply = null;
 await click(button('重試匯入'));
 assert.deepEqual(server.apply.map(b => b.request_id), [server.apply[0].request_id, server.apply[0].request_id]);
 assert.deepEqual(server.apply.map(b => b.preview_id), ['preview-default', 'preview-default']);
 assert.match(dialog().textContent, /已建立1/);
});

test('closing the sheet never imports', async () => {
 await mount({tasks: []});
 await click(button('匯入預設任務')); await click(button('下一步')); await click(button('下一步'));
 await act(async () => {document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await tick()});
 assert.equal(dialog(), null);
 assert.equal(server.apply.length, 0);
});

test('a deep link opens the SOP drawer, Escape clears the discriminator and returns focus', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 assert.equal(dialog().getAttribute('aria-label'), 'SOP 任務 · 業主提出報價需求');
 assert.doesNotMatch(dialog().textContent, /Lark/);
 assert.equal(dialog().querySelector('details.sop-source').open, false);
 await act(async () => {document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await tick()});
 assert.deepEqual([c.route.task, c.route.task_source], [undefined, undefined]);
 const row = document.querySelector('[data-sop-task=t1] button');
 await click(row);
 assert.deepEqual([c.route.task, c.route.task_source], ['t1', 'sop_local']);
 await act(async () => {document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await tick()});
 assert.equal(document.activeElement, document.querySelector('[data-sop-task=t1] button'));
});

test('a task row leads with its state marker and ends with the bulk checkbox; the drawer footer ends with the primary action', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 const row = document.querySelector('[data-sop-task=t1] .sop-task-select');
 assert.deepEqual([...row.children].map(e => e.className || e.type), ['sop-state', 'pf-task-open', 'assignee-picker ds-picker', 'checkbox']);
 assert.equal(row.firstElementChild.dataset.state, 'pending');
 assert.equal(dialog().dataset.kind, 'sop');
 assert.deepEqual([...dialog().querySelectorAll('.task-drawer-trail>span')].map(s => s.textContent), ['SOP 任務', '報價']);
 const actions = [...dialog().querySelectorAll('.task-drawer-footer [aria-label=狀態操作] button')].map(b => b.textContent);
 assert.equal(actions.at(-1), '開始');
});

test('Start shows a labelled pending state, applies the receipt before any refresh, and sends one write', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 let release; server.hold = new Promise(r => {release = r});
 const start = [...dialog().querySelectorAll('.task-drawer-footer button')].find(b => b.textContent === '開始');
 await act(async () => {start.click(); start.click(); await tick()});
 const footer = dialog().querySelector('.task-drawer-footer');
 assert.match(footer.textContent, /開始中…/);
 assert.ok([...footer.querySelectorAll('button')].every(b => b.disabled), 'every action is disabled while the write is pending');
 server.overview = overview([task('t1', {state: 'pending'})]);
 await act(async () => {release(); await tick()});
 assert.equal(server.transitions.length, 1, 'no duplicate write');
 assert.match(dialog().querySelector('.sop-badges').textContent, /進行中/);
 assert.equal([...dialog().querySelectorAll('.task-drawer-footer button')].some(b => b.textContent === '開始'), false);
});

test('a failed Start keeps the task as it was and shows the error beside the actions', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 server.transitionReply = () => response({code: 'invalid_transition', detail: '目前狀態不可執行'}, 409);
 await click([...dialog().querySelectorAll('.task-drawer-footer button')].find(b => b.textContent === '開始'));
 assert.match(dialog().querySelector('.task-drawer-footer [role=alert]').textContent, /目前狀態不可執行/);
 assert.match(dialog().querySelector('.sop-badges').textContent, /待處理/);
 assert.ok([...dialog().querySelectorAll('.task-drawer-footer button')].some(b => b.textContent === '開始' && !b.disabled), 'Start can be retried');
});

const footerButtons = () => [...dialog().querySelectorAll('.task-drawer-footer button')];
const startButton = () => footerButtons().find(b => b.textContent === '開始');

test('after a timeout on Start, actions stay blocked until the read-back answers, then follow the fresh task', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 let release; server.overviewHold = new Promise(r => {release = r});
 server.transitionReply = () => response({code: 'upstream'}, 504);
 await click(startButton());
 assert.match(dialog().querySelector('.task-drawer-footer').textContent, /正在確認剛才的操作結果/);
 assert.ok(footerButtons().every(b => b.disabled), 'every action is disabled while the outcome is unknown');
 await act(async () => {startButton().click(); await tick()});
 assert.equal(server.transitions.length, 1, 'no second write while verifying');
 server.overview = overview([task('t1', {state: 'in_progress', revision: 4, allowed_actions: ['block', 'complete']})]);
 await act(async () => {release(); await tick(); await tick()});
 assert.match(dialog().querySelector('.sop-badges').textContent, /進行中/, 'the read-back result is shown');
 assert.equal(startButton(), undefined);
 assert.equal(server.transitions.length, 1);
});

test('a 5xx on Start whose read-back also fails offers a read-only retry and never a second write', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 server.transitionReply = () => response({code: 'boom'}, 500);
 server.overviewFail = true;
 await click(startButton());
 const footer = () => dialog().querySelector('.task-drawer-footer');
 assert.match(footer().textContent, /無法確認剛才的操作是否已完成/);
 assert.ok(footerButtons().filter(b => b.textContent !== '重新讀取').every(b => b.disabled), 'mutating actions stay disabled');
 const getsBefore = calls.filter(x => x.method === 'GET' && x.url === '/api/projects/p1/sop-tasks').length;
 await act(async () => {startButton().click(); await tick()});
 assert.equal(server.transitions.length, 1);
 await click(footerButtons().find(b => b.textContent === '重新讀取'));
 assert.equal(server.transitions.length, 1, 'retry is a read, not a write');
 assert.ok(calls.filter(x => x.method === 'GET' && x.url === '/api/projects/p1/sop-tasks').length > getsBefore);
 assert.match(footer().textContent, /無法確認剛才的操作是否已完成/, 'still blocked while reads keep failing');
 server.overviewFail = false;
 await click(footerButtons().find(b => b.textContent === '重新讀取'));
 assert.doesNotMatch(footer().textContent, /無法確認/);
 assert.ok(startButton() && !startButton().disabled, 'unblocked once a read-back succeeds');
 assert.equal(server.transitions.length, 1);
});

test('an ordinary 409 conflict is not treated as unknown: the error shows and Start can be retried at once', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 server.transitionReply = () => response({code: 'task_revision_conflict', detail: '任務已更新'}, 409);
 await click(startButton());
 assert.doesNotMatch(dialog().querySelector('.task-drawer-footer').textContent, /正在確認|無法確認/);
 assert.ok(startButton() && !startButton().disabled);
});

test('retrying a failed overview read replaces the stale error at once, keeps the task, blocks duplicates and never writes', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}, overviewStatus: 502});
 assert.match(document.body.textContent, /SOP 任務讀取失敗/);
 const retry = button('重試 SOP 任務');
 assert.ok(retry, 'the failed read offers a retry');
 let release; server.overviewHold = new Promise(r => {release = r}); server.overviewOk = true;
 const readsBefore = calls.filter(x => x.method === 'GET' && x.url === '/api/projects/p1/sop-tasks').length;
 await act(async () => {retry.click(); await tick()});
 assert.doesNotMatch(document.body.textContent, /SOP 任務讀取失敗/, 'the stale error is gone the moment retry is clicked');
 const status = document.querySelector('#sop-tasks [role=status][aria-busy=true]');
 assert.match(status.textContent, /正在重新讀取 SOP 任務/);
 assert.match(status.textContent, /保留目前選取的任務/);
 assert.equal(button('重新讀取中…').disabled, true, 'a second retry is not possible');
 assert.equal(c.route.task, 't1', 'the selected task stays in the route');
 await act(async () => {button('重新讀取中…').click(); await tick()});
 assert.equal(calls.filter(x => x.method === 'GET' && x.url === '/api/projects/p1/sop-tasks').length, readsBefore + 1, 'one read in flight');
 await act(async () => {release(); await tick(); await tick()});
 assert.equal(dialog().getAttribute('aria-label'), 'SOP 任務 · 業主提出報價需求', 'the exact task opens');
 assert.deepEqual(calls.filter(x => x.method !== 'GET'), [], 'retry is read-only');
});

test('a retry that fails again shows the new failure with the retry available', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}, overviewStatus: 502});
 await click(button('重試 SOP 任務'));
 assert.match(document.body.textContent, /SOP 任務讀取失敗/);
 assert.ok(button('重試 SOP 任務') && !button('重試 SOP 任務').disabled);
});

test('a revision conflict reloads the task and keeps the draft for the next save', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 const input = dialog().querySelector('[aria-label="任務名稱"]');
 await type(input, '業主需求確認');
 server.patchReply = () => {server.overview = overview([task('t1', {revision: 2})]); return response({code: 'task_revision_conflict'}, 409)};
 await click(button('儲存任務'));
 assert.equal(dialog().querySelector('[role=alert]').textContent, '任務已被更新，已重新載入');
 assert.equal(dialog().querySelector('[aria-label="任務名稱"]').value, '業主需求確認');
 server.patchReply = null;
 await click(button('儲存任務'));
 assert.deepEqual(server.patch.map(b => [b.expected_revision, b.title]), [[1, '業主需求確認'], [2, '業主需求確認']]);
});

test('participant choices come only from eligible case people', async () => {
 await mount({route: {task: 't1', task_source: 'sop_local'}});
 const executor = dialog().querySelector('button[aria-label="task: 業主提出報價需求"]');
 await click(executor);
 assert.deepEqual([...dialog().querySelectorAll('[role=option]')].map(o => o.textContent), ['未指派', '王經理', '林組員']);
});

test('suggestion controls remain inside the task block without an internal separator', async()=>{
 const style=document.createElement('style');style.textContent=await fs.readFile(new URL('./src/SopTasks.css',import.meta.url),'utf8');document.head.append(style);
 try{const t=clone(examples.sop_tasks_with_suggestions.tasks.find(t=>t.suggestion));await mount({tasks:[t]});const suggestion=document.querySelector('.sop-suggestion');assert.ok(suggestion.closest('[data-sop-task]'));assert.equal(getComputedStyle(suggestion).borderTopWidth,'0px');assert.equal(getComputedStyle(suggestion).paddingLeft,'32px');assert.equal(getComputedStyle(document.querySelector('.sop-task-select input')).marginLeft,'0px')}finally{style.remove()}
});

test('link confirmation shows completion actor, time, state and evidence before importing',async()=>{
 await mount();const previous=globalThis.fetch;
 globalThis.fetch=async(url,init={})=>{if(url.endsWith('/sop-import/preview')){const p=previewFixture(JSON.parse(init.body));p.outcomes[1]={...p.outcomes[1],outcome:'link_addition',existing_state:'done',completion:{state:'done',actor_id:'pm',actor_name:'王經理',at:1792490000,evidence_basis:{rule_id:'reviewed',facts_hash:'abc123'},evidence_refs:['evidence-123']}};return response(p)}return previous(url,init)};
 await click(button('匯入預設任務'));await click(button('下一步'));await click(button('下一步'));
 for(const value of ['完成人員','王經理','完成時間','已完成','reviewed','abc123','evidence-123'])assert.ok(dialog().textContent.includes(value),value);
 assert.equal(server.apply.length,0);
});


test('sync badge and Lark row link follow the task receipt', async () => {
 const sync = {state: 'Lark 已變更', synced_at: 1000, record_id: 'recKnown', base_id: 'baseKnown', table_id: 'tblKnown'};
 await mount({tasks: [task('t1', {lark_sync: sync})], route: {task: 't1', task_source: 'sop_local'}});
 assert.match(document.querySelector('[data-sop-task=t1]').textContent, /Lark 已變更/);
 const link = [...document.querySelectorAll('a')].find(a => a.textContent === '開啟 Lark 列');
 assert.ok(link);
 assert.equal(link.href, 'https://yong-xiang-survey.jp.larksuite.com/base/baseKnown?table=tblKnown&record=recKnown');
});

test('unsynced task has a plain badge without a Lark row link', async () => {
 await mount({tasks: [task('t1', {lark_sync: {state: '同步中', synced_at: null, record_id: null}})], route: {task: 't1', task_source: 'sop_local'}});
 assert.match(document.querySelector('[data-sop-task=t1]').textContent, /同步中/);
 assert.ok(![...document.querySelectorAll('a')].some(a => a.textContent === '開啟 Lark 列'));
 const invalid = overview([task('t1', {lark_sync: {state: 'unknown'}})]);
 assert.throws(() => ui.parseOverview(invalid), e => e.code === 'malformed');
});


test('disabled projection hides stale receipt links', async () => {
 await mount({tasks: [task('t1', {lark_sync: {state: '未啟用', record_id: 'recOld', base_id: 'baseOld', table_id: 'tblOld'}})], route: {task: 't1', task_source: 'sop_local'}});
 assert.ok(![...document.querySelectorAll('a')].some(a => a.textContent === '開啟 Lark 列'));
});


test('background projection completion refreshes badge and receipt link', async () => {
 const originalSet = globalThis.setInterval, originalClear = globalThis.clearInterval;
 const timers = new Map(); let next = 0;
 globalThis.setInterval = (fn, delay) => {assert.equal(delay, 10000); timers.set(++next, fn); return next};
 globalThis.clearInterval = id => timers.delete(id);
 try {
  await mount({tasks: [task('t1', {lark_sync: {state: '同步中'}})], route: {task: 't1', task_source: 'sop_local'}});
  assert.equal(timers.size, 1);
  server.overview = overview([task('t1', {lark_sync: {state: '已同步', record_id: 'recNew', base_id: 'baseNew', table_id: 'tblNew'}})]);
  await act(async () => {await [...timers.values()][0](); await tick()});
  assert.match(document.querySelector('[data-sop-task=t1]').textContent, /已同步/);
  assert.ok([...document.querySelectorAll('a')].some(a => a.href.includes('record=recNew')));
  assert.equal(timers.size, 0);
  assert.ok(button('重新整理'));
  await click(button('重新整理'));
 } finally {globalThis.setInterval = originalSet; globalThis.clearInterval = originalClear}
});

test('projection polling stops after five minutes and on session change or unmount', async () => {
 const originalSet = globalThis.setInterval, originalClear = globalThis.clearInterval;
 const timers = new Map(); let next = 0;
 globalThis.setInterval = (fn, delay) => {assert.equal(delay, 10000); timers.set(++next, fn); return next};
 globalThis.clearInterval = id => timers.delete(id);
 try {
  await mount({tasks: [task('t1', {lark_sync: {state: '同步中'}})]});
  const poll = [...timers.values()][0]; assert.equal(typeof poll, 'function');
  for (let i = 0; i < 31; i++) await act(async () => {await poll(); await tick()});
  assert.equal(calls.filter(c => c.url.endsWith('/sop-tasks')).length, 31);
  assert.equal(timers.size, 0);
  await act(async () => root.unmount()); root = null;
  assert.equal(timers.size, 0);
  document.body.innerHTML = '<div id="root"></div>';
  await mount({tasks: [task('t1', {lark_sync: {state: '同步中'}})]});
  const stale = [...timers.values()][0], before = calls.length;
  await act(async()=>ui.invalidateSessionEpoch());
  await act(async () => {await stale(); await tick()});
  assert.equal(calls.length, before);
  await act(async () => root.unmount()); root = null;
  assert.equal(timers.size, 0);
 } finally {globalThis.setInterval = originalSet; globalThis.clearInterval = originalClear}
});


test('slow overview requests do not extend the projection polling window', async () => {
 const originalSet = globalThis.setInterval, originalClear = globalThis.clearInterval;
 const timers = new Map(); let next = 0, release;
 globalThis.setInterval = fn => {timers.set(++next, fn); return next};
 globalThis.clearInterval = id => timers.delete(id);
 try {
  await mount({tasks: [task('t1', {lark_sync: {state: '同步中'}})]});
  const originalFetch = globalThis.fetch;
  const held = new Promise(resolve => {release = resolve});
  globalThis.fetch = async (...args) => {await held; return originalFetch(...args)};
  const poll = [...timers.values()][0]; let pending;
  await act(async () => {pending = poll(); await tick()});
  for (let i = 1; i < 31; i++) await poll();
  assert.equal(timers.size, 0);
  await act(async () => {release(); await pending; await tick()});
 } finally {release?.(); globalThis.setInterval = originalSet; globalThis.clearInterval = originalClear}
});

test('a manager assigns the executor from the list row without opening the task', async () => {
 await mount({tasks: [task('t1', {allowed_actions: ['start', 'edit']})]});
 const picker = document.querySelector('button[aria-label="task: 業主提出報價需求"]');
 assert.ok(picker, 'row has an inline assignee picker');
 await click(picker);
 assert.deepEqual([...document.querySelectorAll('[role=option]')].map(o => o.textContent), ['未指派', '王經理', '林組員']);
 await act(async()=>{[...document.querySelectorAll('[role=option]')].find(o=>o.textContent==='林組員').click();await tick()});
 assert.deepEqual(server.patch, [{expected_revision: 1, participants: {executor: 'member'}}]);
 assert.equal(document.querySelector('[role=dialog]'), null);
});

test('a task a person cannot edit has no inline assignee picker', async () => {
 await mount({tasks: [task('t1', {allowed_actions: ['start']})]});
 assert.equal(document.querySelector('.assignee-picker'), null);
});

test('a node the data proves done offers one manager action that closes its open tasks', async () => {
 const proven = {sales: {rule: 'c_code', reason: '工編以 C 開頭，業務階段已完成'}};
 await mount({tasks: [task('t1'), task('t2', {state: 'done'})], extra: {node_done: proven, allowed_actions: {...examples.sop_tasks.allowed_actions, manage: true}}});
 assert.match(document.querySelector('.sop-node-done').textContent, /節點已完成 · 工編以 C 開頭，業務階段已完成/);
 await click(button('依節點完成，全部標為已完成（1）'));
 assert.deepEqual(server.close, [{node_key: 'sales'}]);
});

test('without manager authority or open tasks there is no close action', async () => {
 const proven = {sales: {rule: 'c_code', reason: '工編以 C 開頭，業務階段已完成'}};
 await mount({tasks: [task('t1')], extra: {node_done: proven, allowed_actions: {...examples.sop_tasks.allowed_actions, manage: false}}});
 assert.ok(document.querySelector('.sop-node-done'));
 assert.equal(button('依節點完成，全部標為已完成（1）'), undefined);
});

test('an unenrolled node hides creation and import even when case management is allowed',async()=>{
 await mount({tasks:[],extra:{local_nodes:[{key:'sales',id:'sales-id',revision:0,status:'pending',owner_id:null,completed_at:null,reason:null,disabled_reason:'此節點尚未納入 SOP 管理',complete_disabled_reason:'此節點尚未納入 SOP 管理',can:{assign:false,complete:false,reject:false,create_task:false}}]}});
 assert.equal(button('新增任務'),undefined);
 assert.equal(button('匯入預設任務'),undefined);
});


for (const role of ['manager','admin','pm','member']) test(`test task toggle is limited to workspace managers, role ${role}`, async()=>{
 await mount({role,extra:{allowed_actions:{import:true,manage:true,work:true}}});
 await click(button('新增任務'));
 const toggle=document.querySelector('[role=switch]');
 assert.equal(!!toggle,['manager','admin'].includes(role));
 if(toggle)await click(toggle);
 await type(document.querySelector('input[required]'),'Acceptance task');
 await click(button('建立任務'));
 assert.equal(server.created.is_test,['manager','admin'].includes(role)?true:undefined);
});

test('test badge appears in the list and drawer, cleanup requires a reason and preserves filters and focus',async()=>{
 await mount({role:'manager',tasks:[task('t1',{local:{is_test:true},allowed_actions:['edit']})]});
 await click(button('未指派'));
 assert.equal(button('未指派').getAttribute('aria-pressed'),'true');
 assert.match(document.querySelector('[data-sop-task=t1]').textContent,/測試/);
 await click(document.querySelector('.pf-task-open'));
 assert.match(dialog().querySelector('.sop-badges').textContent,/測試/);
 await click(button('清除測試任務'));
 assert.equal(button('確認清除').disabled,true);
 await type(document.querySelector('[aria-label="清除測試任務"] textarea'),'   ');
 assert.equal(button('確認清除').disabled,true);
 await type(document.querySelector('[aria-label="清除測試任務"] textarea'),' Browser acceptance complete ');
 await click(button('確認清除'));
 assert.deepEqual(server.cleanup,[{expected_revision:1,reason:'Browser acceptance complete'}]);
 assert.equal(dialog(),null);
 assert.equal(document.querySelector('[data-sop-task=t1]'),null);
 assert.equal(c.route.task,undefined);
 assert.equal(button('未指派').getAttribute('aria-pressed'),'true');
 assert.equal(document.activeElement.id,'sop-tasks');
});

for(const role of ['pm','member'])test(`non-manager ${role} never sees cleanup even with case management`,async()=>{
 await mount({role,tasks:[task('t1',{local:{is_test:true}})]});
 await click(document.querySelector('.pf-task-open'));
 assert.equal(button('清除測試任務'),undefined);
});

test('manager cannot clean an ordinary task and cancelling cleanup sends no request',async()=>{
 await mount({role:'manager',tasks:[task('t1')]});
 await click(document.querySelector('.pf-task-open'));
 assert.equal(button('清除測試任務'),undefined);
 await act(async()=>{server.overview=overview([task('t1',{local:{is_test:true}})]);c.go({...c.route,task:undefined});await tick()});
 await click(button('重新整理'));
 await click(document.querySelector('.pf-task-open'));
 await click(button('清除測試任務'));
 await click([...document.querySelector('[aria-label="清除測試任務"]').querySelectorAll('button')].find(b=>b.textContent==='取消'));
 assert.equal(server.cleanup,undefined);
 assert.equal(document.querySelectorAll('[role=dialog]').length,1);
});

for(const [status,code,copy] of [[503,'cleanup_migration_required','稽核遷移'],[409,'test_task_projection_exists','Lark 投影紀錄'],[409,'test_task_required','建立時標記'],[409,'task_reopen_required','重新開啟'],[409,'task_revision_conflict','任務已被更新']])test(`cleanup ${code} keeps the task and reason and shows its distinct recovery message`,async()=>{
 await mount({role:'manager',tasks:[task('t1',{local:{is_test:true}})]});
 server.cleanupReply=()=>response({code},status);
 await click(document.querySelector('.pf-task-open'));
 await click(button('清除測試任務'));
 await type(document.querySelector('[aria-label="清除測試任務"] textarea'),'QA reason');
 await click(button('確認清除'));
 const panel=document.querySelector('[aria-label="清除測試任務"]');
 assert.match(panel.querySelector('[role=alert]').textContent,new RegExp(copy));
 assert.equal(panel.querySelector('textarea').value,'QA reason');
 assert.ok(document.querySelector('[data-sop-task=t1]'));
});
