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
  actual_source: null, reason: '尚無日報連結到此案件', drives_status: false, ...patch});
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
  assert.deepEqual(by('field').evidence, {planned_qty: '123.4500', lines: 2, items: 5, work_orders: 2, latest_date: '2026-10-12', actual_known: true, actual_value: '5', actual_source: 'v4_daily', reason: '已有 2 筆日報連結到此案件', drives_status: true});
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
  assert.deepEqual(ui.evidenceLine(evidence()), {known: false, plan: '計畫 123.45', text: '尚無日報連結（完成量未知）'});
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
  assert.match(field.querySelector('.na-muted').textContent, /^尚無日報連結（完成量未知）$/);
  assert.doesNotMatch(field.textContent, /日報 \d|0%|來源未提供|依案件資料判定/);
  assert.match(field.textContent, /無任務/);
});

test('the submit hint shows only when the server says so', async () => {
  await mount({field: {derived_status: '進行中', evidence: evidence(KNOWN), can_submit_hint: true}, control: {derived_status: '進行中', evidence: evidence({...KNOWN, drives_status: false})}});
  assert.equal(card('外業').querySelector('.na-evidence-hint').textContent, '資料顯示已達計畫量，可送審');
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
  assert.match(card('外業').textContent, /尚無日報連結/);
});

test('the quantity formatter never throws', () => {
  for (const bad of HOSTILE) assert.doesNotThrow(() => ui.evidenceLine(evidence({planned_qty: bad})), bad);
  assert.equal(ui.evidenceLine(evidence({planned_qty: '1e9999999999'})).known, false);
});
