// VCC-119: one Taipei formatter; identical text in any process timezone. Runs itself once per TZ.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const zones=['America/Los_Angeles','Asia/Taipei','UTC'];
if(!process.env.TAIPEI_TZ_CHILD){
 for(const TZ of zones){const r=spawnSync(process.execPath,[new URL(import.meta.url).pathname],{env:{...process.env,TZ,TAIPEI_TZ_CHILD:'1'},stdio:'inherit'});assert.equal(r.status,0,`failed under TZ=${TZ}`)}
 console.log(`taipei-time passed under ${zones.join(', ')}`);process.exit(0);
}
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {taipeiTime,parseInstant} from './src/taipeiTime'; export {DataFreshness} from './src/DataFreshness'; export {stamp} from './src/appCommon';",resolveDir:process.cwd(),loader:'ts'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL(`./.taipei-bundle-${process.pid}.mjs`,import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let m;try{m=await import(path.href)}finally{await fs.unlink(path)}
const {taipeiTime,parseInstant,DataFreshness,stamp}=m;
const want='2026/10/13 08:54:22 (台北時間)';
for(const input of ['2026-10-13T08:54:22.133782+08:00','2026-10-13T00:54:22Z','2026-10-12T17:54:22-07:00','2026-10-13T08:54:22.133782'])assert.equal(taipeiTime(input),want,`${input} under ${process.env.TZ}`);
assert.equal(stamp('2026-10-13T08:54:22.133782+08:00'),want);
assert.equal(taipeiTime('2026-10-13'),'2026/10/13');
assert.equal(taipeiTime(null),'—');assert.equal(taipeiTime('garbage','無'),'無');
assert.equal(parseInstant('2026-10-13T08:54:22.133782+08:00'),Date.parse('2026-10-13T00:54:22.133Z'));
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const k of ['window','document','Event','FormData'])globalThis[k]=dom.window[k];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;Object.defineProperty(document,'hidden',{configurable:true,value:false});
const ds=()=>({status:'stale',as_of:'2026-10-05T17:00:00+08:00',fetched_at:'2026-10-05T17:00:01+08:00',age_seconds:637000,ttl_seconds:60,changed_at:null,fingerprint:null,last_error:null});
const fresh={enabled:true,server_time:'2026-10-13T09:00:00+08:00',datasets:{sources:ds(),roster:ds(),attendance:ds()}};
const root=createRoot(document.getElementById('root'));
globalThis.fetch=async()=>new Response('{}');
await act(async()=>{root.render(React.createElement(DataFreshness,{freshness:fresh,syncedAt:'2026-10-13T08:54:22.133782+08:00',refresh:()=>{}}))});
const text=document.querySelector('[role="status"]').textContent;
assert.ok(text.includes('讀取驗證 2026/10/05 17:00:00 (台北時間)'),text);
assert.ok(text.includes(`來源同步 ${want}`),text);
assert.ok(text.includes('資料待更新'),text);
assert.ok(document.querySelector('[role="status"]').title.includes('讀取驗證'));
await act(async()=>root.unmount());
console.log(`ok TZ=${process.env.TZ}`);
