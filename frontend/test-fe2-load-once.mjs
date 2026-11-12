import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink,readFile} from 'node:fs/promises';
import React,{act} from 'react';import {createRoot} from 'react-dom/client';import {JSDOM} from 'jsdom';
const mode=process.argv[2]??'dispatch';
const out=await build({stdin:{contents:`export {invalidateSessionEpoch} from './src/api';export {mockReport} from './src/reports/mock';export {useDispatchBoardRead} from './src/dispatchBoardRead';export {HomeDataProvider} from './src/useHomePanels';export {useReport} from './src/reports/useReport';export {default as ProgressTab} from './src/reports/ProgressTab';`,resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const path=new URL('./.fe2-test.mjs',import.meta.url);await writeFile(path,out.outputFiles[0].text);let m;try{m=await import(path.href)}finally{await unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=reports&tab=progress&status=X'});
for(const name of ['window','document','location','localStorage','HTMLElement','Event'])globalThis[name]=dom.window[name];globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const calls=[];globalThis.fetch=(url,init)=>new Promise(resolve=>calls.push({url,init,resolve}));
const flush=fn=>act(async()=>{fn?.();await new Promise(setImmediate)});const root=createRoot(document.getElementById('root'));let read;
const render=el=>flush(()=>root.render(el));const reply=(i,body)=>flush(()=>calls[i].resolve(new Response(JSON.stringify(body))));
try{
if(mode==='dispatch'){
 const {variants}=JSON.parse(await readFile('fixtures/dispatchBoardSample.json','utf8'));const c={s:{user:{id:'fixture'},workspace_id:'test'},w:{version:0}};
 function Card(){read=m.useDispatchBoardRead('2026-07-27');return null}const page=v=>React.createElement(m.HomeDataProvider,{c},v?React.createElement(Card):null);
 await render(page(true));assert.equal(calls.length,1);await reply(0,variants.loaded);await render(page(false));await render(page(true));assert.equal(calls.length,1,'one board GET after real unmount/remount');await flush(()=>read.reload());assert.equal(calls.length,2,'refresh exactly one batch');await reply(1,variants.loaded);await render(page(false));await render(page(true));assert.equal(calls.length,2);console.log('dispatch initial/remount/refresh/remount: 1/1/2/2');
 await flush(()=>read.reload());assert.equal(calls.length,3);await flush(()=>calls[2].resolve(new Response(JSON.stringify({detail:'offline'}),{status:503})));assert.equal(read.data.slots.length,variants.loaded.slots.length);assert.equal(read.error,'offline');
 await flush(()=>read.reload());assert.equal(calls.length,4);await flush(()=>read.reload());assert.equal(calls.length,5);assert.equal(calls[3].init.signal.aborted,true);await reply(4,variants.loaded);await reply(3,{...variants.loaded,slots:[]});assert.equal(read.data.slots.length,variants.loaded.slots.length,'late response cannot overwrite refresh');
 await flush(()=>m.invalidateSessionEpoch());assert.equal(calls.length,6);assert.equal(read.data,undefined);await reply(5,variants.loaded);
 await flush(()=>read.reload());await reply(6,{...variants.loaded,window:{from:'2020-01-01',to:'2020-01-07',tz:'Asia/Taipei'}});assert.equal(read.error,'回應週次與目前查詢不符，請重試。');assert.equal(read.data.slots.length,variants.loaded.slots.length);
 await flush(()=>read.reload());await flush(()=>calls[7].resolve(new Response(JSON.stringify({detail:'private'}),{status:403})));assert.deepEqual(read.data.source.quality.states,['forbidden']);await render(page(false));await render(page(true));assert.equal(calls.length,8,'denied result is pinned until explicit action');
 await flush(()=>read.reload());await render(null);assert.equal(calls[8].init.signal.aborted,true,'page unmount aborts transport');await reply(8,variants.loaded);
 await render(page(true));assert.equal(calls.length,10,'new page open has a new read generation');assert.equal(read.data,undefined);await reply(9,variants.loaded);

}else if(mode==='ttl'){
 function Probe({group}){read=m.useReport('progress',{group});return null}
 await render(React.createElement(Probe,{group:'A'}));await reply(0,{value:'A'});await render(React.createElement(Probe,{group:'B'}));await reply(1,{value:'B'});const now=Date.now;Date.now=()=>now()+120000;try{await render(React.createElement(Probe,{group:'A'}));assert.equal(calls.length,2,'120 seconds does not expire an open query')}finally{Date.now=now}
 console.log('TTL counts A/B/A after 120s: 1/2/2');
}else if(mode==='absent'){
 await render(React.createElement(m.ProgressTab));const d=m.mockReport('progress',new URLSearchParams());d.options.status=[{status:'執行中',count:7}];await reply(0,d);assert.equal(document.querySelectorAll('.reports-status-filters button')[2].textContent,'X —');assert.equal(document.querySelector('.reports-status-filters button').textContent,'全部 7');console.log('loaded options: 全部 7 / missing X —');
}else if(mode==='reports'){
 function Probe({group}){read=m.useReport('progress',{group});return null}await render(React.createElement(Probe,{group:'A'}));await reply(0,{value:'A'});await flush(()=>read.retry());await reply(1,{value:'A2'});await render(React.createElement(Probe,{group:'B'}));assert.equal(calls[2].init.headers['X-YX-Fetch-Intent'],'user_query_change');await reply(2,{value:'B'});const now=Date.now;Date.now=()=>now()+120000;try{await render(React.createElement(Probe,{group:'A'}));assert.equal(calls.length,3,'no TTL read after 120 seconds')}finally{Date.now=now}assert.equal(read.data.value,'A2');console.log('reports initial/retry/query/return after 120s: 1/2/3/3');
}else{await render(React.createElement(m.ProgressTab));assert.equal(document.querySelector('.reports-status-filters button').textContent,'全部 —');assert.equal(document.querySelectorAll('.reports-status-filters button')[1].textContent,'X —');console.log('全部 — / X —')}
}finally{await flush(()=>root.unmount());dom.window.close()}
