import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {workspace,a} from './session-epoch-fixture.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','location','localStorage','sessionStorage','HTMLElement','Event','MouseEvent'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const bundle=await build({stdin:{contents:"export {Dashboard,ShellDashboard} from './src/DailyHome';export {Projects} from './src/ProjectsList';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,format:'esm',platform:'node',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.overview-test-bundle.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);
let Dashboard,ShellDashboard,Projects;try{({Dashboard,ShellDashboard,Projects}=await import(path.href))}finally{await fs.unlink(path)}
const w=structuredClone(workspace);w.as_of='2026-10-08T09:00:00+08:00';w.projects=w.projects.slice(0,1);
const p=w.projects[0];p.code='CASE-001';p.contract_amount=120000;p.case_type='formal';p.execution_status='in_progress';p.source_lifecycle={state:'mapped',canonical:'執行中',reasons:[]};p.due_date='2026-10-10';
const base=p.nodes[0].tasks[0];p.nodes[0].tasks=[{...base,id:'ready',title:'Next survey',status:'in_progress',due_date:'2026-10-10'},{...base,id:'blocked',title:'Blocked survey',status:'paused',due_date:null,original_due_date:'2026-10-06'},{...base,id:'late',title:'Overdue survey',due_date:'2026-10-05'},{...base,id:'src1',title:'Source only A',can_execute:false,due_date:'2026-09-01'},{...base,id:'src2',title:'Source only B',can_execute:false,due_date:'2026-09-02'}];
w.users.push({id:'coworker',name:'Active coworker',active:true});
p.nodes[0].tasks.push({...base,id:'coworker-task',title:'Coworker assignment',owner_id:'coworker',can_execute:false,source_ref:undefined,due_date:'2026-10-04'});
const calls=[];const c={w,s:{user:a,mode:'demo',users:w.users},route:{view:'dashboard'},go:route=>calls.push(route),run:async()=>undefined,reloadVersion:0,busy:false};
const root=createRoot(document.getElementById('root'));
const flush=async fn=>act(async()=>{fn?.();await new Promise(r=>setTimeout(r,30))});
await flush(()=>root.render(React.createElement(Dashboard,{c})));
assert.equal(document.querySelector('.dh-hero h2').textContent,'Next survey');
const inbox=document.querySelector('.work-inbox');assert.ok(inbox.textContent.includes('Overdue survey'));assert.ok(inbox.textContent.includes('逾期 3 個曆日'));assert.equal(inbox.querySelector('.heading-count').textContent,'1','only actionable overdue belongs in attention');assert.ok(!inbox.textContent.includes('Blocked survey')&&!inbox.textContent.includes('Coworker assignment')&&!inbox.textContent.includes('Source only'));const cap=inbox.textContent;assert.ok(cap.includes('本人可執行逾期 1'));assert.ok(!cap.includes('非本人')&&!cap.includes('受阻'));
const waitingText=()=>[...document.querySelectorAll('.dh-waiting')].map(section=>section.textContent).join(' | ');
const waiting=waitingText();
for(const title of ['Blocked survey','Source only A','Source only B','Next survey'])assert.ok(waiting.includes(title),`assigned waiting category includes ${title}`);
assert.ok(waiting.includes('暫停中的指派1')&&waiting.includes('原期限 2026/10/06'),'paused assignment preserves its original deadline');
assert.ok(waiting.includes('等待前置條件2')&&waiting.includes('指派與執行資格待核對'),'blocked assignments have a reason');
assert.ok(waiting.includes('即將開始1')&&!waiting.includes('Coworker assignment'),'upcoming is separate and coworker is excluded');
await flush(()=>[...document.querySelectorAll('.dh-hero button')].find(b=>b.textContent.includes('繼續此任務')).click());assert.equal(calls.at(-1).focus,'ready');
const shell={...w,scope:'shell',counts:{overdue_tasks:1,my_overdue_tasks:1,due_today_tasks:0,my_active_tasks:2,approvals_pending:0},attention:[p.nodes[0].tasks.find(t=>t.id==='late')].map(t=>({task_id:t.id,title:t.title,project_id:p.id,project_code:p.code,node_id:p.nodes[0].id,node_name:p.nodes[0].name,assignee_id:t.owner_id,status:t.status,due_date:t.due_date})),home_waiting:[
 {task_id:'blocked',project_id:p.id,project_code:p.code,node_id:p.nodes[0].id,title:'Blocked survey',kind:'paused',reason:'暫停原因待核對',original_due_date:'2026-10-06',due_date:null},
 {task_id:'src1',project_id:p.id,project_code:p.code,node_id:p.nodes[0].id,title:'Source only A',kind:'prerequisite',reason:'指派與執行資格待核對',due_date:'2026-09-01'},
 {task_id:'src2',project_id:p.id,project_code:p.code,node_id:p.nodes[0].id,title:'Source only B',kind:'prerequisite',reason:'指派與執行資格待核對',due_date:'2026-09-02'},
 {task_id:'ready',project_id:p.id,project_code:p.code,node_id:p.nodes[0].id,title:'Next survey',kind:'upcoming',reason:'預計 2026/10/10 到期',due_date:'2026-10-10'},
],pending_approvals:[]};
await flush(()=>root.render(React.createElement(ShellDashboard,{c:{...c,w:shell}})));
const shellInbox=document.querySelector('.work-inbox');assert.equal(shellInbox.querySelector('.heading-count').textContent,'1');assert.ok(shellInbox.textContent.includes('本人可執行逾期 1'));assert.ok(!shellInbox.textContent.includes('非本人')&&!shellInbox.textContent.includes('Coworker assignment'));assert.deepEqual([...document.querySelectorAll('.dh-waiting')].map(section=>section.querySelector('h2').textContent),['暫停中的指派1','等待前置條件2','即將開始1'],'shell waiting categories match full');
for(const title of ['Blocked survey','Source only A','Source only B','Next survey'])assert.ok(waitingText().includes(title),`shell waiting includes ${title}`);
assert.equal(waitingText(),waiting,'full and shell render the same assigned waiting groups and explanations');
assert.ok(waitingText().includes('原期限 2026/10/06')&&!waitingText().includes('Coworker assignment'));
assert.ok(document.querySelector('.dh-hero').textContent.includes('2 項待處理'),'shell actionable count excludes waiting');

w.projects=Array.from({length:300},(_,i)=>({...structuredClone(p),id:`p${i}`,code:`CASE-${String(i+1).padStart(3,'0')}`,name:`Road survey ${i+1}`,created_at:String(300-i).padStart(3,'0')}));
await flush(()=>root.render(React.createElement(Projects,{c:{...c,route:{view:'projects'}}})));
assert.equal(document.querySelectorAll('tbody tr').length,10);assert.ok(document.querySelector('.table-footer').textContent.includes('共 300 筆'));
const row=document.querySelector('tbody tr');assert.equal(row.querySelector('.verification-cell').getAttribute('aria-label'),'已驗證');assert.ok(row.textContent.includes('受阻'));assert.ok(row.textContent.includes('即將到期'));assert.ok(row.querySelector('.deadline').classList.contains('is-upcoming'));assert.equal(row.querySelector('.numeric').textContent,'NT$ 120,000');
await flush(()=>[...document.querySelectorAll('.pager button')].find(b=>b.textContent==='下一頁').click());assert.ok(document.querySelector('tbody').textContent.includes('CASE-011'));assert.ok(!document.querySelector('tbody').textContent.includes('CASE-001'));
// Creation ordering is shared by shell requests and legacy rows.
w.projects=[['old','2026-10-01'],['new','2026-10-13'],['tied','2026-10-13'],['empty','']].map(([id,created_at])=>({...structuredClone(p),id,code:id,created_at}));
await flush(()=>root.render(React.createElement(Projects,{key:'created',c:{...c,route:{view:'projects'}}})));
assert.equal(document.querySelector('[aria-label="案件排序"]').value,'created');
const codes=()=>[...document.querySelectorAll('tbody .case-code')].map(e=>e.childNodes[0].textContent);
assert.deepEqual(codes(),['tied','new','old','empty']);
await flush(()=>document.querySelector('[aria-label="切換排序方向"]').click());
assert.deepEqual(codes(),['old','new','tied','empty']);
const requests=[];globalThis.fetch=async url=>{requests.push(String(url));return new Response(JSON.stringify({items:[],total:0,facets:{all:0,formal:0,intake:0}}),{status:200})};
await flush(()=>root.render(React.createElement(Projects,{key:'shell-created',c:{...c,w:{...w,scope:'shell'},route:{view:'projects'}}})));
assert.ok(requests.some(url=>url.includes('sort=created&dir=desc')),requests.join(' | '));
await flush(()=>root.unmount());dom.window.close();console.log('Overview design: ready action, separate assigned waiting parity, preserved original deadline, verification/deadline states and 300-case paging passed');
