import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {useReport,useDebounce,useReportSearch} from './src/reports/useReport';export {invalidateSessionEpoch} from './src/api';export {ReportState} from './src/reports/shared';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const path=new URL('./.reports-requests-bundle.mjs',import.meta.url);await writeFile(path,bundle.outputFiles[0].text);let useReport,useDebounce,useReportSearch,invalidateSessionEpoch,ReportState;try{({useReport,useDebounce,useReportSearch,invalidateSessionEpoch,ReportState}=await import(path.href))}finally{await unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});Object.assign(globalThis,{window:dom.window,document:dom.window.document,location:dom.window.location,IS_REACT_ACT_ENVIRONMENT:true});
const pending=[];globalThis.fetch=(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}));
function View({group}){const state=useReport('review',{group});return React.createElement('div',null,state.loading?'loading':state.error||state.data?.value)}
const root=createRoot(document.getElementById('root'));const render=group=>act(async()=>root.render(React.createElement(View,{group})));const reply=(i,value)=>act(async()=>pending[i].resolve(new Response(JSON.stringify({value}),{status:200})));
await render('一組');await render('二組');assert.equal(pending[0].options.signal.aborted,true);await reply(1,'current');await reply(0,'old');assert.equal(document.body.textContent,'current');
await render('一組');await reply(2,'cached one');await render('二組');assert.equal(pending.length,3);assert.equal(document.body.textContent,'current');await render('三組');invalidateSessionEpoch();await reply(3,'wrong session');assert.equal(document.body.textContent,'loading');
await act(async()=>root.unmount());assert.equal(pending[3].options.signal.aborted,true);
console.log('Reports stale responses, session epoch and unmount cancellation passed.');

const searchRoot=createRoot(document.getElementById('root'));
function Search({search}){const [offset,setOffset]=React.useState(50);const q=useDebounce(search,()=>setOffset(0));return React.createElement('div',null,`${q}:${offset}`)}
await act(async()=>searchRoot.render(React.createElement(Search,{search:''})));
await act(async()=>searchRoot.render(React.createElement(Search,{search:'new'})));
assert.equal(document.body.textContent,':50');
await act(async()=>new Promise(r=>setTimeout(r,300)));
assert.equal(document.body.textContent,'new:0');
await act(async()=>searchRoot.unmount());
console.log('Search offset resets with the debounced query.');

const atomicRoot=createRoot(document.getElementById('root'));let searchActions;
function AtomicSearch(){const [group,setGroup]=React.useState('A');const state=useReportSearch(()=>{});searchActions={...state,clear:()=>{state.applySearch('');setGroup('')},rank:()=>{state.applySearch('ranked');setGroup('B')}};useReport('review/rows',{group,q:state.q});return null}
await act(async()=>atomicRoot.render(React.createElement(AtomicSearch)));
await act(async()=>searchActions.setSearch('old'));
await act(async()=>new Promise(r=>setTimeout(r,300)));
let before=pending.length;
await act(async()=>searchActions.clear());
assert.equal(pending.length,before+1);assert.equal(new URL(pending.at(-1).url,'http://localhost').searchParams.has('q'),false);
await act(async()=>searchActions.setSearch('pending'));
before=pending.length;
await act(async()=>searchActions.rank());
assert.equal(pending.length,before+1);assert.equal(new URL(pending.at(-1).url,'http://localhost').searchParams.get('q'),'ranked');
await act(async()=>new Promise(r=>setTimeout(r,300)));assert.equal(pending.length,before+1);
await act(async()=>atomicRoot.unmount());
console.log('Clear and ranking apply the query and filters together without stale requests.');


const warmingRoot=createRoot(document.getElementById('root'));
let warmingState;
function Warming({group}){warmingState=useReport('sales',{pm:group});return warmingState.data?React.createElement('div',null,warmingState.data.value):React.createElement(ReportState,warmingState)}
const realSetTimeout=globalThis.setTimeout,realClearTimeout=globalThis.clearTimeout;
const timers=new Map();let timerId=0;
globalThis.setTimeout=(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id};
globalThis.clearTimeout=id=>timers.delete(id);
const tick=()=>act(async()=>{const [id,timer]=timers.entries().next().value;timers.delete(id);timer.fn()});
const warmReply=()=>act(async()=>pending.at(-1).resolve(new Response(JSON.stringify({detail:'warming',warming:true,retry_after:5}),{status:503})));
try{
 await act(async()=>warmingRoot.render(React.createElement(Warming,{group:'warm'})));
 let count=pending.length;
 await warmReply();
 assert.match(document.body.textContent,/正在首次讀取 Lark 資料，約需 15 到 30 秒/);assert.ok(document.querySelector('.skeleton')||document.querySelector('[aria-hidden]'));
 assert.equal(timers.size,1);assert.equal([...timers.values()][0].ms,5000);assert.equal(pending.length,count);
 await tick();assert.equal(pending.length,++count);await warmReply();
 await tick();assert.equal(pending.length,++count);
 await act(async()=>pending.at(-1).resolve(new Response(JSON.stringify({value:'ready'}),{status:200})));
 assert.equal(document.body.textContent,'ready');assert.equal(timers.size,0);
 await act(async()=>warmingRoot.render(React.createElement(Warming,{group:'old-warm'})));await warmReply();
 await act(async()=>warmingRoot.render(React.createElement(Warming,{group:'new-warm'})));
 assert.equal(timers.size,0);await warmReply();assert.equal(timers.size,1);
 invalidateSessionEpoch();count=pending.length;await tick();assert.equal(pending.length,count);
 await act(async()=>warmingRoot.render(React.createElement(Warming,{group:'cap'})));
 for(let attempt=0;attempt<12;attempt++){await warmReply();if(attempt<11)await tick()}
 assert.equal(document.querySelector('button').textContent,'重試');assert.equal(warmingState.loading,false);assert.equal(warmingState.error,'warming');assert.equal(timers.size,0);
 await act(async()=>warmingState.retry());
 await act(async()=>pending.at(-1).resolve(new Response(JSON.stringify({detail:'failed',warming:false}),{status:503})));
 assert.equal(timers.size,0);assert.equal(document.querySelector('button').textContent,'重試');
 await act(async()=>warmingState.retry());await warmReply();assert.equal(timers.size,1);
 await act(async()=>warmingRoot.unmount());assert.equal(timers.size,0);
}finally{globalThis.setTimeout=realSetTimeout;globalThis.clearTimeout=realClearTimeout}
console.log('Warming retries are serial, bounded and cancelled by parameters, session changes and unmount.');

const {spawnSync}=await import('node:child_process');
for(const scenario of ['assets-blank','asset-owner','progress-week','progress-label','points','progress-sentinel','progress-options']){const result=spawnSync(process.execPath,['test-reports-interactions.mjs'],{env:{...process.env,REPORT_CASE:scenario},encoding:'utf8'});assert.equal(result.status,0,result.stdout+result.stderr);process.stdout.write(result.stdout);}
