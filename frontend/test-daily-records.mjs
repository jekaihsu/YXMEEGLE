// Render the real DailyRecords with a synthetic API payload; no live or private source data.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({entryPoints:['src/DailyRecords.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.daily-test-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let DailyRecords;try{DailyRecords=(await import(bundlePath.href)).DailyRecords}finally{await fs.unlink(bundlePath)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event'])try{globalThis[key]=dom.window[key]}catch{}
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const cases=[
 ['syn-approved',{status:'approved',source_status:'已通過'},'原日報已核准'],
 ['syn-returned',{status:'returned',source_status:'已退回'},'原日報已退回'],
 ['syn-pending',{status:'pending',source_status:'待檢核'},'原日報待檢核'],
 ['syn-unverified',{status:'unverified',source_status:''},'原日報檢核待查證'],
 ['syn-unknown',{status:'reviewed'},'原日報檢核待查證'],
 ['syn-conflict',{status:'conflict'},'原日報檢核待查證'],
 ['syn-partial',{status:'partial'},'原日報檢核待查證'],
 ['syn-missing',undefined,'原日報檢核待查證'],
];
const items=cases.map(([id,review],i)=>({id,date:'2026-10-0'+(i+1),department:'測試組',person:'合成人員',description:id,project_id:'P1',project_code:'SYN-1',review}));
globalThis.fetch=async()=>new Response(JSON.stringify({items,total:items.length,offset:0,limit:30,summary:{matched:items.length,unmatched:0,source_missing:0}}),{status:200,headers:{'content-type':'application/json'}});
const w={version:1,projects:[],daily_unmatched:[]};const p={id:'P1',code:'SYN-1',daily_reports:[]};
const root=createRoot(document.getElementById('root'));
await act(async()=>{root.render(React.createElement(DailyRecords,{w,p,go:()=>{}}));await new Promise(r=>setTimeout(r,20))});
const labels=Object.fromEntries([...document.querySelectorAll('.daily-cards article')].map(a=>[a.querySelector('p').textContent,[...a.querySelectorAll('footer span')].map(s=>s.textContent)]));
for(const [id,,label] of cases){assert.ok(labels[id]?.includes(label),`${id} shows ${label}, got ${labels[id]}`);
 for(const other of ['原日報已核准','原日報已退回','原日報待檢核','原日報檢核待查證'])if(other!==label)assert.ok(!labels[id].includes(other),`${id} must not show ${other}`)}
console.log(`Daily records: ${cases.length} review states render explicit labels`);

// Request-state regressions: offset, page label and items must agree.
const click=async(text)=>{await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent===text).dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));await new Promise(r=>setTimeout(r,20))})};
const status=()=>document.querySelector('[role=status]').textContent;
const shown=()=>[...document.querySelectorAll('.daily-cards article p')].map(x=>x.textContent);
const mk=(pid,ids)=>ids.map(id=>({id,date:'2026-10-01',department:'組',person:'人',description:id,project_id:pid,project_code:pid}));
const calls=[];let handler;
globalThis.fetch=async(url)=>{const q=new URL(String(url),'http://x').searchParams;calls.push({pid:q.get('project_id'),offset:q.get('offset')});return new Response(JSON.stringify(handler(q)),{status:200,headers:{'content-type':'application/json'}})};
const render=async(proj)=>{await act(async()=>{root.render(React.createElement(DailyRecords,{w,p:proj,go:()=>{}}));await new Promise(r=>setTimeout(r,20))})};
const resp=(items,total)=>({items,total,offset:0,limit:30,summary:{matched:total,unmatched:0,source_missing:0}});
// Case 1: A at page 3 -> switch to one-row B resets to offset 0 and shows B's record.
handler=q=>q.get('project_id')==='A'?resp(mk('A',['a-row']),100):resp(mk('B',['b-only']),1);
await render({id:'A',code:'A',daily_reports:[]});
await click('下一頁');await click('下一頁');
assert.equal(calls.at(-1).offset,'60');assert.match(status(),/第 3／4 頁/);
calls.length=0;
await render({id:'B',code:'B',daily_reports:[]});
assert.ok(calls.every(c=>c.pid==='B'&&c.offset==='0'),`B requests use offset 0: ${JSON.stringify(calls)}`);
assert.deepEqual(shown(),['b-only']);assert.match(status(),/共 1 筆.*第 1／1 頁/);
// Case 2: page 3 shrinks to one page -> refetch offset 0 with matching label/items.
let total=100;handler=q=>Number(q.get('offset'))>=total?resp([],total):resp(mk('C',['c@'+q.get('offset')]),total);
await render({id:'C',code:'C',daily_reports:[]});
await click('下一頁');await click('下一頁');
assert.equal(calls.at(-1).offset,'60');
total=20;calls.length=0;
await act(async()=>{root.render(React.createElement(DailyRecords,{w:{...w,version:2},p:{id:'C',code:'C',daily_reports:[]},go:()=>{}}));await new Promise(r=>setTimeout(r,40))});
await act(async()=>{await new Promise(r=>setTimeout(r,20))});
assert.equal(calls.at(-1).offset,'0',`shrink refetches offset 0: ${JSON.stringify(calls)}`);
assert.deepEqual(shown(),['c@0']);assert.match(status(),/共 20 筆.*第 1／1 頁/);
assert.equal(document.querySelectorAll('button[disabled]').length,2);
console.log('Daily records: project switch and shrink keep offset, label and items consistent');
process.exit(0);
