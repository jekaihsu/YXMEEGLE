// F1/F2/F3 render tests: the real WorkPage in jsdom with a controllable fetch.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle = await build({entryPoints: ['./src/IntegratedPages.tsx'], bundle: true, write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
const mod = new URL('./.my-work-integrated-test.mjs', import.meta.url);
await fs.writeFile(mod, bundle.outputFiles[0].text);
let WorkPage;
try {({WorkPage} = await import(mod.href))} finally {await fs.unlink(mod)}
const dom = new JSDOM('<div id="root"></div>', {url: 'http://localhost/#view=work', pretendToBeVisual: true});
for (const key of ['window', 'document', 'location', 'history', 'Event', 'HTMLElement']) Object.defineProperty(globalThis, key, {value: dom.window[key], configurable: true, writable: true});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
dom.window.scrollTo = () => {};
const mk = (id, title, extra = {}) => ({id, title, case_title: '案件', work_item_title: '工項', assignee_name: '我', workflow_state: '進行中', ended: false, ...extra});
const bodyFor = (rows, extra = {}) => ({rows, readState: 'ready', assignment: 'assigned', canSeeAwaitingConfirmation: false, ...extra});
const pending = [];
globalThis.fetch = () => new Promise(resolve => pending.push(body => resolve(new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json'}}))));
const settle = () => act(async () => {await new Promise(r => setTimeout(r, 20))});
const respond = async body => {await act(async () => {pending.shift()(body)}); await settle()};
let go = () => {};
const root = createRoot(document.getElementById('root'));
const render = async ({user, reloadVersion, selected}) => {
 const route = {view: 'work', ...(selected ? {ctx: JSON.stringify({v: 1, search: '', mode: 'todo', selectedId: selected})} : {})};
 await act(async () => root.render(React.createElement(WorkPage, {c: {route, go, reloadVersion, w: {version: 1}, s: {user: {id: user}}}})));
 await settle();
};
const text = () => document.body.textContent;

// F2: data timestamp + completeness in the top bar
await render({user: 'u1', reloadVersion: 1});
await respond(bodyFor([mk('a', '任務甲')], {as_of: '2026-10-14'}));
assert.match(document.querySelector('.my-work-banner')?.textContent ?? text(), /完整讀取/);
assert.match(text(), /資料日期 2026-10-14/, 'F2 as_of rendered');

// F3: switching user / reloadVersion drops the previous body while refetching
await render({user: 'u2', reloadVersion: 1});
assert.doesNotMatch(text(), /任務甲/, 'F3 previous user rows hidden on user change');
assert.doesNotMatch(text(), /完整讀取/, 'F3 previous completeness hidden');
await respond(bodyFor([mk('b', '任務乙')], {as_of: '2026-10-15'}));
assert.match(text(), /任務乙/);
await render({user: 'u2', reloadVersion: 2});
assert.doesNotMatch(text(), /任務乙/, 'F3 rows hidden while reloadVersion refetch is in flight');
await respond(bodyFor([mk('b', '任務乙')], {as_of: '2026-10-15'}));
assert.match(text(), /任務乙/);

// F1: drawer evidence
await render({user: 'u2', reloadVersion: 2, selected: 'b'});
assert.doesNotMatch(text(), /無附加佐證/, 'F1 absent evidence must not read as none');
const section = [...document.querySelectorAll('.my-work-drawer-section')].find(s => s.textContent.includes('附加佐證'));
assert.match(section.textContent, /佐證資料尚未提供/, 'F1 absent evidence is distinguished from an empty list in Chinese');
await render({user: 'u3', reloadVersion: 2, selected: 'b'});
await respond(bodyFor([mk('b', '任務乙', {evidence: []})]));
const section2 = [...document.querySelectorAll('.my-work-drawer-section')].find(s => s.textContent.includes('附加佐證'));
assert.match(section2.textContent, /無附加佐證/, 'F1 explicit empty list renders none');
// The current assignment route has one source message and never claims unknown work is zero.
const renderAssigned=async version=>{await act(async()=>root.render(React.createElement(WorkPage,{c:{route:{view:'work'},go,reloadVersion:version,refresh:async()=>{},w:{version:1},s:{features:{node_assignment:true},user:{id:'assigned-user'}}}})));await settle()};
const assignment={panel:'assigned',scope:'mine',readState:'partial',snapshot_version:'one',as_of:null,freshness:{status:'unknown',last_success_at:null,refreshing:false},counts:{node_assignments:null,tasks:null,local_workflow:null,sop_tasks:0,complete:false},items:[],next_cursor:null,has_more:false,complete:false,total_count:null,manager_view_available:false};
await renderAssigned(1);await respond(assignment);
assert.equal(document.querySelectorAll('.work-page [role=status]').length,1);
assert.match(text(),/工作來源尚未完整，請重新讀取。/);
assert.doesNotMatch(text(),/未知|0 項|目前沒有符合條件|尚無成功讀取時間/);
assert.equal(document.querySelector('table'),null,'hide empty groups');
await renderAssigned(2);await respond({...assignment,complete:true,readState:'ready',counts:{...assignment.counts,complete:true},total_count:0});
assert.match(text(),/目前沒有符合條件的工作。/);
assert.doesNotMatch(text(),/工作來源尚未完整/);
await act(async () => root.unmount());
console.log('my-work integrated render: ok');
