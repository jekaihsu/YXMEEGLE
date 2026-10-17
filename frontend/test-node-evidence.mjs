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
const bundle = await build({stdin: {contents: "export * from './src/nodeAssignmentApi';export * from './src/nodeEvidence';export {NodeAssignments} from './src/NodeAssignments';export {invalidateSessionEpoch} from './src/api';", resolveDir: new URL('.', import.meta.url).pathname}, bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
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
  await act(async () => root.render(React.createElement(ui.NodeAssignments, {projectId: 'p1', enabled: true, legacy: null})));
}
afterEach(async () => {if (root) {await act(async () => root.unmount()); root = null}});
const card = key => [...document.querySelectorAll('.na-flow-card')].find(c => c.querySelector('.na-card-top strong')?.textContent === key);

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

test('a production card with mapped rows shows the evidence line, the data tag and a link to the progress tab', async () => {
  await mount({field: {derived_status: '進行中', status: '未開始', evidence: evidence(KNOWN)}});
  const field = card('外業');
  const wrap = field.closest('.na-card-wrap');
  assert.match(field.textContent, /計畫 123\.45 · 日報 2 筆 · 最近 10\/12/);
  assert.match(field.textContent, /依案件資料判定/);
  assert.match(field.textContent, /任務（選用） 0\/0/);
  assert.doesNotMatch(field.textContent, /來源未提供|0%/);
  assert.equal(field.querySelector('.na-evidence-hint'), null);
  const link = wrap.querySelector('a.na-evidence-link');
  assert.equal(link.getAttribute('href'), '#view=project&project=p1&tab=progress');
  assert.equal(field.contains(link), false);
});

test('unknown evidence says so in muted text and never shows 0%', async () => {
  await mount({field: {derived_status: '待處理', status: '待處理'}});
  const field = card('外業');
  assert.match(field.textContent, /計畫 123\.45/);
  assert.match(field.querySelector('.na-muted').textContent, /^尚無進度資料（日報未連結或尚未開工）$/);
  assert.equal(field.querySelector('.na-progress-bar'), null);
  assert.doesNotMatch(field.textContent, /日報 \d|0%|完成|來源未提供|依案件資料判定/);
  assert.match(field.textContent, /無任務/);
});

test('the submit hint shows only when the server says so', async () => {
  await mount({field: {derived_status: '進行中', evidence: evidence(KNOWN), can_submit_hint: true}, control: {derived_status: '進行中', evidence: evidence({...KNOWN, drives_status: false})}});
  assert.equal(card('外業').querySelector('.na-evidence-hint').textContent, '可送審');
  assert.equal(card('控制').querySelector('.na-evidence-hint'), null);
  assert.doesNotMatch(card('控制').textContent, /依案件資料判定/);
});

test('optional tasks keep their real counts and percentage when they exist', async () => {
  await mount({field: {derived_status: '進行中', evidence: evidence(KNOWN), tasks: {done: 1, total: 4}, progress: 0.25}});
  assert.match(card('外業').textContent, /任務（選用） 1\/4.*25%/);
});

test('cards without evidence keep the old task wording and have no link', async () => {
  await mount();
  assert.match(card('業務').textContent, /0\/0 項任務/);
  assert.equal(card('業務').closest('.na-card-wrap'), null);
});

const HOSTILE = ['1e9999999999', '1e99999', '-5', 'NaN', 'Infinity', '1'.repeat(101), '1,5', ''];

test('an unbounded or non-decimal quantity is neutralized to null and the list still parses', async () => {
  for (const bad of HOSTILE) {
    globalThis.fetch = async () => reply(listWith({field: {evidence: evidence({planned_qty: bad, actual_value: bad})}}));
    const parsed = await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true);
    const e = parsed.nodes.find(n => n.key === 'field').evidence;
    assert.deepEqual([e.planned_qty, e.actual_value], [null, null], bad);
  }
});

test('a hostile planned quantity leaves the page mounted with the no-data wording', async () => {
  await mount({field: {evidence: evidence({planned_qty: '1e9999999999', actual_value: '1e9999999999'})}});
  assert.ok(document.getElementById('root').innerHTML.length > 0);
  assert.match(card('外業').textContent, /尚無進度資料/);
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

test('a card with item progress shows the bar, the percent and a collapsed item list', async () => {
  await mount({field: {derived_status: '進行中', evidence: evidence(WITH_ITEMS)}});
  const field = card('外業'), wrap = field.closest('.na-card-wrap');
  assert.match(field.textContent, /完成 30%（已完成 0\/2 工項）/);
  assert.equal(field.querySelector('.na-progress-bar > span').style.width, '30%');
  assert.equal(field.querySelector('.na-progress-bar').getAttribute('role'), 'progressbar');
  assert.equal(field.querySelector('.na-progress-bar').getAttribute('aria-valuenow'), '30');
  assert.equal(field.querySelector('.na-evidence .na-muted'), null);
  const details = wrap.querySelector('details.na-items');
  assert.equal(details.open, false);
  assert.equal(details.querySelector('summary').textContent, '工項明細（2）');
  assert.equal(field.contains(details), false);
  const rows = [...details.querySelectorAll('li')];
  assert.equal(rows.length, 2);
  assert.match(rows[0].textContent, /C1-1.*導線測量.*數量 50.*進行中.*剩餘 40 \/ 100 點/);
  assert.match(rows[1].textContent, /C1-2.*水準測量.*數量 5.*尚無進度資料/);
  assert.equal(rows[1].querySelector('.na-item-status').className.includes('na-item-no_signal'), true);
  assert.doesNotMatch(rows[1].textContent, /0%/);
  assert.equal(wrap.querySelector('a.na-evidence-link').textContent.trim(), '到工程進度看完整證據');
  assert.equal(wrap.lastElementChild, wrap.querySelector('a.na-evidence-link'));
});

test('items without any signal never render a percentage or a bar', async () => {
  const idle = workItem({status: 'no_signal', remaining_points: '100'});
  await mount({field: {derived_status: '待處理', evidence: evidence({items_total: 1, work_items: [idle]})}});
  const field = card('外業');
  assert.equal(field.querySelector('.na-progress-bar'), null);
  assert.match(field.querySelector('.na-muted').textContent, /^尚無進度資料（日報未連結或尚未開工）$/);
  assert.doesNotMatch(field.closest('.na-card-wrap').textContent.replace(/任務（選用） 0\/0/, ''), /\d+%/);
  assert.equal(field.closest('.na-card-wrap').querySelector('details summary').textContent, '工項明細（1）');
});

test('a viewer without the points gate sees the counts and statuses only', async () => {
  const gated = {progress: {percent: null, earned_points: null, planned_points: null, items_done: 1, items_total: 2}, items_total: 2, drives_status: true,
    work_items: [workItem({planned_points: null, remaining_points: null, status: 'done'}), workItem({planned_points: null, remaining_points: null, status: 'no_signal'})]};
  await mount({field: {derived_status: '進行中', evidence: evidence(gated)}});
  const wrap = card('外業').closest('.na-card-wrap');
  assert.match(card('外業').textContent, /已完成 1\/2 工項/);
  assert.equal(card('外業').querySelector('.na-progress-bar'), null);
  assert.doesNotMatch(wrap.textContent, /點|%/);
  assert.match(wrap.querySelectorAll('li')[0].textContent, /已完成/);
});

test('all items done shows the submit chip while the status stays in progress', async () => {
  const done = {progress: {percent: '100', earned_points: '9', planned_points: '9', items_done: 2, items_total: 2}, items_total: 2, drives_status: true,
    work_items: [workItem({remaining_points: '0', status: 'done'}), workItem({remaining_points: '0', status: 'done'})]};
  await mount({field: {derived_status: '進行中', evidence: evidence(done), can_submit_hint: true}});
  const field = card('外業');
  assert.equal(field.querySelector('.na-evidence-hint').textContent, '可送審');
  assert.match(field.textContent, /進行中/);
  assert.match(field.textContent, /完成 100%（已完成 2\/2 工項）/);
  assert.doesNotMatch(field.textContent, /待審核|已完成節點/);
});

test('a truncated list says how many are shown', async () => {
  await mount({field: {derived_status: '進行中', evidence: evidence({...WITH_ITEMS, items_total: 80, items_truncated: true})}});
  assert.match(card('外業').closest('.na-card-wrap').querySelector('details').textContent, /僅顯示前 2 筆，共 80 筆/);
});

test('the item list is touch sized and cannot overflow at 390px', async () => {
  const css = await fs.readFile(new URL('./src/NodeAssignments.css', import.meta.url), 'utf8');
  assert.match(css, /\.na-items>summary\{[^}]*min-height:44px/);
  assert.match(css, /\.na-items li\{[^}]*overflow-wrap:anywhere/);
  assert.match(css, /\.na-card-wrap:has\(\.na-items\[open\]\)\{[^}]*grid-column:1\/-1/);
});

const UNKNOWN_HEAVY = {progress: {percent: '99.9', earned_points: '1', planned_points: '1', items_done: 1, items_total: 100, known_items: 1, unknown_items: 99}, items_total: 100,
  drives_status: true, work_items: [workItem({remaining_points: '0', planned_points: '1', status: 'done'})]};

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

test('an unknown-heavy card leads with the caveat, mutes the percent and keeps the bar nearly empty', async () => {
  await mount({field: {derived_status: '進行中', evidence: evidence(UNKNOWN_HEAVY)}});
  const field = card('外業'), percent = field.querySelector('.na-evidence-percent');
  assert.equal(percent.classList.contains('is-muted'), true);
  assert.equal(percent.firstElementChild.textContent, '僅計有進度資料的 1 項；其餘 99 項尚無資料');
  assert.match(percent.textContent, /完成 99\.9%$/);
  assert.equal(field.querySelector('.na-progress-bar').classList.contains('is-partial'), true);
  assert.equal(field.querySelector('.na-progress-bar > span').style.width, '1%');
  assert.doesNotMatch(field.textContent, /已完成 1\/100/);
});

test('an item that is not certainly linked reads 關聯待確認 instead of a status', async () => {
  const items = [workItem({link_basis: 'ambiguous', status: 'no_signal', planned_points: null, remaining_points: null}), workItem({code: 'C1-2', link_basis: 'unlinked', status: 'no_signal'}), workItem({code: 'C1-3', link_basis: 'derived', status: 'done', remaining_points: '0'})];
  await mount({field: {derived_status: '待處理', evidence: evidence({items_total: 3, work_items: items})}});
  const rows = [...card('外業').closest('.na-card-wrap').querySelectorAll('li .na-item-status')].map(n => n.textContent);
  assert.deepEqual(rows, ['關聯待確認', '關聯待確認', '已完成']);
  assert.equal(ui.itemStatusLabel({status: 'partial', link_basis: ''}), '進行中');
});

test('an item without code or name is kept and labelled', async () => {
  globalThis.fetch = async () => reply(listWith({field: {evidence: evidence({items_total: 3, work_items: [workItem({code: null, name: null}), workItem({code: null, name: '只有名稱'}), workItem({code: 'C9', name: null})]})}}));
  const parsed = await ui.fetchNodeAssignments('p1', new AbortController().signal, () => true);
  const e = parsed.nodes.find(n => n.key === 'field').evidence;
  assert.deepEqual(e.work_items.map(ui.itemLabel), ['未命名工項', '只有名稱', 'C9']);
  await mount({field: {derived_status: '進行中', evidence: e}});
  const names = [...card('外業').closest('.na-card-wrap').querySelectorAll('.na-item-name')].map(n => n.textContent.trim());
  assert.deepEqual(names, ['未命名工項', '只有名稱', 'C9']);
});
