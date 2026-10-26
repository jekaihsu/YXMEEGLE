import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const k of ['window','document','location','HTMLElement','Event'])globalThis[k]=dom.window[k];
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
const sourceBody=allowed=>({can_refresh:allowed,refresh_reason:allowed?null:'需由有權限的 PM 或主管更新',page_state:{states:['stale'],count:null},sources:[{key:'source-one',name:'測試來源',authorized:true,read_authorized:allowed,retry_handle:allowed?{dataset:'sources'}:null,data_state:{states:['stale'],count:null},last_success:'2026-10-26T09:00:00Z'}]});
const sourceContext=role=>({s:{user:{id:role,role}},w:{version:1},route:{view:'sources'},go(){}});
test('limited source page shows permission reason and no retry',async()=>{
 globalThis.fetch=async url=>reply(url==='/api/health'?{}:sourceBody(false));await mount(React.createElement(ui.SourceHealthPage,{c:sourceContext('member')}));await flush();
 assert.equal([...document.querySelectorAll('button')].some(b=>b.textContent==='重試'),false);assert.equal(document.body.textContent.includes('需由有權限的 PM 或主管更新'),true);assert.equal(document.body.textContent.includes('2026/10/26 17:00:00'),true);
});
test('privileged source page polls accepted work then reloads health',async()=>{
 const calls=[];globalThis.fetch=async(url,init)=>{calls.push(url);if(url==='/api/live/refresh')return reply({freshness:freshness('refreshing')},202);if(url==='/api/live/status')return reply({freshness:freshness('fresh')});return reply(url==='/api/health'?{}:sourceBody(true))};
 await mount(React.createElement(ui.SourceHealthPage,{c:sourceContext('manager')}));await flush();await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='重試').click());await flush();
 assert.deepEqual(calls.filter(x=>x!=='/api/health'),['/api/source-health','/api/live/refresh','/api/live/status','/api/source-health']);assert.equal(document.querySelector('[role="alert"]'),null);
});
test('source page displays server rejection and retains last success',async()=>{
 globalThis.fetch=async url=>url==='/api/live/refresh'?reply({detail:'來源同步操作者已無權限'},403):reply(url==='/api/health'?{}:sourceBody(true));
 await mount(React.createElement(ui.SourceHealthPage,{c:sourceContext('manager')}));await flush();await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='重試').click());await flush();
 assert.equal(document.querySelector('[role="alert"]').textContent,'來源同步操作者已無權限');assert.equal(document.body.textContent.includes('2026/10/26 17:00:00'),true);
});
test('a refresh is bounded at ninety seconds and reports pending explicitly',async()=>{
 const real=globalThis.setTimeout;const delays=[];
 globalThis.setTimeout=(fn,ms,...args)=>{delays.push(ms);return real(fn,ms===90000?0:ms,...args)};
 globalThis.fetch=async(url,init)=>new Promise((resolve,reject)=>init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true}));
 try{await assert.rejects(ui.refreshSources(),{message:'資料仍在更新，請稍後重試'});assert.equal(delays.includes(90000),true)}finally{globalThis.setTimeout=real}
});
test('stale readback without a timestamp retains the previous success time',async()=>{
 const data=structuredClone(fixture);Object.assign(data.sources,{can_refresh_sources:true,source_status:'stale',source_synced_at:'2026-10-26T09:00:00Z'});
 globalThis.fetch=async url=>{if(url.endsWith('/refresh')){data.sources.source_synced_at=null;return reply({freshness:freshness('fresh')})}return reply(data)};
 await mount(React.createElement(Probe));await act(async()=>read.retry());await flush();assert.equal(read.state.kind,'error');assert.equal(read.state.lastGoodAt,'2026-10-26T09:00:00Z');
});
test('polling failure uses a short Chinese reason',async()=>{
 globalThis.fetch=async url=>{const data=freshness(url.endsWith('/refresh')?'refreshing':'error');data.datasets.sources.last_error='Lark refresh failed';return reply({freshness:data},url.endsWith('/refresh')?202:200)};
 await assert.rejects(ui.refreshSources(),{message:'Lark 讀取失敗，請重試'});
});
test('initial permission denial never grants refresh or retry',async()=>{
 let calls=0;globalThis.fetch=async()=>{calls++;return reply({detail:'denied'},403)};
 await mount(React.createElement(Probe));assert.equal(read.canRefresh,false);assert.equal(read.canRetryRead,false);
 await act(async()=>read.retry());assert.equal(calls,1);
});
test('initial network failure offers only a progress reread',async()=>{
 const calls=[];globalThis.fetch=async url=>{calls.push(url);if(calls.length===1)throw new TypeError('network');return reply(fixture)};
 await mount(React.createElement(Probe));assert.equal(read.canRefresh,false);assert.equal(read.canRetryRead,true);
 await act(async()=>read.retry());assert.equal(read.state.kind,'ready');assert.equal(calls.some(url=>url==='/api/live/refresh'),false);
});
test('cached privilege is preserved after a failed progress read',async()=>{
 const data=structuredClone(fixture);data.sources.can_refresh_sources=true;
 globalThis.fetch=async()=>reply(data);await mount(React.createElement(Probe));
 globalThis.fetch=async()=>{throw new TypeError('network')};await act(async()=>read.reload());
 assert.equal(read.state.kind,'error');assert.equal(read.canRefresh,true);
});
test('unmount cancels a pending engineering poll before another status read',async t=>{
 const data=structuredClone(fixture);data.sources.can_refresh_sources=true;let statuses=0;
 globalThis.fetch=async url=>{if(url==='/api/live/refresh')return reply({freshness:freshness('refreshing')},202);if(url==='/api/live/status'){statuses++;return reply({freshness:freshness('refreshing')})}return reply(data)};
 await mount(React.createElement(Probe));t.mock.timers.enable({apis:['setTimeout']});
 await act(async()=>read.retry());assert.equal(statuses,1);
 await act(()=>root.unmount());root=null;
 await act(async()=>t.mock.timers.tick(2000));assert.equal(statuses,1);
 t.mock.timers.reset();
});
test('session epoch change cancels pending engineering polling',async t=>{
 const data=structuredClone(fixture);data.sources.can_refresh_sources=true;let statuses=0;
 globalThis.fetch=async url=>{if(url==='/api/live/refresh')return reply({freshness:freshness('refreshing')},202);if(url==='/api/live/status'){statuses++;return reply({freshness:freshness('refreshing')})}return reply(data)};
 await mount(React.createElement(Probe));t.mock.timers.enable({apis:['setTimeout']});
 await act(async()=>read.retry());assert.equal(statuses,1);
 await act(async()=>ui.invalidateSessionEpoch());await act(async()=>t.mock.timers.tick(2000));assert.equal(statuses,1);
 t.mock.timers.reset();
});
test('strict effect remount does not join an aborted progress request',async()=>{
 globalThis.fetch=async()=>reply(fixture);
 await mount(React.createElement(React.StrictMode,null,React.createElement(Probe)));
 assert.equal(read.state.kind,'ready');
});
test('project change aborts the old poller before another project refresh',async t=>{
 let statuses=0;const signals=[];
 globalThis.fetch=async(url,init)=>{if(url==='/api/live/refresh'){signals.push(init.signal);return reply({freshness:freshness('refreshing')},202)}if(url==='/api/live/status'){statuses++;return reply({freshness:freshness('refreshing')})}const data=structuredClone(fixture);data.project_id=url.split('/')[3];data.sources.can_refresh_sources=true;return reply(data)};
 function Switch({id}){read=ui.useProjectProgress(id);return React.createElement('p',null,read.state.kind)}
 await mount(React.createElement(Switch,{id:'old'}));t.mock.timers.enable({apis:['setTimeout']});await act(async()=>read.retry());assert.equal(statuses,1);
 await act(async()=>root.render(React.createElement(Switch,{id:'new'})));assert.equal(signals[0].aborted,true);
 await act(async()=>t.mock.timers.tick(2000));assert.equal(statuses,1);
 await act(async()=>read.retry());assert.equal(statuses,2);assert.equal(signals.length,2);
 t.mock.timers.reset();
});
test('engineering deadline includes progress readback and keeps last good time',async t=>{
 const data=structuredClone(fixture);Object.assign(data.sources,{can_refresh_sources:true,source_synced_at:'2026-10-26T09:00:00Z'});
 globalThis.fetch=async()=>reply(data);await mount(React.createElement(Probe));
 t.mock.timers.enable({apis:['setTimeout','Date']});
 globalThis.fetch=async url=>url==='/api/live/refresh'?new Promise(resolve=>setTimeout(()=>resolve(reply({freshness:freshness('fresh')})),80000)):new Promise(()=>{});
 await act(async()=>read.retry());await act(async()=>t.mock.timers.tick(80000));assert.equal(read.state.kind,'loading');
 await act(async()=>t.mock.timers.tick(10000));assert.equal(read.state.kind,'error');assert.equal(read.state.lastGoodAt,'2026-10-26T09:00:00Z');
 assert.match(read.state.message,/資料仍在更新/);t.mock.timers.reset();
});
test('reload during an active read coalesces into one subsequent read',async()=>{
 let release,calls=0;globalThis.fetch=async()=>{calls++;if(calls===1)await new Promise(resolve=>release=resolve);return reply(fixture)};
 await mount(React.createElement(Probe));assert.equal(calls,1);
 await act(async()=>{read.reload();read.reload();read.reload()});assert.equal(calls,1);
 await act(async()=>release());assert.equal(calls,2);assert.equal(read.state.kind,'ready');
});
test('source permission hint is one short label without raw authorization details',async()=>{
 globalThis.fetch=async url=>reply(url==='/api/health'?{}:{...sourceBody(false),refresh_reason:'來源同步操作者尚未核實在職身分'});
 await mount(React.createElement(ui.SourceHealthPage,{c:sourceContext('member')}));await flush();
 assert.equal(document.body.textContent.includes('來源同步操作者尚未核實在職身分'),false);
 assert.equal(document.body.textContent.includes('權限不足'),true);
});
