import assert from 'node:assert/strict';
import {test, afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture} from './fixtures/node-assignments.mjs';

const dom = new JSDOM('<div id="root"></div>', {url: 'http://localhost/'});
for (const k of ['window', 'document', 'location', 'history', 'sessionStorage', 'localStorage', 'Event', 'KeyboardEvent', 'Element', 'HTMLElement', 'navigator']) Object.defineProperty(globalThis, k, {value: dom.window[k], configurable: true});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.getComputedStyle = dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView = function () {};
HTMLElement.prototype.getClientRects = function () {return [{width: 40, height: 40}]};
const React = await import('react');
const {act} = React;
const {createRoot} = await import('react-dom/client');
const bundle = await build({stdin: {contents: "export * from './src/nodeAssignmentApi';export * from './src/nodeEvidence';export {NodeWorkItems} from './src/NodeWorkItems';export {invalidateSessionEpoch} from './src/api';", resolveDir: new URL('.', import.meta.url).pathname}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
const path = new URL('./.node-evidence-test.mjs', import.meta.url);
await fs.writeFile(path, bundle.outputFiles[0].text);
let ui;
try {ui = await import(path.href)} finally {await fs.unlink(path)}

const evidence = (patch = {}) => ({planned_qty: '123.4500', lines: 2, items: 5, work_orders: 0, latest_date: null, actual_known: false, actual_value: null,
  actual_source: null, reason: '尚無日報連結到此案件', drives_status: false, progress: null, items_total: 0, items_truncated: false, work_items: [], ...patch});
const workItem = (patch = {}) => ({code: 'C1-1', name: '導線測量', planned_qty: '50', planned_points: '100', remaining_points: '40', status: 'partial', link_basis: 'native', ...patch});
const PROGRESS = {percent: '30', earned_points: '60', planned_points: '200', items_done: 0, items_total: 2, known_items: 2, unknown_items: 0};
const WITH_ITEMS = {progress: PROGRESS, items_total: 2, work_items: [workItem(), workItem({code: 'C1-2', name: '水準測量', planned_qty: '5', remaining_points: '100', status: 'no_signal'})],
  work_orders: 0, actual_known: false, drives_status: true, reason: '合約填報工項已有進度（來源剩餘營業額小於對應營業額）'};
const KNOWN = {work_orders: 2, latest_date: '2026-10-12', actual_known: true, actual_value: '5', actual_source: 'v4_daily', reason: '已有 2 筆日報連結到此案件', drives_status: true};
function listWith(patches) {
  const {list} = assignmentFixture();
  for (const n of list.nodes) {
    const production = ['field', 'control', 'mapping', 'report'].includes(n.key);
    n.evidence = production ? evidence() : null;
    n.can_submit_hint = false;
    n.tasks = {done: 0, total: 0}; n.progress = 0; n.deadline = null; n.next_due = null;
    Object.assign(n, patches[n.key] || {});
  }
  return list;
}
let root, list;
const reply = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
async function mount(patches = {}) {
  ui.invalidateSessionEpoch(); list = listWith(patches);
  globalThis.fetch = async url => url.endsWith('/start-sop') ? reply({code: 'disabled', message: 'off'}, 404) : reply(list);
  root = createRoot(document.getElementById('root'));
  await act(async () => root.render(React.createElement(ui.NodeWorkItems, {projectId: 'p1', node:list.nodes.find(n=>n.key==='field')})));
}
afterEach(async () => {if (root) {await act(async () => root.unmount()); root = null}});
const click = async element => act(async () => element.dispatchEvent(new window.MouseEvent('click', {bubbles: true})));

const HOSTILE = ['1e9999999999', '1e99999', '-5', 'NaN', 'Infinity', '1'.repeat(101), '1,5', ''];
const UNKNOWN_HEAVY = {progress: {percent: '99.9', earned_points: '1', planned_points: '1', items_done: 1, items_total: 100, known_items: 1, unknown_items: 99}, items_total: 100, drives_status: true, work_items: [workItem({remaining_points: '0', planned_points: '1', status: 'done'})]};

test('the list parser carries evidence and the submit hint, and nulls stay null', async () => {
  globalThis.fetch = async () => reply(listWith({field: {evidence: evidence(KNOWN), can_submit_hint: true}, control: {evidence: evidence({lines: null, items: null, planned_qty: null})}}));
  const parsed = await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true);
  const by = key => parsed.nodes.find(n => n.key === key);
  assert.deepEqual(by('field').evidence, {planned_qty: '123.4500', lines: 2, items: 5, work_orders: 2, latest_date: '2026-10-12', actual_known: true, actual_value: '5', actual_source: 'v4_daily', reason: '已有 2 筆日報連結到此案件', drives_status: true, progress: null, items_total: 0, items_truncated: false, work_items: []});
  assert.equal(by('field').can_submit_hint, true);
  assert.deepEqual([by('control').evidence.planned_qty, by('control').evidence.lines, by('control').evidence.items], [null, null, null]);
  assert.equal(by('sales').evidence, null);
  assert.equal(by('sales').can_submit_hint, false);
});

test('a payload from an older server without evidence still parses', async () => {
  const old = assignmentFixture().list;
  globalThis.fetch = async () => reply(old);
  const parsed = await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true);
  assert.equal(parsed.nodes.every(n => n.evidence === undefined), true);
});

test('malformed evidence is rejected as a whole payload', async () => {
  for (const bad of [{work_orders: -1}, {work_orders: '2'}, {drives_status: 'yes'}, {actual_known: 1}, {reason: null}, {lines: -3}]) {
    globalThis.fetch = async () => reply(listWith({field: {evidence: evidence(bad)}}));
    await assert.rejects(ui.fetchNodeAssignments('p1', new AbortController().signal, () => true), /節點資料格式不正確/);
  }
});

test('evidence line wording', () => {
  assert.deepEqual(ui.evidenceLine(evidence(KNOWN)), {known: true, plan: '計畫 123.45', text: '計畫 123.45 · 日報 2 筆 · 最近 10/12'});
  assert.deepEqual(ui.evidenceLine(evidence()), {known: false, plan: '計畫 123.45', text: '尚無進度資料（日報未連結或尚未開工）'});
  assert.deepEqual(ui.evidenceLine(evidence({planned_qty: null, work_orders: 1})), {known: true, plan: '', text: '日報 1 筆'});
  assert.equal(ui.evidenceLine(evidence({actual_source: 'v3_reports', actual_known: true, actual_value: null})).text, '計畫 123.45 · 週報登記冊已有外業進度');
});

test('an unbounded or non-decimal quantity is neutralized to null and the list still parses', async () => {
  for (const bad of HOSTILE) {
    globalThis.fetch = async () => reply(listWith({field: {evidence: evidence({planned_qty: bad, actual_value: bad})}}));
    const parsed = await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true);
    const e = parsed.nodes.find(n => n.key === 'field').evidence;
    assert.deepEqual([e.planned_qty, e.actual_value], [null, null], bad);
  }
});

test('the quantity formatter never throws', () => {
  for (const bad of HOSTILE) assert.doesNotThrow(() => ui.evidenceLine(evidence({planned_qty: bad})), bad);
  assert.equal(ui.evidenceLine(evidence({planned_qty: '1e9999999999'})).known, false);
});


test('the parser carries the item progress and work items and defaults them for an older server', async () => {
  globalThis.fetch = async () => reply(listWith({field: {evidence: evidence(WITH_ITEMS)}, control: {evidence: {...evidence(), progress: undefined, items_total: undefined, items_truncated: undefined, work_items: undefined}}}));
  const parsed = await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true);
  const field = parsed.nodes.find(n => n.key === 'field').evidence, control = parsed.nodes.find(n => n.key === 'control').evidence;
  assert.deepEqual(field.progress, PROGRESS);
  assert.deepEqual(field.work_items[1], workItem({code: 'C1-2', name: '水準測量', planned_qty: '5', remaining_points: '100', status: 'no_signal'}));
  assert.deepEqual([field.items_total, field.items_truncated], [2, false]);
  assert.deepEqual([control.progress, control.work_items, control.items_total, control.items_truncated], [null, [], 0, false]);
});

test('hostile item numbers and statuses are neutralized without rejecting the payload', async () => {
  const hostile = {progress: {percent: '1e9999999999', earned_points: '-5', planned_points: 'NaN', items_done: 9, items_total: 2},
    items_total: -4, items_truncated: 'yes',
    work_items: [workItem({planned_qty: 'Infinity', planned_points: '1'.repeat(101), remaining_points: '1,5', status: 'weird'}), null, 'x', {code: 7}, workItem({status: 'done'})]};
  globalThis.fetch = async () => reply(listWith({field: {evidence: evidence(hostile)}}));
  const parsed = await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true);
  const e = parsed.nodes.find(n => n.key === 'field').evidence;
  assert.equal(e.progress, null);
  assert.deepEqual([e.items_total, e.items_truncated], [3, false]);
  assert.equal(e.work_items.length, 3);   // a nameless item is kept; only non-objects are dropped
  assert.deepEqual([e.work_items[0].planned_qty, e.work_items[0].planned_points, e.work_items[0].remaining_points, e.work_items[0].status], [null, null, null, 'no_signal']);
  assert.equal(e.work_items[2].status, 'done');
});

test('a percent outside 0..100 drops the percent but keeps the counts', async () => {
  for (const percent of ['100.1', '-1', 'abc']) {
    globalThis.fetch = async () => reply(listWith({field: {evidence: evidence({progress: {...PROGRESS, percent}})}}));
    const e = (await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true)).nodes.find(n => n.key === 'field').evidence;
    assert.deepEqual([e.progress.percent, e.progress.items_done, e.progress.items_total], [null, 0, 2], percent);
  }
});

test('work items are capped at fifty when parsed', async () => {
  globalThis.fetch = async () => reply(listWith({field: {evidence: evidence({items_total: 80, items_truncated: true, work_items: Array.from({length: 80}, (_, i) => workItem({code: `C-${i}`}))})}}));
  const e = (await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true)).nodes.find(n => n.key === 'field').evidence;
  assert.deepEqual([e.work_items.length, e.items_total, e.items_truncated], [50, 80, true]);
});

test('progress wording', () => {
  assert.deepEqual(ui.progressLine(evidence(WITH_ITEMS)), {known: true, percent: 30, text: '完成 30%（已完成 0/2 工項）', counts: '已完成 0/2 工項', partial: false, muted: false, caveat: null, figure: '完成 30%', fill: 30});
  assert.deepEqual(ui.progressLine(evidence({progress: {...PROGRESS, percent: '42.5', items_done: 1}})), {known: true, percent: 42.5, text: '完成 42.5%（已完成 1/2 工項）', counts: '已完成 1/2 工項', partial: false, muted: false, caveat: null, figure: '完成 42.5%', fill: 42.5});
  assert.deepEqual(ui.progressLine(evidence({progress: {...PROGRESS, percent: null, earned_points: null, planned_points: null, items_done: 1}})), {known: true, percent: null, text: '已完成 1/2 工項', counts: '已完成 1/2 工項', partial: false, muted: false, caveat: null, figure: null, fill: null});
  assert.deepEqual(ui.progressLine(evidence()), {known: false, percent: null, text: '尚無進度資料（日報未連結或尚未開工）', counts: '', partial: false, muted: false, caveat: null, figure: null, fill: null});
  assert.deepEqual([ui.ITEM_STATUS_LABEL.done, ui.ITEM_STATUS_LABEL.partial, ui.ITEM_STATUS_LABEL.no_signal], ['已完成', '進行中', '尚無進度資料']);
});

test('clicking a work item opens its detail and Escape closes it', async () => {
  await mount({field: {derived_status: '進行中', evidence: evidence(WITH_ITEMS)}});
  const row = document.querySelectorAll('.na-wi-row')[0];
  assert.equal(row.getAttribute('aria-label'), '查看工項 C1-1 導線測量 明細');
  await click(row);
  const sheet = document.querySelector('[role=dialog]');
  assert.equal(sheet.getAttribute('aria-label'), '工項明細 · C1-1 導線測量');
  const text = sheet.textContent;
  for (const expected of [/工項編號C1-1/, /工項名稱導線測量/, /所屬節點外業/, /計畫數量50/, /狀態進行中/, /完成度60%/, /營業額點數（計畫）100/, /已完成點數60/, /剩餘點數40/, /Lark 原生關聯/]) assert.match(text, expected);
  assert.equal(sheet.querySelector('a.na-evidence-link').getAttribute('href'), '#view=project&project=p1&tab=progress&node=field');
  await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})));
  assert.equal(document.querySelector('[role=dialog]'), null);
  await click(document.querySelectorAll('.na-wi-row')[1]);
  assert.match(document.querySelector('[role=dialog]').textContent, /已完成點數尚無進度資料/);
});

test('item progress needs a certain link and a valid pair of points', () => {
  assert.deepEqual(ui.itemProgress(workItem()), {earned: 60, planned: 100, remaining: 40, percent: 60});
  for (const patch of [{status: 'no_signal'}, {link_basis: 'ambiguous'}, {link_basis: 'unlinked'}, {remaining_points: null}, {planned_points: null}, {remaining_points: '101'}, {planned_points: '0', remaining_points: '0'}, {remaining_points: '-1'}]) assert.equal(ui.itemProgress(workItem(patch)), null, JSON.stringify(patch));
  assert.equal(ui.itemProgress(workItem({link_basis: 'derived'})).percent, 60);
});

test('a truncated list says how many are shown', async () => {
  await mount({field: {derived_status: '進行中', evidence: evidence({...WITH_ITEMS, items_total: 80, items_truncated: true})}});
  assert.match(document.querySelector('.na-wi').textContent, /僅顯示前 2 筆，共 80 筆/);
  assert.match(document.querySelector('.na-wi h4').textContent, /80 項/);
});

test('the item table is touch sized and cannot overflow at 390px', async () => {
  const css = await fs.readFile(new URL('./src/NodeAssignments.css', import.meta.url), 'utf8');
  assert.match(css, /\.na-wi-row\{[^}]*min-height:52px/);
  assert.match(css, /\.na-wi-name\{[^}]*overflow-wrap:anywhere/);
  assert.match(css, /@container\(max-width:700px\)\{\.na-wi-head\{display:none\}/);
});


test('a percent over few known items says it covers only them', () => {
  const heavy = ui.progressLine(evidence(UNKNOWN_HEAVY));
  assert.equal(heavy.text, '完成 99.9%（僅計有進度資料的 1 項；其餘 99 項尚無資料）');
  assert.deepEqual([heavy.partial, heavy.muted, heavy.fill], [true, true, 1]);
  const mostly = ui.progressLine(evidence({progress: {percent: '80', earned_points: '8', planned_points: '10', items_done: 1, items_total: 4, known_items: 3, unknown_items: 1}}));
  assert.equal(mostly.text, '完成 80%（僅計有進度資料的 3 項；其餘 1 項尚無資料）');
  assert.deepEqual([mostly.partial, mostly.muted, mostly.fill], [true, false, 60]);
  const gated = ui.progressLine(evidence({progress: {percent: null, earned_points: null, planned_points: null, items_done: 1, items_total: 4, known_items: 3, unknown_items: 1}}));
  assert.equal(gated.text, '已完成 1/4 工項（僅計有進度資料的 3 項；其餘 1 項尚無資料）');
});


test('selected node evidence renders every work item with honest per-item signals', async()=>{
 await mount({field:{evidence:evidence(WITH_ITEMS),can_submit_hint:true}});
 assert.equal(document.querySelectorAll('.na-wi-row').length,2);
 assert.equal(document.querySelector('.na-wi-row .na-progress-bar').getAttribute('aria-valuenow'),'60');
 assert.match(document.querySelectorAll('.na-wi-row')[1].textContent,/尚無進度資料/);
 assert.equal(document.querySelectorAll('.na-wi-row')[1].querySelector('.na-progress-bar'),null);
 assert.match(document.querySelector('.na-wi-summary').textContent,/完成 30%/);
 assert.match(document.querySelector('.na-evidence-hint').textContent,/可送審/);
});
test('unlinked daily evidence keeps unknown text without a zero percent', async()=>{
 await mount({field:{evidence:evidence({items_total:1,work_items:[workItem({status:'no_signal'})]})}});
 assert.match(document.querySelector('.na-wi-summary').textContent,/尚無進度資料/);
 assert.equal(document.querySelectorAll('.na-progress-bar').length,0);
 assert.doesNotMatch(document.querySelector('.na-wi').textContent,/0%/);
});
