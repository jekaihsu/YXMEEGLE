import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {DataFreshness} from './src/DataFreshness';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external'});
const path=new URL('./.live-regression-bundle.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);
let mod;try{mod=await import(path.href)}finally{await fs.unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const key of ['window','document','Event','FormData'])globalThis[key]=dom.window[key];
Object.defineProperty(document,'hidden',{configurable:true,value:false});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const realTimeout=setTimeout,realClear=clearTimeout,realNow=Date.now;
let now=Date.parse('2026-10-07T02:02:23Z'),id=0;const timers=new Map();
Date.now=()=>now;
globalThis.setTimeout=(fn,ms,...args)=>ms>=15000?(timers.set(++id,{fn,ms}),id):realTimeout(fn,ms,...args);
globalThis.clearTimeout=id=>timers.delete(id)||realClear(id);
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(r=>realTimeout(r,0))});
const tick=async(ms)=>{const entry=[...timers].find(([,t])=>t.ms===ms);assert.ok(entry,`timer ${ms} exists`);timers.delete(entry[0]);await flush(entry[1].fn)};
const dataset=(status='fresh',age=12)=>({status,as_of:age===null?null:'2026-10-07T02:02:11Z',changed_at:'2026-10-07T02:02:11Z',age_seconds:age,ttl_seconds:60,fetched_at:null,last_error:null,fingerprint:null,lark:{calls:0,retries:0,duration_ms:0}});
const freshness=()=>({enabled:true,server_time:'2026-10-07T02:02:23Z',datasets:{sources:dataset(),roster:dataset(),attendance:dataset()}});
let root=createRoot(document.getElementById('root'));
const render=(data,props={})=>flush(()=>root.render(React.createElement(mod.DataFreshness,{freshness:data,refresh:()=>{},...props})));
try{
 const data=freshness();await render(data);assert.equal(document.querySelector('.data-freshness').dataset.state,'fresh');
 now+=120000;await tick(30000);
 assert.equal(document.querySelector('.data-freshness').dataset.state,'stale','M1: fresh degrades after TTL without a server request');
 assert.match(document.body.textContent,/132 秒前/,'M1: age advances with time');
 console.log('Live-read regressions passed');
}finally{await flush(()=>root.unmount());globalThis.setTimeout=realTimeout;globalThis.clearTimeout=realClear;Date.now=realNow;dom.window.close()}
