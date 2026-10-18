import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import React,{act} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createRoot} from 'react-dom/client';
import {JSDOM} from 'jsdom';
import * as model from './src/dispatchBoardModel.ts';
const {variants}=JSON.parse(await fs.readFile(new URL('./fixtures/dispatchBoardSample.json',import.meta.url),'utf8'));
const bundle=await build({stdin:{contents:"export {DispatchBoard,DispatchBoardFrame} from './src/DispatchBoard';export {AppShell} from './src/AppShell';export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.dispatch-fixes-test.mjs',import.meta.url);
await fs.writeFile(temp,bundle.outputFiles[0].text);
let ui;
try{ui=await import(temp.href)}finally{await fs.unlink(temp)}
const frame=(raw)=>renderToStaticMarkup(React.createElement(ui.DispatchBoardFrame,{from:'2026-07-27',read:{data:model.parseDispatchBoard(raw),loading:false,error:'',reload(){}},onWeek(){}}));

test('F4 read_failed snapshot retains counts and retry notice',()=>{
 const html=frame({...variants.loaded,source:{...variants.loaded.source,quality:{states:['read_failed']}}});
 assert.equal(html.includes('<strong>6</strong>'),true);
 assert.equal(html.includes('已保留上次成功資料。'),true);
 assert.equal(html.includes('重試'),true);
});
test('F5 inactive timed overlap counts as conflict',()=>{
 const raw=structuredClone(variants.loaded);
 raw.slots=[raw.slots[1]];raw.slots[0].crew[0].active=false;
 assert.deepEqual(model.parseDispatchBoard(raw).kpi,{slots:1,unassigned:0,unknown_overlap:0,conflict:1});
});
test('F9 midnight end is exclusive in day list and person grid',()=>{
 const raw=structuredClone(variants.loaded);raw.slots=[raw.slots[1]];
 raw.slots[0].interval={start:'2026-07-27T23:00:00+08:00',end:'2026-07-28T00:00:00+08:00',precision:'datetime'};
 const board=model.parseDispatchBoard(raw);
 assert.equal(model.slotsPerDay(board.slots,'2026-07-27').length,1);
 assert.equal(model.slotsPerDay(board.slots,'2026-07-28').length,0);
 assert.equal(model.personDayGrid(board,['2026-07-28'])[0].days[0].booked_slots,0);
});
test('F9 snapshot age preserves server age',()=>{
 const raw=structuredClone(variants.stale);raw.source.quality.age_seconds=7200;
 assert.equal(model.parseDispatchBoard(raw).source.quality.age_seconds,7200);
 assert.equal(frame(raw).includes('120 分鐘前'),true);
});
test('F11 accessible cards include crew, status and unassigned state',()=>{
 const dom=new JSDOM(frame(variants.loaded));
 const cards=[...dom.window.document.querySelectorAll('.db-slot')];
 const name=card=>card.getAttribute('aria-label')||card.textContent;
 assert.equal(cards.some(card=>name(card).includes('尚未安排人員')&&name(card).includes('待派工')),true);
 assert.equal(cards.some(card=>name(card).includes('示例 林安娜')&&name(card).includes('時段衝突')),true);
 assert.equal(cards.some(card=>name(card).includes('不可用')),true);
 dom.window.close();
});
test('F11 snapshot age stays outside status live region',()=>{
 const dom=new JSDOM(frame(variants.stale));
 assert.equal(dom.window.document.querySelector('[role="status"]').textContent.includes('分鐘前'),false);
 assert.equal(dom.window.document.querySelector('.db-source').textContent.includes('分鐘前'),true);
 dom.window.close();
});
test('F10 member navigation hides dispatch while PM company navigation shows it',()=>{
 for(const [role,expected] of [['member',false],['pm',true],['manager',true]]){
  const html=renderToStaticMarkup(React.createElement(ui.AppShell,{s:{features:{dispatch_board:true},user:{name:'測試',role},mode:'lark',workspace_id:'company'},route:{view:'dashboard'},error:'',ready:true,go(){},children:null}));
  assert.equal(html.includes('派工看板'),expected);
 }
});
test('F4 cold HTTP 200 read_failed board is displayed',async()=>{
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
 for(const name of ['window','document','Event','HTMLElement','Element','Node'])globalThis[name]=dom.window[name];
 globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 globalThis.fetch=async url=>{const query=new URL(url,'http://localhost').searchParams;return new Response(JSON.stringify({...variants.loaded,window:{from:query.get('from'),to:query.get('to'),tz:'Asia/Taipei'},source:{...variants.loaded.source,quality:{states:['read_failed']}}}),{status:200})};
 const root=createRoot(document.getElementById('root'));ui.invalidateSessionEpoch();
 try{await act(async()=>root.render(React.createElement(ui.DispatchBoard)));assert.equal(document.querySelector('.db-kpi strong').textContent,'6');assert.equal(document.body.textContent.includes('已保留上次成功資料。'),true)}
 finally{await act(async()=>root.unmount());dom.window.close()}
});
test('F7 polling ignores stable partial joins, continues pending joins, caps time and cancels switches',async()=>{
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
 for(const name of ['window','document','Event','HTMLElement','Element','Node'])globalThis[name]=dom.window[name];
 globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 const realSet=globalThis.setTimeout,realClear=globalThis.clearTimeout,realNow=Date.now;
 let now=100000,timers=new Map(),serial=0,calls=0,pending=false;
 Date.now=()=>now;
 globalThis.setTimeout=(fn,ms,...args)=>{if(ms===1500){const id=++serial;timers.set(id,fn);return id}return realSet(fn,ms,...args)};
 globalThis.clearTimeout=id=>{if(timers.has(id))timers.delete(id);else realClear(id)};
 globalThis.fetch=async url=>{calls++;const query=new URL(url,'http://localhost').searchParams;return new Response(JSON.stringify({...variants.loaded,window:{from:query.get('from'),to:query.get('to'),tz:'Asia/Taipei'},source:{...variants.loaded.source,joins:{people:pending?'unavailable':'ok',instruments:'ok',vehicles:'ok',cases:'partial'},quality:{states:['partial']}}}),{status:200})};
 const root=createRoot(document.getElementById('root'));ui.invalidateSessionEpoch();
 const click=async label=>act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent===label||b.getAttribute('aria-label')===label).click());
 const tick=async()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);now+=1500;await act(async()=>fn())};
 try{
  await act(async()=>root.render(React.createElement(ui.DispatchBoard)));
  assert.equal(timers.size,0);
  pending=true;await click('重新讀取');
  for(let i=0;i<4;i++)await tick();
  assert.equal(timers.size,1);
  assert.equal(calls,6);
  now+=30000;await tick();assert.equal(timers.size,0);
  await click('上一週');assert.equal(timers.size,1);
  pending=false;await click('下一週');assert.equal(timers.size,0);
  pending=true;await click('重新讀取');assert.equal(timers.size,1);
  ui.invalidateSessionEpoch();pending=false;await act(async()=>root.render(React.createElement(ui.DispatchBoard)));assert.equal(timers.size,0);
 }finally{await act(async()=>root.unmount());globalThis.setTimeout=realSet;globalThis.clearTimeout=realClear;Date.now=realNow;dom.window.close()}
});
