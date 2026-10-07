// Render the real CompanyCockpit with a synthetic payload; no live or private source data.
import assert from 'node:assert/strict';
import {fakeClock} from './fake-clock-fixture.mjs';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {Simulate} from 'react-dom/test-utils';
const bundle=await build({stdin:{contents:"export {CompanyCockpit} from './src/CompanyCockpit';export {RuntimeHealthPanel} from './src/RuntimeHealthPanel';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.cockpit-test-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let CompanyCockpit,RuntimeHealthPanel;try{({CompanyCockpit,RuntimeHealthPanel}=await import(bundlePath.href))}finally{await fs.unlink(bundlePath)}
const lifecycle=(over)=>({relationship:'已關聯確認單',state:'mapped',canonical:'執行中',reasons:[],quote_workflow:[],...over});
const row=(id,over,lc)=>({case_type:'formal',id,code:id,name:'合成案件 '+id,group:'測試組',source_status:'執行中',source_lifecycle:lifecycle(lc),execution_status:'pending',tasks_total:0,tasks_completed:0,tasks_overdue:0,pending_local_reviews:0,pending_native_reviews:0,...over});
const cases=[
 // raw source_status says 已結案 but the lifecycle is blank: must not display or count as closed.
 row('SYN-A',{source_status:'已結案'},{state:'needs_verification',canonical:null,reasons:['blank'],quote_workflow:[{raw:'成案',kind:'won'}]}),
 // intake relationship with explicit lifecycle and a date-valued quote workflow.
 row('SYN-B',{case_type:'intake',source_status:'待確認單'},{relationship:'待確認單',canonical:'已結案',quote_workflow:[{raw:'2026-09-01',kind:'date'}]}),
 row('SYN-C',{},{state:'needs_verification',canonical:null,reasons:['conflict','unknown_option']}),
 row('SYN-D',{},{}),
];
const payload={as_of:'2026-10-06',checked_at:'2026-10-06T01:00:00Z',date_basis:'synthetic',source:{status:'ready',mapping_status:'ready',last_success_at:'2026-10-06T01:00:00Z'},
 totals:{cases:4,confirmed_cases:3,intake_records:1,workbench_cases:0,deliveries_confirmed:0,tasks_total:0,tasks_completed:0,tasks_overdue:0,pending_local_reviews:0,pending_native_reviews:0,
  source_status_counts:{已結案:1,執行中:2,待確認單:1},lifecycle_state_counts:{mapped:2,needs_verification:2},lifecycle_counts:{待核對:2,已結案:1,執行中:1},execution_status_counts:{pending:4}},
 missing:{task_due_date:0,group:0,source_status:0},groups:[{group:'測試組',cases:4,tasks_total:0,tasks_completed:0,tasks_overdue:0}],cases,
 pagination:{offset:0,limit:40,total:4,has_more:false}};
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=company'});
for(const key of ['window','document','location','history','sessionStorage','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const clock=fakeClock(dom.window);
const urls=[];
globalThis.fetch=async(url)=>{urls.push(String(url));return new Response(JSON.stringify(payload),{status:200,headers:{'content-type':'application/json'}})};
const root=createRoot(document.getElementById('root'));
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(r=>clock.realTimeout(r,0))});
await flush(()=>root.render(React.createElement(CompanyCockpit,{refreshVersion:0})));
let checks=0;const ok=(cond,msg)=>{assert.ok(cond,msg);checks++};
const headers=[...document.querySelectorAll('.cockpit-case-table thead th')].map(th=>th.textContent);
ok(document.querySelector('.cockpit-freshness').textContent.includes(new Date(payload.checked_at).toLocaleString('zh-TW',{hour12:false})),'legacy dashboard uses checked_at');
const sourceAsOf='2026-10-07T10:02:11+08:00';
await flush(()=>root.render(React.createElement(CompanyCockpit,{refreshVersion:0,freshness:{datasets:{sources:{as_of:sourceAsOf}}}})));
ok(document.querySelector('.cockpit-freshness').textContent.includes(new Date(payload.checked_at).toLocaleString('zh-TW',{hour12:false})),'retained dashboard never claims a newer sources time');
ok(['案件狀態','報價狀態','關聯'].every(h=>headers.includes(h)),'lifecycle, quote workflow and relationship are separate columns');
const rows=Object.fromEntries([...document.querySelectorAll('.cockpit-case-table tbody tr')].map(tr=>[tr.querySelector('th small').textContent.split(' · ')[0],[...tr.querySelectorAll('td')].map(td=>td.textContent)]));
ok(rows['SYN-A'][0].startsWith('待核對')&&rows['SYN-A'][0].includes('尚未填寫案件狀態'),'blank lifecycle is review-required, not the raw 已結案');
ok(!rows['SYN-A'][0].includes('已結案'),'raw source_status is never shown as lifecycle');
ok(rows['SYN-A'][1]==='成案'&&rows['SYN-A'][2]==='已關聯確認單','quote workflow and relationship preserved separately');
ok(rows['SYN-B'][0]==='已結案'&&rows['SYN-B'][1]==='2026-09-01'&&rows['SYN-B'][2]==='待確認單','explicit lifecycle shown beside date workflow and intake relationship; no inferred closure');
ok(rows['SYN-C'][0].includes('不一致')&&rows['SYN-C'][0].includes('無法對應'),'conflict and unknown options are explained');
ok(rows['SYN-D'][0]==='執行中'&&rows['SYN-D'][1]==='—','mapped lifecycle without quote workflow shows a dash');
const dist=[...document.querySelectorAll('.cockpit-distribution button')].map(b=>b.textContent);
ok(dist.some(t=>t.startsWith('待核對')&&t.endsWith('2'))&&dist.some(t=>t.startsWith('已結案')&&t.endsWith('1')),'lifecycle counts come from canonical values (raw closed + blank is not counted closed)');
ok(!document.querySelector('.cockpit-source').textContent.includes('來源進度'),'old source_status heading is gone');
const review=[...document.querySelectorAll('.cockpit-distribution button')].find(b=>b.textContent.startsWith('待核對'));
await flush(()=>review.click());
ok(urls.at(-1).includes('lifecycle=%E5%BE%85%E6%A0%B8%E5%B0%8D')&&!urls.at(-1).includes('source_status'),'filter sends lifecycle, not source_status');
// A stale server without the additive field degrades to review-required.
payload.cases=[{...cases[0],source_lifecycle:undefined,source_status:'已結案'}];payload.totals.lifecycle_counts=undefined;
await flush(()=>document.querySelector('.cockpit-filters .button').click());
const legacy=document.querySelector('.cockpit-case-table tbody td').textContent;
ok(legacy.startsWith('待核對')&&!legacy.includes('已結案'),'missing source_lifecycle never falls back to raw source_status');
const beforeIdle=urls.length;
await flush(()=>clock.advance(600000));
ok(urls.length===beforeIdle&&clock.intervals===0,'cockpit makes no periodic requests in ten minutes');
await flush(()=>document.querySelector('.cockpit-heading button').click());
ok(urls.length===beforeIdle+1,'cockpit manual refresh reads once');
// The search debounce is retained and reads only after the user edits search.
const input=document.querySelector('input[type=search]');
await flush(()=>{input.value='SYN';Simulate.change(input)});
const beforeSearch=urls.length;await flush(()=>clock.advance(249));ok(urls.length===beforeSearch,'search waits for its debounce');
await flush(()=>clock.advance(1));ok(urls.length===beforeSearch+1&&urls.at(-1).includes('q=SYN'),'user search reads after 250 ms');
await flush(()=>root.unmount());
const healthRoot=createRoot(document.getElementById('root'));let healthReads=0;
globalThis.fetch=async()=>{healthReads++;return new Response(JSON.stringify({checked_at:'2026-10-07T02:00:00Z',status:'ok',worker:{status:'ok'},backup:{status:'ok'},directory:{status:'ok'}}))};
await flush(()=>healthRoot.render(React.createElement(RuntimeHealthPanel,{w:{environment:'production',workspace_id:'synthetic'},s:{mode:'lark',user:{role:'manager'}}})));
ok(healthReads===1,'health reads once on view mount');
await flush(()=>clock.advance(600000));ok(healthReads===1&&clock.intervals===0,'health never schedules an interval or periodic read');
await flush(()=>document.querySelector('button').click());ok(healthReads===2,'manual health refresh reads once');
await flush(()=>healthRoot.unmount());clock.restore();dom.window.close();
console.log(`Company cockpit and runtime health: ${checks} checks passed`);
