import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {fakeClock} from './fake-clock-fixture.mjs';
import {workspace,a} from './session-epoch-fixture.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const k of ['window','document','location','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','Event','StorageEvent'])globalThis[k]=dom.window[k];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const bundle=await build({stdin:{contents:"export {Projects} from './src/ProjectsList';export {RecoveryPage} from './src/RecoveryPage';export {AttendanceWorkSchedules} from './src/AttendanceWorkSchedules';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.legacy-sync-test.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const reply=(body,status=200)=>new Response(JSON.stringify(body),{status});
const freshness=(dataset,status)=>({enabled:true,server_time:new Date().toISOString(),datasets:Object.fromEntries(['sources','roster','attendance'].map(k=>[k,{status:k===dataset?status:'fresh',ttl_seconds:60,age_seconds:0,last_error:status==='error'?'測試讀取失敗':null}]))});
for(const [component,dataset,label] of [['Projects','sources','重新同步 Lark'],['RecoveryPage','roster','重新同步公司名冊'],['AttendanceWorkSchedules','attendance','同步正常班表']])for(const outcome of ['fresh','error'])test(`${component} waits for 202 then ${outcome}`,async()=>{
 const clock=fakeClock(window);let reads=0;let completed=false;const calls=[],requests=[];
 globalThis.fetch=async (url,init)=>{requests.push(url);if(init?.method!=='POST'){assert.notEqual(url,'/api/live/status','sync never polls status');return reply({})}calls.push(url);assert.notEqual(url,'/api/live/status','sync never polls status');return completed?reply(outcome==='fresh'?{freshness:freshness(dataset,outcome)}:{detail:'測試讀取失敗'},outcome==='fresh'?200:502):reply({freshness:freshness(dataset,'refreshing')},202)};
 const refresh=async()=>{reads++};const s={mode:'lark',user:a,workspace_id:'company'};
 const c={s,w:{...workspace,work_schedules:[]},route:{view:'projects'},go(){},refresh,run(){},reloadVersion:0};
 const root=createRoot(document.getElementById('root'));
 try{
  await act(async()=>root.render(React.createElement(ui[component],component==='RecoveryPage'?{s,refresh,logout:async()=>{}}:{c})));
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent===label).click());
  assert.equal(reads,0,'pending sync must not reload or claim completion');
  assert.equal(calls.length,1,'202 performs only the user sync request');
  assert.equal((component==='Projects'?document.querySelector('.pl-sync-status'):component==='RecoveryPage'?document.querySelector('[role=alert]'):[...document.querySelectorAll('[role=status]')].find(e=>e.textContent==='資料更新結果尚未確認，請按同步按鈕重試。'))?.textContent.includes('資料更新結果尚未確認，請按同步按鈕重試。'),true);
  const before=requests.length;await act(async()=>clock.advance(600000));assert.equal(requests.length,before,'ten minutes starts no passive read');assert.equal(reads,0);
  completed=true;await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent===label).click());assert.equal(calls.length,2,'explicit sync retry performs exactly one request');
  assert.equal(reads,outcome==='fresh'?1:0);
  if(outcome==='error')assert.match(document.body.textContent,/測試讀取失敗/);
 }finally{await act(()=>root.unmount());clock.restore()}
});
