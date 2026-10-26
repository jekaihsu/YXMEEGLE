import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const k of ['window','document','location','HTMLElement'])globalThis[k]=dom.window[k];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const bundle=await build({stdin:{contents:"export {refreshSources} from './src/refreshSources';export {useProjectProgress} from './src/useProjectProgress';export {SourceHealthPage} from './src/IntegratedPages';export {invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.refresh-round2.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const fixture=JSON.parse(await fs.readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
const reply=(body,status=200)=>new Response(JSON.stringify(body),{status});
const freshness=status=>({enabled:true,server_time:'2026-10-26T10:00:00Z',datasets:Object.fromEntries(['sources','roster','attendance'].map(k=>[k,{status:k==='sources'?status:'fresh',age_seconds:0,ttl_seconds:60}]))});
let root,read;
afterEach(async()=>{if(root)await act(()=>root.unmount());root=null;ui.invalidateSessionEpoch()});
function Probe(){read=ui.useProjectProgress(fixture.project_id);return React.createElement('div',null,read.state.kind)}
const mount=async element=>{root=createRoot(document.getElementById('root'));await act(async()=>root.render(element))};
const flush=async()=>act(async()=>{await new Promise(r=>setTimeout(r,10))});
test('source refresh accepts 202, polls status and finishes fresh',async()=>{
 const calls=[];globalThis.fetch=async(url,init)=>{calls.push([url,init?.method??'GET']);return reply({freshness:freshness(url.endsWith('/refresh')?'refreshing':'fresh')},url.endsWith('/refresh')?202:200)};
 await ui.refreshSources();assert.deepEqual(calls,[['/api/live/refresh','POST'],['/api/live/status','GET']]);
});
test('source refresh preserves the server failure reason',async()=>{
 globalThis.fetch=async()=>reply({detail:'來源同步操作者已無權限'},403);
 await assert.rejects(ui.refreshSources(),{message:'來源同步操作者已無權限'});
});
test('privileged engineering refresh posts then rereads progress',async()=>{
 const data=structuredClone(fixture);Object.assign(data.sources,{can_refresh_sources:true,source_status:'stale',source_synced_at:'2026-10-26T09:00:00Z'});const calls=[];
 globalThis.fetch=async(url,init)=>{calls.push([url,init?.method??'GET']);if(url.endsWith('/refresh')){data.sources.source_status='ready';return reply({freshness:freshness('fresh')})}return reply(data)};
 await mount(React.createElement(Probe));await act(async()=>read.retry());await flush();
 assert.deepEqual(calls.map(c=>c[1]),['GET','POST','GET']);assert.equal(read.state.kind,'ready');assert.equal(read.state.data.sources.source_status,'ready');
});
test('limited engineering viewer cannot trigger refresh',async()=>{
 const data=structuredClone(fixture);data.sources.can_refresh_sources=false;let calls=0;globalThis.fetch=async()=>{calls++;return reply(data)};
 await mount(React.createElement(Probe));await act(async()=>read.retry());await flush();assert.equal(calls,1);assert.equal(read.canRefresh,false);
});
test('engineering refresh that stays stale fails with last good time',async()=>{
 const data=structuredClone(fixture);Object.assign(data.sources,{can_refresh_sources:true,source_status:'stale',source_synced_at:'2026-10-26T09:00:00Z'});
 globalThis.fetch=async url=>reply(url.endsWith('/refresh')?{freshness:freshness('fresh')}:data);
 await mount(React.createElement(Probe));await act(async()=>read.retry());await flush();assert.equal(read.state.kind,'error');assert.equal(read.state.message,'來源仍待更新，請重試');assert.equal(read.state.lastGoodAt,'2026-10-26T09:00:00Z');
});
