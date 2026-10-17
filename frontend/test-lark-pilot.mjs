import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {LarkPilotPanel,PilotView,parsePilot} from './src/LarkPilotPanel';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.pilot-test-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let module;try{module=await import(path.href)}finally{await fs.unlink(path)}
const {LarkPilotPanel,PilotView,parsePilot}=module;
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const k of ['window','document','Event','FormData'])globalThis[k]=dom.window[k];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const root=createRoot(document.getElementById('root'));
const payload=(status='fresh',source='lark_live')=>({status,source,fetched_at:'2026-10-12T00:00:00Z',ttl_seconds:60,records:{cases:[],work_orders:[],people:[]},table_states:{cases:'present',work_orders:'present',people:'present'},table_fetched_at:{cases:'2026-10-12T00:00:00Z',work_orders:'2026-10-12T00:00:00Z',people:'2026-10-12T00:00:00Z'},counts:Object.fromEntries(['cases','work_orders','people'].map(name=>[name,['blocked','error','partial'].includes(status)?null:{requested:0,returned:0,omitted:0,has_more:false}]))});
const render=async(element)=>act(async()=>{root.render(element);await new Promise(r=>setTimeout(r,0))});
try{
 for(const [state,copy] of Object.entries({fresh:'已讀取',stale:'資料待更新',blocked:'無法讀取',partial:'部分資料',error:'讀取失敗',unconfigured:'尚未設定'})){
  await render(React.createElement(PilotView,{data:parsePilot(payload(state)),now:Date.parse('2026-10-12T00:00:10Z')}));
  assert.ok(document.body.textContent.includes(copy),state);
  assert.ok(document.body.textContent.includes('08:00:00'),'Taipei timestamp');
  assert.equal(document.querySelectorAll('button,form').length,0);
  assert.equal(document.querySelector('[role="status"]').getAttribute('aria-live'),'polite');
  if(['blocked','error','partial'].includes(state))assert.ok(!document.body.textContent.includes('0 筆'));
 }
 for(const [source,label] of Object.entries({lark_live_cached:'快取',mock:'示範',local:'本機',unmapped:'未對映'})){
  await render(React.createElement(PilotView,{data:parsePilot(payload('fresh',source)),now:Date.parse('2026-10-12T00:00:10Z')}));
  assert.ok(document.body.textContent.includes(label));
 }
 await render(React.createElement(PilotView,{data:parsePilot(payload()),now:Date.parse('2026-10-12T00:01:01Z')}));
 assert.ok(document.body.textContent.includes('資料待更新'));
 const requests=[];
 globalThis.fetch=async(url,init)=>{requests.push({url,init});return new Response(JSON.stringify(payload()))};
 await render(React.createElement(LarkPilotPanel,{demo:true}));
 assert.equal(requests.length,0);assert.ok(document.body.textContent.includes('示範資料'));
 await render(React.createElement(LarkPilotPanel,{demo:false}));
 assert.equal(requests.length,1);assert.equal(requests[0].url,'/api/lark-pilot/shadow');
 assert.equal(requests[0].init.method,'GET');
 assert.throws(()=>parsePilot({...payload(),source:'secret-source'}));
 console.log('F01-F07 synthetic rendering: states, time, TTL, no controls, GET only, demo isolation and semantic status passed.');
}finally{await act(()=>root.unmount());dom.window.close()}
