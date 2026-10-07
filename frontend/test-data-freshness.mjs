// Render the real component with synthetic responses; fake only the 15-second poll timer.
import assert from 'node:assert/strict';
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
const realTimeout=globalThis.setTimeout,realClear=globalThis.clearTimeout;
const timers=new Map();let timerId=0;
globalThis.setTimeout=(fn,ms,...args)=>fn.name==='poll'?(timers.set(++timerId,fn),timerId):realTimeout(fn,ms,...args);
globalThis.clearTimeout=id=>{if(timers.has(id))timers.delete(id);else realClear(id)};
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(r=>realTimeout(r,0))});
const tick=()=>flush(async()=>{assert.equal(timers.size,1);const [id,fn]=timers.entries().next().value;timers.delete(id);await fn()});
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
  for(const [state,label] of Object.entries({fresh:'10:02:11（12 秒前）',stale:'資料待更新',refreshing:'更新中…',error:'Lark 暫時無法讀取',blocked:'Lark 權限不足（1254302）',unconfigured:'尚未設定',never:'正在讀取 Lark 來源…'})){
    const data=freshness(state);for(const d of Object.values(data.datasets))d.status=state;
    await render(data);
    ok(document.querySelector('.data-freshness').dataset.state===state&&text().includes(label),`${state} renders`);
    ok(document.querySelector('[role="status"]').getAttribute('aria-live')==='polite',`${state} is accessible`);
    ok(timers.size===(state==='refreshing'?1:0),`polling only while refreshing, not ${state}`);
  }
  ok(requests.length===0,'rendering does not read Lark');
  ok(document.querySelector('[role="status"]').title.includes('名冊')&&document.querySelector('[role="status"]').title.includes('TTL 60 秒'),'tooltip gives all dataset times and TTL');
  await render({...freshness('refreshing'),enabled:false},{demo:true});
  ok(text()==='示範資料'&&timers.size===0&&!document.querySelector('button'),'demo has no timer or refresh control');
  await render({...freshness(),enabled:false});ok(text()==='尚未設定','disabled production is unconfigured');
  await render(freshness('refreshing'));response=freshness();await tick();
  ok(requests.at(-1).url==='/api/live/status'&&timers.size===0,'poll stops on completion');
  ok(refreshes===0,'as_of alone does not refresh workspace');
  await render(freshness('fresh',later),{mutationActive:true});ok(refreshes===0,'mutation suppresses change');
  await render(freshness('fresh',later),{dirtyDraft:true});ok(refreshes===0,'dirty draft suppresses change');
  await render(freshness('fresh',later));ok(refreshes===1,'pending change refreshes once after guards clear');
  await render(freshness('fresh',later));await render(freshness());ok(refreshes===1,'equal or older changed_at never refreshes');
  await render(freshness('refreshing',later));response=freshness('fresh',newest);await tick();
  ok(refreshes===2&&timers.size===0,'poll completion refreshes changed data once');
  const roster=freshness('fresh',newest);roster.datasets.roster.status='refreshing';await render(roster);
  ok(timers.size===1,'any refreshing dataset starts polling');
  response=freshness('fresh',newest);response.datasets.roster.changed_at=newest;await tick();ok(refreshes===3,'roster changed_at triggers refresh');
  response=freshness('refreshing',newest);await flush(()=>document.querySelector('button').click());
  ok(requests.at(-1).url==='/api/live/refresh'&&timers.size===1,'manual refresh starts polling');
  assert.deepEqual(JSON.parse(requests.at(-1).init.body),{datasets:['sources','attendance'],wait:false,force:false});checks++;
  globalThis.fetch=async()=>{throw new Error('synthetic network failure')};await tick();
  ok(text().includes('資料狀態暫時無法讀取')&&timers.size===1,'failed status read reports error and keeps bounded polling');
  await flush(()=>root.unmount());ok(timers.size===0,'unmount cancels polling');
  root=createRoot(document.getElementById('root'));let resolveOld;
  globalThis.fetch=()=>new Promise(resolve=>{resolveOld=resolve});await render(freshness('refreshing'));
  const [oldId,oldPoll]=timers.entries().next().value;timers.delete(oldId);let oldPending;
  await flush(()=>{oldPending=oldPoll()});ok(timers.size===0,'slow poll never overlaps another status request');
  await render(freshness());
  await flush(async()=>{resolveOld(new Response(JSON.stringify({freshness:freshness('fresh',newest)})));await oldPending});
  ok(refreshes===3&&timers.size===0,'new workspace freshness invalidates older poll response');
  await flush(()=>root.unmount());
  for(const staleSession of [false,true]){
    root=createRoot(document.getElementById('root'));let resolvePoll;
    globalThis.fetch=()=>new Promise(resolve=>{resolvePoll=resolve});await render(freshness('refreshing'));
    const [id,poll]=timers.entries().next().value;timers.delete(id);let pending;
    await flush(()=>{pending=poll()});
    if(staleSession)invalidateSessionEpoch();else await flush(()=>root.unmount());
    await flush(async()=>{resolvePoll(new Response(JSON.stringify({freshness:freshness('fresh',newest)})));await pending});
    ok(refreshes===3,'late response cannot refresh unmounted or previous-session workspace');
    if(staleSession){ok(document.querySelector('.data-freshness').dataset.state==='refreshing','previous-session status is discarded');await flush(()=>root.unmount())}
    ok(timers.size===0,'no polling after unmount');
  }
  globalThis.fetch=fetchMock;await liveStatus();ok(requests.at(-1).url==='/api/live/status','status helper contract URL');
  await liveRefresh(['sources'],true);assert.deepEqual(JSON.parse(requests.at(-1).init.body),{datasets:['sources'],wait:true,force:false});checks++;
  console.log(`Data freshness: ${checks} checks passed`);
}finally{
  await flush(()=>root.unmount());globalThis.setTimeout=realTimeout;globalThis.clearTimeout=realClear;dom.window.close();
}
