import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {fakeClock} from './fake-clock-fixture.mjs';
const b=await build({stdin:{contents:"export {invalidateSessionEpoch} from './src/api';export * from './src/useHomePanels';export {UnifiedHome} from './src/UnifiedHome';export {WorkPage} from './src/IntegratedPages';export {ReportCard} from './src/homeViews/ReportCard';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.home-once.mjs',import.meta.url);await fs.writeFile(file,b.outputFiles[0].text);let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','Event','localStorage','sessionStorage','location','history'])globalThis[key]=dom.window[key];globalThis.IS_REACT_ACT_ENVIRONMENT=true;
let failRead=false;
const clock=fakeClock(dom.window,Date.parse('2026-11-01T15:59:00Z')),calls=[];
const body=(url)=>({panel:new URL(url,'http://home').searchParams.get('panel')||'assigned',scope:'mine',readState:'complete',snapshot_version:'v1',as_of:'2026-11-01T15:59:00Z',freshness:{status:'fresh',last_success_at:null,refreshing:false},counts:{node_assignments:0,tasks:0,local_workflow:0,sop_tasks:0,complete:true},items:[],next_cursor:null,has_more:false,complete:true,total_count:0,manager_view_available:false});
globalThis.fetch=async(url,init)=>{calls.push({url,init});return new Response(JSON.stringify(failRead?{detail:'failed'}:body(url)),{status:failRead?500:200})};
const c={s:{workspace_id:'once',mode:'lark',user:{id:'u',role:'member'},features:{node_assignment:true}},w:{version:1,as_of:'2026-11-01',projects:[],users:[]},route:{view:'work'},reloadVersion:1,refresh:async()=>{},go(){}};
const root=createRoot(document.getElementById('root'));
const render=node=>act(async()=>root.render(node));
async function events(){await act(async()=>{await clock.advance(86400000);for(const event of ['focus','online','pointerdown','keydown','wheel'])window.dispatchEvent(new Event(event));for(const visibility of ['hidden','visible']){Object.defineProperty(document,'visibilityState',{configurable:true,value:visibility});document.dispatchEvent(new Event('visibilitychange'))}})}
try{
 for(const Component of [m.UnifiedHome,m.WorkPage]){
  calls.length=0;await render(React.createElement(React.StrictMode,null,React.createElement(Component,{c})));
  assert.equal(calls.length,1,'StrictMode initial page load exactly once');await events();assert.equal(calls.length,1,'+24h and all events add zero reads');
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='重新讀取').click());
  if(Component===m.WorkPage)await render(React.createElement(React.StrictMode,null,React.createElement(Component,{c:{...c,reloadVersion:2}})));
  assert.equal(calls.length,2,'explicit refresh exactly one batch');await render(null);
 }
 let exposed;
 const resource={endpoint:'/api/home-panels',query:{panel:'assigned'}};
 function Reader(){exposed=m.useHomeResource(c,resource,raw=>m.homeValue(m.parseHomeResponse(raw),true,raw.as_of));return React.createElement('span',null,exposed.loading?'loading':exposed.data?.total_count??'unknown')}
 const readers=count=>React.createElement(m.HomeDataProvider,{c},...Array.from({length:count},(_,key)=>React.createElement(Reader,{key})));
 calls.length=0;await render(readers(2));assert.equal(calls.length,1,'two readers share one resource');
 await render(readers(0));await events();await render(readers(2));assert.equal(calls.length,1,'lazy view remount retains owner resource');
 await act(async()=>exposed.owner.ownWriteCommitted('own-write',[resource,resource]));assert.equal(calls.length,2,'own write refreshes affected resource exactly once');
 await act(async()=>exposed.owner.ownWriteCommitted('own-write',[resource]));assert.equal(calls.length,2,'duplicate completion coalesces');
 assert.equal(calls[1].init.headers.get('X-YX-Fetch-Intent'),'own_write_committed');
 await act(async()=>exposed.retry());assert.equal(calls.length,3,'explicit resource retry reads once');
 await render(readers(0));await render(readers(2));assert.equal(calls.length,3,'settled explicit refresh stays pinned across remount');
 failRead=true;
 await act(async()=>{await exposed.owner.ownWriteCommitted('failed-write-read',[resource]).catch(()=>{})});
 assert.equal(calls.length,4);assert.equal(exposed.data.total_count,0,'known data stays available from Error.previous');assert.equal(exposed.dataTime,'2026-11-01T15:59:00Z');
 assert.equal(exposed.owner.state(resource).kind,'Error');
 failRead=false;await act(async()=>m.invalidateSessionEpoch());assert.equal(calls.length,5,'same mounted page gets a new owner on session epoch change');
 assert.equal(exposed.data.total_count,0);assert.equal(exposed.loading,false,'epoch change cannot leave a closed owner loading');

 await render(null);
 let scoped;
 function Scoped({context}){scoped=m.useHomeResource(context,resource,raw=>m.homeValue(m.parseHomeResponse(raw),true,raw.as_of));return React.createElement('span',null,scoped.data?.total_count??'unknown')}
 const grantContext={...c,s:{...c.s,user:{...c.s.user,capabilities:['read','write'],authz_version:1}}};
 const beforeGrants=calls.length;
 await render(React.createElement(Scoped,{context:grantContext}));
 await render(React.createElement(Scoped,{context:{...grantContext,s:{...grantContext.s,user:{...grantContext.s.user,capabilities:['write','read']}}}}));
 assert.equal(calls.length,beforeGrants+1,'equivalent grant order preserves one owner');
 await render(React.createElement(Scoped,{context:{...grantContext,s:{...grantContext.s,user:{...grantContext.s.user,authz_version:2}}}}));
 assert.equal(calls.length,beforeGrants+2,'grant revision rekeys the mounted owner');
 await render(null);
 const held=[];
 globalThis.fetch=(url,init)=>new Promise(resolve=>held.push({url,init,resolve}));
 await render(React.createElement(Scoped,{context:c}));assert.equal(held.length,1);
 const original=scoped.owner.read(resource,{reason:'initial_open'},()=>{throw Error('must join initial read')});
 let successor;
 await act(async()=>{successor=scoped.owner.ownWriteCommitted('during-initial',[resource])});assert.equal(held.length,2);
 assert.equal(held[0].init.signal.aborted,true);
 await act(async()=>{held[1].resolve(new Response(JSON.stringify({...body('/'),total_count:22})));await successor});
 assert.equal((await original).data.total_count,22,'superseded initial awaiter resolves successor data');
 await act(async()=>held[0].resolve(new Response(JSON.stringify({...body('/'),total_count:11}))));
 assert.equal(scoped.data.total_count,22,'late superseded result never regresses Home');
 assert.equal(m.parseHomeResponse({...body('/'),counts:{node_assignments:null,tasks:null,local_workflow:null,complete:false}}).counts.sop_tasks,null);
 assert.equal(m.parseHomeResponse(body('/')).counts.sop_tasks,0);
 for(const read of [{loading:true,error:'',unavailable:false},{loading:false,error:'failed',unavailable:false}]){
  await render(React.createElement(m.ReportCard,{id:'achievement',read}));assert.doesNotMatch(document.body.textContent,/全部\s*0|0%|共\s*0/);
 }
 console.log('PASS Home/Work each: initial 1, +24h/events 1, explicit refresh 2; shared readers/remount 1; affected own-write 2; unknown ≠ 0');
}finally{await act(async()=>root.unmount());clock.restore();dom.window.close()}
