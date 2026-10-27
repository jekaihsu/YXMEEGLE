import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {workspace,a} from './session-epoch-fixture.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const k of ['window','document','location','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','Event','StorageEvent'])globalThis[k]=dom.window[k];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const bundle=await build({stdin:{contents:"export {Projects} from './src/ProjectsList';export {RecoveryPage} from './src/RecoveryPage';export {AttendanceWorkSchedules} from './src/AttendanceWorkSchedules';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.legacy-sync-test.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const reply=(body,status=200)=>new Response(JSON.stringify(body),{status});
const freshness=(dataset,status)=>({enabled:true,server_time:new Date().toISOString(),datasets:Object.fromEntries(['sources','roster','attendance'].map(k=>[k,{status:k===dataset?status:'fresh',ttl_seconds:60,age_seconds:0,last_error:status==='error'?'測試讀取失敗':null}]))});
for(const [component,dataset,label] of [['Projects','sources','重新同步 Lark'],['RecoveryPage','roster','重新同步公司名冊'],['AttendanceWorkSchedules','attendance','同步正常班表']])for(const outcome of ['fresh','error'])test(`${component} waits for 202 then ${outcome}`,async()=>{
 let release,reads=0;const calls=[];
 globalThis.fetch=async url=>{calls.push(url);if(url==='/api/live/status'){await new Promise(r=>release=r);return reply({freshness:freshness(dataset,outcome)})}return reply({freshness:freshness(dataset,'refreshing')},202)};
 const refresh=async()=>{reads++};const s={mode:'lark',user:a,workspace_id:'company'};
 const c={s,w:{...workspace,work_schedules:[]},route:{view:'projects'},go(){},refresh,run(){},reloadVersion:0};
 const root=createRoot(document.getElementById('root'));
 try{
  await act(async()=>root.render(React.createElement(ui[component],component==='RecoveryPage'?{s,refresh,logout:async()=>{}}:{c})));
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent===label).click());
  assert.equal(reads,0,'pending sync must not reload or claim completion');
  assert.equal(typeof release,'function','pending sync starts status polling');
  await act(async()=>release());
  assert.equal(reads,outcome==='fresh'?1:0);
  if(outcome==='error')assert.match(document.body.textContent,/測試讀取失敗/);
 }finally{await act(()=>root.unmount())}
});
