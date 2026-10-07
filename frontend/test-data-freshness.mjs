// Render the real component with synthetic responses; fake only the 15-second poll timer.
import assert from 'node:assert/strict';
import {fakeClock} from './fake-clock-fixture.mjs';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {DataFreshness} from './src/DataFreshness'; export {liveStatus,liveRefresh,invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external'});
const path=new URL('./.freshness-test-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let module;try{module=await import(path.href)}finally{await fs.unlink(path)}
const {DataFreshness,liveStatus,liveRefresh,invalidateSessionEpoch}=module;
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const key of ['window','document','Event','FormData'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
Object.defineProperty(document,'hidden',{configurable:true,value:false});
const clock=fakeClock(dom.window);
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(r=>clock.realTimeout(r,0))});
const initial='2026-10-07T10:00:00+08:00',later='2026-10-07T10:03:00+08:00',newest='2026-10-07T10:04:00+08:00';
const dataset=(status='fresh',changed_at=initial)=>({status,as_of:'2026-10-07T10:02:11+08:00',fetched_at:'2026-10-07T10:02:12+08:00',changed_at,age_seconds:12,ttl_seconds:60,fingerprint:'sha256:synthetic',last_error:null,lark:{calls:1,retries:0,duration_ms:20}});
const freshness=(status='fresh',changed=initial)=>({enabled:true,server_time:'2026-10-07T10:02:23+08:00',datasets:{sources:dataset(status,changed),roster:dataset(),attendance:dataset()}});
let response=freshness();const requests=[];
const fetchMock=async(url,init)=>{requests.push({url,init});return new Response(JSON.stringify({freshness:response}),{status:200})};
globalThis.fetch=fetchMock;
let root=createRoot(document.getElementById('root')),refreshes=0;
const render=(data,props={})=>flush(()=>root.render(React.createElement(DataFreshness,{freshness:data,refresh:()=>{refreshes++},...props})));
const text=()=>document.querySelector('[role="status"]').textContent;
let checks=0;const ok=(condition,message)=>{assert.ok(condition,message);checks++};
try{
  for(const [state,label] of Object.entries({fresh:'10:02:11',stale:'資料待更新',refreshing:'更新中',error:'Lark 暫時無法讀取',blocked:'Lark 權限不足（1254302）',unconfigured:'尚未設定',never:'正在讀取 Lark 來源…'})){
    const data=freshness(state);for(const d of Object.values(data.datasets))d.status=state;
    await render(data);
    ok(document.querySelector('.data-freshness').dataset.state===state&&text().includes(label),`${state} renders`);
    ok(document.querySelector('[role="status"]').getAttribute('aria-live')==='polite',`${state} is accessible`);
    const before=text();await flush(()=>clock.advance(600000));
    ok(text()===before&&requests.length===0&&clock.intervals===0&&clock.timers.size===0,`${state} stays static without reads for ten minutes`);
  }
  await render({...freshness('refreshing'),enabled:false},{demo:true});
  ok(text()==='示範資料'&&!document.querySelector('button'),'demo has no refresh control');
  await render(freshness('refreshing'));response=freshness('fresh',newest);
  await flush(()=>document.querySelector('button').click());
  ok(requests.at(-1).url==='/api/live/refresh'&&refreshes===1,'manual refresh reads live data and workspace once');
  assert.deepEqual(JSON.parse(requests.at(-1).init.body),{datasets:['sources','attendance'],wait:false,force:false});checks++;
  await render(freshness('fresh',newest));await render(freshness('fresh',later));
  ok(refreshes===1,'newer changed_at renders without another workspace read');
  for(const props of [{mutationActive:true},{dirtyDraft:true}]){
    await render(freshness(),props);const before=requests.length;await flush(()=>document.querySelector('button').click());
    ok(requests.length===before,'manual refresh respects mutation and draft guards');
  }
  await render(freshness());globalThis.fetch=async()=>{throw Error('synthetic failure')};
  await flush(()=>document.querySelector('button').click());ok(text().includes('暫時無法讀取'),'manual failure is visible');
  for(const staleSession of [false,true]){
    await flush(()=>root.unmount());root=createRoot(document.getElementById('root'));let resolveOld;
    globalThis.fetch=()=>new Promise(resolve=>{resolveOld=resolve});await render(freshness('refreshing'));
    await flush(()=>document.querySelector('button').click());
    if(staleSession)invalidateSessionEpoch();else await flush(()=>root.unmount());
    await flush(()=>resolveOld(new Response(JSON.stringify({freshness:freshness('fresh',newest)}))));
    ok(refreshes===1,'late manual response cannot reload unmounted or previous-session workspace');
    if(staleSession)ok(document.querySelector('.data-freshness').dataset.state==='refreshing','previous-session response discarded');
  }
  globalThis.fetch=fetchMock;await liveStatus();ok(requests.at(-1).url==='/api/live/status','explicit status helper remains available');
  await liveRefresh(['sources'],true);assert.deepEqual(JSON.parse(requests.at(-1).init.body),{datasets:['sources'],wait:true,force:false});checks++;
  console.log(`Data freshness: ${checks} checks passed`);
}finally{await flush(()=>root.unmount());clock.restore();dom.window.close()}
