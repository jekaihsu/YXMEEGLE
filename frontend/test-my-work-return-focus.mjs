// W1: browser Back from a My Work row's task/project navigation must land keyboard focus on the originating row's
// selection control (or the page heading when the row is gone), never BODY. Real WorkPage in jsdom, hash-driven host.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle = await build({entryPoints: ['./src/IntegratedPages.tsx'], bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
const mod = new URL('./.my-work-return-focus-test.mjs', import.meta.url);
await fs.writeFile(mod, bundle.outputFiles[0].text);
let WorkPage, parseRoute;
try {({WorkPage} = await import(mod.href))} finally {await fs.unlink(mod)}
const apiBundle = await build({stdin: {contents: "export {parseRoute} from './src/api.ts'", resolveDir: process.cwd(), loader: 'ts'}, bundle: true, write: false, platform: 'node', format: 'esm', packages: 'external'});
({parseRoute} = await import('data:text/javascript;base64,' + Buffer.from(apiBundle.outputFiles[0].text).toString('base64')));

const dom = new JSDOM('<div id="root"></div>', {url: 'http://localhost/#view=work', pretendToBeVisual: true});
for (const key of ['window', 'document', 'location', 'history', 'Event', 'HTMLElement']) Object.defineProperty(globalThis, key, {value: dom.window[key], configurable: true, writable: true});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.scrollTo = () => {};
const entry = (kind, route) => ({kind, exists: true, authorized: true, route});
const rows = [
 {id: 't1', title: '任務一', case_title: '案件', work_item_title: '工項', assignee_name: '我', workflow_state: '進行中', ended: false, entry_points: [entry('task', '/#view=project&project=p1&task=t1&tab=flow')]},
 {id: 't2', title: '任務二', case_title: '案件', work_item_title: '工項', assignee_name: '我', workflow_state: '進行中', ended: false, entry_points: [entry('case', '/#view=project&project=p2')]},
];
let body = {rows, readState: 'ready', assignment: 'assigned', canSeeAwaitingConfirmation: false};
globalThis.fetch = async () => new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}});
const tick = () => act(async () => {await new Promise(r => setTimeout(r, 20))});

function Host() {
 const [route, setRoute] = React.useState(() => parseRoute(location.hash));
 React.useEffect(() => {
  const sync = () => setRoute(parseRoute(location.hash));
  window.addEventListener('hashchange', sync); window.addEventListener('popstate', sync);
  return () => {window.removeEventListener('hashchange', sync); window.removeEventListener('popstate', sync)};
 }, []);
 // Mirrors App.go: push via location.hash, replace via history.replaceState.
 const go = (next, replace = false) => {
  const q = new URLSearchParams(); Object.entries(next).forEach(([k, v]) => {if (v) q.set(k, v)});
  if (replace) history.replaceState(null, '', location.pathname + location.search + '#' + q.toString()); else location.hash = q.toString();
  setRoute(parseRoute(location.hash));
 };
 return route.view === 'work' ? React.createElement(WorkPage, {c: {route, go, reloadVersion: 1, w: {version: 1}}}) : React.createElement('main', {id: 'task-page'}, 'task');
}
const root = createRoot(document.getElementById('root'));
const settle = async () => {await tick(); await tick()};
const back = async () => {
 const changed = new Promise(r => window.addEventListener('hashchange', r, {once: true}));
 await act(async () => {history.back(); await changed}); await settle();
};
const label = el => `${el?.tagName}${el?.getAttribute?.('aria-label') ? ':' + el.getAttribute('aria-label') : ''}`;
await act(async () => root.render(React.createElement(Host))); await settle();

// 1. select row t1 via keyboard-reachable button, drawer opens, hash carries the selection
const btn = id => document.querySelector(`[data-row-select-id="${id}"]`);
await act(async () => {btn('t1').focus(); btn('t1').click()}); await settle();
assert.match(location.hash, /ctx=/); const returnHash = location.hash;
assert.ok(document.querySelector('.my-work-drawer'), 'drawer open');

// 2. search then navigate from the row's action button: task navigation unmounts WorkPage
const actions = [...document.querySelectorAll('.my-work-table .my-work-action-button')];
assert.ok(actions.length >= 1);
await act(async () => {actions[0].focus(); actions[0].click()}); await settle();
assert.ok(document.getElementById('task-page'), 'navigated away');
assert.ok(!document.querySelector('.my-work-container'), 'WorkPage unmounted');

// 3. browser Back restores hash context and focuses the originating row's selection control
await back();
assert.equal(location.hash, returnHash, 'hash return context preserved');
assert.ok(document.querySelector('.my-work-drawer'), 'selection/drawer restored');
assert.notEqual(document.activeElement, document.body, 'focus must not fall to BODY');
assert.equal(document.activeElement, btn('t1'), `focus on originating row control, got ${label(document.activeElement)}`);

// 4. drawer-close focus behaviour preserved (Escape inside the drawer returns focus to the row)
await act(async () => {document.querySelector('.my-work-drawer-close').focus(); document.querySelector('.my-work-drawer-close').click()}); await settle();
assert.ok(!document.querySelector('.my-work-drawer'));
assert.equal(document.activeElement, btn('t1'), 'drawer close still restores row focus');

// 5. a fresh visit (no row navigation) does not steal focus
await act(async () => {location.hash = 'view=other'}); await settle();
await act(async () => {location.hash = 'view=work'}); await settle();
assert.equal(document.activeElement, document.body, 'fresh mount keeps focus untouched');

// 6. originating row gone after Back (data changed): focus falls to the page heading, still not BODY
await act(async () => {btn('t2').focus(); btn('t2').click()}); await settle();
const hash2 = location.hash;
const acts2 = [...document.querySelectorAll('.my-work-table .my-work-action-button')];
await act(async () => {acts2[1].focus(); acts2[1].click()}); await settle();
assert.ok(document.getElementById('task-page'));
body = {...body, rows: [rows[0]]};
await back();
assert.equal(location.hash, hash2);
assert.notEqual(document.activeElement, document.body);
assert.equal(document.activeElement?.tagName, 'H2', `heading fallback, got ${label(document.activeElement)}`);
assert.equal(document.activeElement.getAttribute('tabindex'), '-1');
await act(async () => root.unmount());
console.log('my-work return focus: ok');
