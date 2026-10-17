import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {default as Assets} from './src/reports/AssetsTab';export {default as Progress} from './src/reports/ProgressTab';export {mockReport} from './src/reports/mock';export {invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd(),loader:'tsx'},loader:{'.css':'empty'},bundle:true,write:false,platform:'node',format:'cjs',packages:'external',jsx:'automatic'});
const mod={exports:{}};new Function('require','module','exports',bundle.outputFiles[0].text)(createRequire(import.meta.url),mod,mod.exports);
const {Assets,Progress,mockReport,invalidateSessionEpoch}=mod.exports;
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});Object.assign(globalThis,{window:dom.window,document:dom.window.document,location:dom.window.location,IS_REACT_ACT_ENVIRONMENT:true});
const requests=[];let basis='days',firstWeek,dropGroup=false;
globalThis.fetch=async url=>{const u=new URL(url,'http://localhost'),p=u.searchParams;requests.push(p);const endpoint=u.pathname.split('/').at(-1);const data=mockReport(endpoint,p);if(endpoint==='assets'){
 const instrument=p.get('kind')==='instrument';data.options.owner=instrument?['__blank__']:['自有','__blank__'];data.options.category=['__blank__','具名'];data.by_category=[{category:'',total:4,in_use:0,repair:0},{category:'具名',total:1,in_use:0,repair:0}];
 data.items=Array.from({length:p.get('category')==='__blank__'?4:5},(_,i)=>({...data.items[0],name:i<4?`空白儀器${i}`:'具名儀器',category:i<4?'':'具名',status:'',owner:''}));data.total=data.items.length;
 }else{data.basis=basis;data.kpi={...data.kpi,planned_days:8,matched_days:3,planned_points:100,matched_points:25,actual_points:40,achievement:.25};data.by_group=[{group:'未分組',planned:100,matched_points:25,actual:40,planned_days:8,matched_days:3,achievement:.25}];firstWeek??=p.get('week');data.options.group=dropGroup?['__blank__']:p.get('week')===firstWeek?['__blank__','A']:['__blank__','B'];}
 return new Response(JSON.stringify(data),{status:200});};
let root;const mount=async Component=>{root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(Component)));};
const click=async element=>{assert.ok(element,'click target exists');await act(async()=>element.click());};
const select=async(label,value)=>{const el=[...document.querySelectorAll('label')].find(e=>e.textContent.startsWith(label))?.querySelector('select');assert.ok(el,label);await act(async()=>{el.value=value;el.dispatchEvent(new window.Event('change',{bubbles:true}));});};
const button=text=>[...document.querySelectorAll('button')].find(e=>e.textContent.includes(text));
const test=process.env.REPORT_CASE;
if(test==='assets-blank'){await mount(Assets);await click(button('儀器'));await click(document.querySelector('[aria-label="資產類別"] .reports-bar-row'));assert.equal(requests.at(-1).get('category'),'__blank__');const rows=[...document.querySelectorAll('tbody tr')];assert.equal(rows.length,4);assert.ok(rows.every(r=>r.cells[0].textContent.startsWith('空白儀器')&&[1,2,3].every(i=>r.cells[i].textContent==='未填')));}
if(test==='asset-owner'){await mount(Assets);await select('管理分類','自有');assert.equal(requests.at(-1).get('owner'),'自有');const before=requests.length;await click(button('儀器'));assert.equal(requests.length,before+1);assert.equal(requests.at(-1).has('owner'),false);}
if(test==='progress-week'){await mount(Progress);await select('組別','A');const before=requests.length;await click(document.querySelector('[aria-label="前一週"]'));assert.equal(requests.length,before+1);assert.equal(requests.at(-1).has('group'),false);}
if(test==='progress-label'){await mount(Progress);while(document.querySelector('input[type=date]').value>'2026-09-07')await click(document.querySelector('[aria-label="前一週"]'));assert.equal(document.querySelector('input[type=date]').value,'2026-09-07');assert.equal(document.querySelector('option[value="__blank__"]').textContent,'未分組');assert.ok(button('未分組'));}
if(test==='points'){basis='points';await mount(Progress);assert.match(document.querySelector('.reports-metrics small').textContent,/對應 25 \/ 預排 100 點/);assert.match(document.querySelector('.reports-bar-row').textContent,/對應 25 \/ 預排 100 點/);const headers=[...document.querySelectorAll('th')].map(e=>e.textContent);for(const label of ['預排點數','對應點數','預排天數','對應天數','未預排天數'])assert.ok(headers.some(h=>h.includes(label)),label);}
if(test==='progress-sentinel'){await mount(Progress);await click(button('未分組'));assert.equal(requests.at(-1).get('group'),'__blank__');}
if(test==='progress-options'){await mount(Progress);dropGroup=true;invalidateSessionEpoch();const before=requests.length;await select('組別','A');assert.equal(requests.length,before+2);assert.equal(requests.at(-1).has('group'),false);assert.equal(document.querySelector('select').value,'');}
await act(async()=>root.unmount());console.log(`${test} passed.`);
