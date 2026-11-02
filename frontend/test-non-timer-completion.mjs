import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {fakeClock} from './fake-clock-fixture.mjs';
import {workspace,a} from './session-epoch-fixture.mjs';
const bundle=await build({stdin:{contents:"export {useDispatchBoardRead} from './src/dispatchBoardRead';export {Projects} from './src/ProjectsList';export {refreshSources} from './src/refreshSources';export {default as Progress} from './src/reports/ProgressTab';export {mockReport} from './src/reports/mock';export {invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const file=new URL('./.non-timer.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=reports&tab=progress'});
for(const key of ['window','document','location','localStorage','Event','HTMLElement','Element'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const clock=fakeClock(window),root=createRoot(document.getElementById('root'));
const flush=fn=>act(async()=>{await fn?.();await new Promise(r=>clock.realTimeout(r,0))});
const mount=Component=>flush(()=>root.render(Component));
const click=text=>flush(()=>{const button=[...document.querySelectorAll('button')].find(b=>b.textContent===text);assert.ok(button,text);button.click()});
const {variants}=JSON.parse(await fs.readFile('fixtures/dispatchBoardSample.json','utf8'));
let calls=[],read;
const json=(body,status=200)=>new Response(JSON.stringify(body),{status});
function Board(){read=m.useDispatchBoardRead('2026-07-27');return React.createElement('button',{onClick:read.reload},'重試')}
const idle=async(label)=>{const count=calls.length;await flush(()=>clock.advance(600000));assert.equal(calls.length,count,`${label}: no requests after ten minutes`)};
try{
 for(const state of ['partial','stale','offline']){
  await mount(null);const board=structuredClone(variants.loaded);board.window={from:'2026-07-27',to:'2026-08-02',tz:'Asia/Taipei'};board.source.quality.states=[state==='offline'?'read_failed':state];board.source.quality.reason='refreshing_last_good_snapshot';board.source.joins={projects:'unavailable'};
  globalThis.fetch=async(url)=>{calls.push(url);return state==='offline'?json({detail:'offline'},503):json(board)};
  await mount(React.createElement(Board));await idle(`dispatch ${state}`);const count=calls.length;await click('重試');assert.equal(calls.length,count+1);
 }
 await mount(null);
 const c={w:{...workspace,scope:'shell'},s:{user:a,mode:'lark',workspace_id:'test'},route:{view:'projects'},refresh:async()=>{},go(){},run(){}};
 globalThis.fetch=async(url)=>{calls.push(url);return json({items:[],total:0,node_status_degraded:true,as_of:'2026-10-01',basis:'persisted_workspace'})};
 await mount(React.createElement(m.Projects,{c}));await idle('projects degraded');let count=calls.length;await click('重新載入');assert.equal(calls.length,count+1);
 for(const status of [202,503]){
  globalThis.fetch=async(url,init)=>{calls.push(url);return init?.method==='POST'?json(status===202?{status:'refreshing'}:{detail:'offline'},status):json({items:[],total:0,node_status_degraded:true,as_of:'2026-10-01',basis:'persisted_workspace'})};
  const count=calls.length;await click('重新同步 Lark');assert.equal(calls.length,count+1);await idle(`projects sync ${status}`);
  assert.match(document.querySelector('.pl-sync-status').textContent,status===202?/按同步按鈕/:/offline/);
 }
 await mount(null);
 for(const status of [202,200,503]){
  const source={status:status===200?'fresh':'refreshing',fingerprint:'unchanged',ttl_seconds:60,age_seconds:0};
  globalThis.fetch=async(url)=>{calls.push(url);return json(status===503?{detail:'offline'}:{freshness:{enabled:true,server_time:'2026-11-02T00:00:00Z',datasets:{sources:source,roster:source,attendance:source}}},status)};
  const count=calls.length;
  if(status===200){assert.equal((await m.refreshSources()).status,'ready');assert.equal((await m.refreshSources()).status,'ready')}
  else await assert.rejects(m.refreshSources(),status===202?/按同步按鈕/:/offline/);
  await idle(`sources ${status}`);assert.equal(calls.length,count+(status===200?2:1));
 }
 for(const cancel of ['caller','session']){
  let signal;globalThis.fetch=(_url,init)=>new Promise((_resolve,reject)=>{signal=init.signal;signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')))});
  const controller=new AbortController(),work=m.refreshSources('sources',undefined,controller.signal);const rejected=assert.rejects(work,/取消|逾時/);
  if(cancel==='caller')controller.abort();else m.invalidateSessionEpoch();await rejected;assert.equal(signal.aborted,true);
 }
 for(const status of [202,200]){
  globalThis.fetch=async(url,init)=>{calls.push(url);if(init.method==='POST')return json({},status);const data=m.mockReport('progress',new URL(url,'http://localhost').searchParams);data.meta.can_refresh=true;return json(data)};
  await mount(React.createElement(m.Progress,{key:status}));
  const refresh=[...document.querySelectorAll('button')].find(b=>b.textContent==='重新整理資料');
  assert.ok(refresh);const before=calls.length;await flush(()=>refresh.click());
  assert.equal(calls.length,before+(status===202?1:2));await idle(`report refresh ${status}`);
  count=calls.length;await click('查看更新結果');assert.equal(calls.length,count+1);await mount(null);
 }
 console.log('Non-timer completion: dispatch partial/warming/offline, projects degraded, sources 202/offline/unchanged, report 202/completed: ten minutes +0; explicit button +1; source request aborts.');
}finally{await flush(()=>root.unmount());clock.restore();dom.window.close()}
