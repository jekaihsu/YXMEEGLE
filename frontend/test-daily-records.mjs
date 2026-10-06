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
process.exit(0);
