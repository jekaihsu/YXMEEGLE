// T1 expected behavior, synthetic HTTP only; Lark requests cannot occur here.
import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {LarkPilotPanel,PilotView,parsePilot} from './src/LarkPilotPanel'; export {FullWorkspaceGate,fullReads} from './src/appCommon'; export {PeopleDirectoryPanel} from './src/PeopleDirectoryPanel';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.pilot-contract-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let module;try{module=await import(path.href)}finally{await fs.unlink(path)}
const {LarkPilotPanel,PilotView,parsePilot,FullWorkspaceGate,fullReads,PeopleDirectoryPanel}=module;
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const k of ['window','document','Event','FormData'])globalThis[k]=dom.window[k];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(r=>setTimeout(r,0))});
const payload=(source='lark_live')=>({status:'fresh',source,fetched_at:'2026-10-12T00:00:00Z',ttl_seconds:60,records:{cases:[{record_id:'rec_SYN',fields:{fldgZDflpb:{state:'null'}}}],work_orders:[],people:[]},table_states:{cases:'present',work_orders:'not_read',people:'not_read'},table_fetched_at:{cases:'2026-10-12T00:00:05Z',work_orders:null,people:null},counts:{cases:{requested:3,returned:1,omitted:2,has_more:true},work_orders:null,people:null}});
let root;
const render=element=>flush(()=>root.render(element));
const clean=async()=>{if(root)await flush(()=>root.unmount());root=undefined;fullReads.clear()};
const setup=()=>{root=createRoot(document.getElementById('root'))};
const c=enabled=>({w:{scope:'shell',version:1,environment:'production',users:[],freshness:{enabled}},s:{mode:'lark',user:{id:'ou_SYN',role:'manager',capabilities:['manage_people']}},refresh:async()=>{}});
const messages={pilot_disabled:'唯讀 Lark 試讀尚未啟用',pilot_not_company_workspace:'此工作區不是公司工作區',pilot_method_not_allowed:'唯讀 Lark 試讀不支援此請求方式',pilot_read_failed:'唯讀 Lark 試讀暫時無法完成',pilot_roster_missing:'尚無名冊核實紀錄',pilot_config_invalid:'系統設定異常',access_roster_expired:'公司名冊已逾 15 分鐘',access_not_admitted:'帳號尚未核實或已停用',source_authorization_denied:'你沒有讀取 Lark 來源的權限'};
for(const [code,message] of Object.entries(messages))test(`B1 ${code}`,async()=>{
 setup();const calls=[];
 globalThis.fetch=async(url,init)=>{calls.push({url,init});return new Response(JSON.stringify({code,detail:'SYN_private_detail'}),{status:['pilot_disabled','pilot_not_company_workspace'].includes(code)?404:403})};
 try{await render(React.createElement(LarkPilotPanel,{c:c(false)}));assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/lark-pilot/shadow');assert.equal(calls[0].init.method,'GET');assert.ok(document.body.textContent.includes(message),document.body.textContent);assert.ok(!document.body.textContent.includes('SYN_private_detail'))}finally{await clean()}
});
for(const ceiling of [60,30])test(`B1 stale message uses ceiling ${ceiling}`,async()=>{
 setup();const calls=[];globalThis.fetch=async(url)=>{calls.push(url);return new Response(JSON.stringify({code:'pilot_roster_stale',ceiling_seconds:ceiling,detail:'SYN'}),{status:403})};
 try{await render(React.createElement(LarkPilotPanel,{c:c(false)}));assert.deepEqual(calls,['/api/lark-pilot/shadow']);assert.ok(document.body.textContent.includes(`名冊核實已逾 ${ceiling} 秒`),document.body.textContent)}finally{await clean()}
});
for(const code of [undefined,'unknown_code'])test(`B1 unclassified 403 ${code}`,async()=>{
 setup();const calls=[];globalThis.fetch=async(url)=>{calls.push(url);return new Response(JSON.stringify({code,detail:'SYN'}),{status:403})};
 try{await render(React.createElement(LarkPilotPanel));assert.deepEqual(calls,['/api/lark-pilot/shadow']);assert.ok(document.body.textContent.includes('讀取失敗（原因不明）'),document.body.textContent)}finally{await clean()}
});
test('B2 counts, table timestamp and field states visible',async()=>{
 setup();globalThis.fetch=()=>{throw Error('view must not fetch')};
 try{await render(React.createElement(PilotView,{data:parsePilot(payload()),now:Date.parse('2026-10-12T00:00:10Z')}));const text=document.body.textContent;assert.ok(text.includes('fldgZDflpb')&&text.includes('明確空值'));assert.ok(text.includes('08:00:05'),'per-table time must be visible');assert.ok(text.includes('至少 2 筆'),text)}finally{await clean()}
});
for(const source of ['lark_live','mock','local','unmapped'])test(`B3 source ${source} truthful live label`,async()=>{
 setup();globalThis.fetch=()=>{throw Error('view must not fetch')};
 try{await render(React.createElement(PilotView,{data:parsePilot(payload(source)),now:Date.parse('2026-10-12T00:01:01Z')}));assert.ok(!document.body.textContent.includes('Lark 即時'),document.body.textContent);if(source==='lark_live')assert.ok(document.body.textContent.includes('資料待更新'))}finally{await clean()}
});
for(const enabled of [false,true])test(`B4 roster-only retry freshness ${enabled}`,async()=>{
 setup();const calls=[];let resolveSync;
 globalThis.fetch=async(url,init)=>{calls.push({url,init});if(url==='/api/lark-pilot/shadow')return new Response(JSON.stringify({code:'pilot_roster_stale',ceiling_seconds:60,detail:'SYN'}),{status:403});return new Promise(resolve=>{resolveSync=resolve})};
 try{await render(React.createElement(LarkPilotPanel,{c:c(enabled)}));assert.equal(calls.length,1);const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='重新核對名冊後重試');assert.ok(button,'stale evidence needs roster retry');await flush(()=>button.click());await flush(()=>button.click());assert.equal(calls.length,2,'double click makes one roster refresh');assert.equal(calls[1].url,enabled?'/api/live/refresh':'/api/people/sync');assert.equal(calls[1].init.method,'POST');if(enabled)assert.deepEqual(JSON.parse(calls[1].init.body).datasets,['roster']);assert.ok(!calls.some(x=>x.url.includes('/sources/')));await flush(()=>resolveSync(new Response(JSON.stringify({freshness:{enabled,server_time:'2026-10-12T00:00:00Z',datasets:Object.fromEntries(['roster','sources','attendance'].map(k=>[k,{status:'fresh',ttl_seconds:60,age_seconds:0,as_of:'2026-10-12T00:00:00Z'}]))},status:'ready',last_sync:'2026-10-12T00:00:00Z'}))));assert.equal(calls.filter(x=>x.url==='/api/lark-pilot/shadow').length,2,'pilot retries only once even if still stale')}finally{await clean()}
});
test('B5 full workspace timeout becomes visible error and retry',async()=>{
 setup();const nativeTimer=globalThis.setTimeout;const timers=[];const calls=[];
 globalThis.setTimeout=(fn,delay,...args)=>delay>=30000?(timers.push(fn),12345):nativeTimer(fn,delay,...args);
 globalThis.fetch=(url,init)=>{calls.push({url,init});return new Promise((resolve,reject)=>init.signal?.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError'))))};
 try{await render(React.createElement(FullWorkspaceGate,{c:c(false),children:()=>React.createElement('p',null,'loaded')}));assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/workspace');await flush(()=>timers.forEach(fn=>fn()));assert.ok(document.querySelector('[role="alert"]'),'bounded timeout must surface error');assert.ok(document.body.textContent.includes('重試'));await flush(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='重試').click());assert.equal(calls.length,2,'timeout retry starts a new full read')}finally{globalThis.setTimeout=nativeTimer;await clean()}
});
test('B5 version change starts a new read and drops old result',async()=>{
 setup();const calls=[];globalThis.fetch=(url,init)=>new Promise(resolve=>calls.push({url,init,resolve}));
 const gate=version=>React.createElement(FullWorkspaceGate,{c:{...c(false),w:{...c(false).w,version}},children:fc=>React.createElement('p',null,fc.w.label)});
 try{await render(gate(1));await render(gate(2));assert.equal(calls.length,2);assert.ok(calls.every(x=>x.url==='/api/workspace'));await flush(()=>calls[1].resolve(new Response(JSON.stringify({label:'new'}))));await flush(()=>calls[0].resolve(new Response(JSON.stringify({label:'old'}))));assert.equal(document.body.textContent,'new')}finally{await clean()}
});
for(const [code,message] of Object.entries({lark_permission_denied:'Lark 拒絕此應用讀取',lark_read_failed:'Lark 資料暫時無法讀取'}))test(`B1/B2 remote ${code} failure hides counts`,async()=>{
 setup();const calls=[];const data={...payload(),status:code==='lark_permission_denied'?'blocked':'error',code,counts:{cases:null,work_orders:null,people:null},records:{cases:[],work_orders:[],people:[]}};
 globalThis.fetch=async(url)=>{calls.push(url);return new Response(JSON.stringify(data))};
 try{await render(React.createElement(LarkPilotPanel));assert.deepEqual(calls,['/api/lark-pilot/shadow']);assert.ok(document.body.textContent.includes(message),document.body.textContent);assert.ok(!document.body.textContent.includes('0 筆'))}finally{await clean()}
});
test('B3 unknown source rejected without a live badge',async()=>{assert.throws(()=>parsePilot(payload('unknown')))});
for(const enabled of [false,true])test(`B5 roster success includes server as_of, mode ${enabled}`,async()=>{
 setup();const calls=[];const stamp='2026-10-12T00:00:00Z';const freshness={enabled,server_time:stamp,datasets:Object.fromEntries(['roster','sources','attendance'].map(k=>[k,{status:'fresh',ttl_seconds:60,age_seconds:0,as_of:stamp}]))};
 const context=c(enabled);context.w.freshness={...freshness,datasets:{...freshness.datasets,roster:{...freshness.datasets.roster,as_of:null}}};context.onFreshness=f=>{context.w.freshness=f};context.refresh=async()=>{};
 globalThis.fetch=async(url,init)=>{calls.push({url,init});context.w.people_directory_status={status:'ready',last_success_at:stamp};return new Response(JSON.stringify({freshness}))};
 try{await render(React.createElement(PeopleDirectoryPanel,{c:context}));await flush(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='同步 Lark 人員名冊').click());assert.equal(calls.length,1);assert.equal(calls[0].url,enabled?'/api/live/refresh':'/api/people/sync');await render(React.createElement(PeopleDirectoryPanel,{c:context}));assert.ok(document.body.textContent.includes('08:00:00')||document.body.textContent.includes('上午8:00:00'),document.body.textContent)}finally{await clean()}
});
test('B3 table freshness controls live label even when envelope is fresh',async()=>{
 setup();const data=payload();data.table_fetched_at.cases='2026-10-11T23:58:00Z';globalThis.fetch=()=>{throw Error('view must not fetch')};
 try{await render(React.createElement(PilotView,{data:parsePilot(data),now:Date.parse('2026-10-12T00:00:10Z')}));assert.ok(!document.body.textContent.includes('Lark 即時'),document.body.textContent)}finally{await clean()}
});
for(const enabled of [false,true])test(`B5 roster failure visible without source sync, mode ${enabled}`,async()=>{
 setup();const calls=[];const context=c(enabled);context.w.freshness.datasets={};context.onRefreshError=()=>{};
 globalThis.fetch=async(url,init)=>{calls.push({url,init});return new Response(JSON.stringify({code:'lark_read_failed',detail:'Lark 資料暫時無法讀取'}),{status:502})};
 try{await render(React.createElement(PeopleDirectoryPanel,{c:context}));await flush(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='同步 Lark 人員名冊').click());assert.equal(calls.length,1);assert.equal(calls[0].url,enabled?'/api/live/refresh':'/api/people/sync');assert.ok(document.querySelector('[role="alert"]').textContent.includes('Lark 資料暫時無法讀取'))}finally{await clean()}
});
for(const enabled of [false,true])test(`roster retry timeout is visible, mode ${enabled}`,async()=>{
 setup();const nativeTimer=globalThis.setTimeout;const timers=[];const delays=[];const calls=[];
 globalThis.setTimeout=(fn,delay,...args)=>delay>=30000?(timers.push(fn),delays.push(delay),12345):nativeTimer(fn,delay,...args);
 globalThis.fetch=async(url,init)=>{calls.push({url,init});return url==='/api/lark-pilot/shadow'?new Response(JSON.stringify({code:'pilot_roster_stale',ceiling_seconds:60}),{status:403}):new Promise(()=>{})};
 try{
  await render(React.createElement(LarkPilotPanel,{c:c(enabled)}));
  await flush(()=>document.querySelector('button').click());
  assert.deepEqual(delays,[120000,120000],'pilot and roster call sites use 120-second deadlines');
  await flush(()=>timers.forEach(fn=>fn()));
  assert.ok(document.body.textContent.includes('讀取逾時'));
  assert.equal(calls.length,2);assert.ok(calls[1].init.signal.aborted);
  assert.equal(document.querySelector('button').disabled,false);
 }finally{globalThis.setTimeout=nativeTimer;await clean()}
});
for(const defect of ['unread','no-time','incomplete'])test(`fresh envelope cannot hide ${defect} table`,async()=>{
 setup();const data=payload();
 data.table_states={cases:'present',work_orders:'present',people:'present'};
 data.table_fetched_at={cases:'2026-10-12T00:00:05Z',work_orders:'2026-10-12T00:00:05Z',people:'2026-10-12T00:00:05Z'};
 data.counts={cases:{requested:1,returned:1,omitted:0,has_more:false},work_orders:{requested:0,returned:0,omitted:0,has_more:false},people:{requested:0,returned:0,omitted:0,has_more:false}};
 if(defect==='unread')data.table_states.people='not_read';
 if(defect==='no-time')data.table_fetched_at.people=null;
 if(defect==='incomplete')data.counts.cases.has_more=true;
 try{await render(React.createElement(PilotView,{data:parsePilot(data),now:Date.parse('2026-10-12T00:00:10Z')}));assert.ok(!document.body.textContent.includes('Lark 即時'));assert.equal(document.querySelector('.data-freshness-fresh'),null)}finally{await clean()}
});
for(const enabled of [false,true])test(`roster displays response as_of before parent reload, mode ${enabled}`,async()=>{
 setup();const context=c(enabled);context.w.freshness.datasets={};const stamp=new Date().toISOString();context.onFreshness=()=>{};
 const freshness={enabled,server_time:stamp,datasets:Object.fromEntries(['roster','sources','attendance'].map(k=>[k,{status:'fresh',ttl_seconds:60,age_seconds:0,as_of:stamp}]))};
 globalThis.fetch=async()=>new Response(JSON.stringify({freshness}));
 try{await render(React.createElement(PeopleDirectoryPanel,{c:context}));await flush(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='同步 Lark 人員名冊').click());const t=document.body.textContent;assert.ok(t.includes(new Date(stamp).toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'}).replaceAll('-','/'))&&t.includes('(台北時間)'),t)}finally{await clean()}
});

for(const enabled of [false,true])test(`roster recovery routes only roster and re-fetches pilot, mode ${enabled}`,async()=>{
 setup();const calls=[];const stamp=new Date().toISOString();
 const freshness={enabled,server_time:stamp,datasets:Object.fromEntries(['roster','sources','attendance'].map(k=>[k,{status:'fresh',ttl_seconds:60,age_seconds:0,as_of:stamp}]))};
 globalThis.fetch=async(url,init)=>{calls.push({url,init});return new Response(JSON.stringify(url==='/api/lark-pilot/shadow'?(calls.length===1?{code:'pilot_roster_missing'}:payload()):{freshness}),{status:calls.length===1?403:200})};
 try{
  await render(React.createElement(LarkPilotPanel,{c:c(enabled)}));await flush(()=>document.querySelector('button').click());
  assert.deepEqual(calls.map(x=>x.url),['/api/lark-pilot/shadow',enabled?'/api/live/refresh':'/api/people/sync','/api/lark-pilot/shadow']);
  assert.equal(calls[1].init.method,'POST');
  assert.deepEqual(calls[1].init.body===undefined?undefined:JSON.parse(calls[1].init.body),enabled?{datasets:['roster'],wait:true,force:false}:undefined);
  assert.ok(document.body.textContent.includes('工程確認單'));
 }finally{await clean()}
});

for(const age of ['expired','unknown'])test(`live roster recovery rejects fresh status with ${age} age`,async()=>{
 setup();const calls=[];const stamp=new Date().toISOString();
 const freshness={enabled:true,server_time:stamp,datasets:Object.fromEntries(['roster','sources','attendance'].map(k=>[k,{status:'fresh',ttl_seconds:60,age_seconds:age==='unknown'?null:60,as_of:age==='unknown'?null:new Date(Date.parse(stamp)-60000).toISOString()}]))};
 globalThis.fetch=async(url,init)=>{calls.push({url,init});return new Response(JSON.stringify(url==='/api/lark-pilot/shadow'?{code:'pilot_roster_stale'}:{freshness}),{status:url==='/api/lark-pilot/shadow'?403:200})};
 try{
  await render(React.createElement(LarkPilotPanel,{c:c(true)}));await flush(()=>document.querySelector('button').click());
  assert.equal(calls.length,2,'aged roster must not trigger pilot re-fetch');
  assert.ok(document.body.textContent.includes('名冊讀取尚未完成'));
  assert.equal(document.querySelector('button').disabled,false);
 }finally{await clean()}
});

test('legacy roster sync success re-fetches pilot though freshness is unconfigured',async()=>{
 setup();const calls=[];const stamp=new Date().toISOString();
 // Real legacy /api/people/sync shape: live reads are disabled, so every dataset reports unconfigured.
 const freshness={enabled:false,server_time:stamp,datasets:Object.fromEntries(['roster','sources','attendance'].map(k=>[k,{status:'unconfigured',ttl_seconds:300,age_seconds:0,as_of:stamp}]))};
 globalThis.fetch=async(url,init)=>{calls.push({url,init});return new Response(JSON.stringify(url==='/api/lark-pilot/shadow'?(calls.length===1?{code:'pilot_roster_stale'}:payload()):{status:'ready',last_success_at:stamp,freshness}),{status:calls.length===1?403:200})};
 try{
  await render(React.createElement(LarkPilotPanel,{c:c(false)}));await flush(()=>document.querySelector('button').click());
  assert.deepEqual(calls.map(x=>x.url),['/api/lark-pilot/shadow','/api/people/sync','/api/lark-pilot/shadow']);
 }finally{await clean()}
});
const reasonCases={no_linked_records:'案件目前沒有關聯的工單，未讀取',traversal_unavailable:'目前唯讀範圍無法依關聯讀取',access_denied:'應用尚無此資料表讀取權限（Lark 1254302）',read_failed:'讀取失敗'};
for(const [reason,wording] of Object.entries(reasonCases))test(`VCC-119 per-table reason ${reason}`,async()=>{
 setup();globalThis.fetch=()=>{throw Error('view must not fetch')};
 const data={...payload(),status:'partial',table_reasons:{work_orders:reason}};
 try{await render(React.createElement(PilotView,{data:parsePilot(data),now:Date.parse('2026-10-12T00:00:10Z')}));const text=document.body.textContent;assert.ok(text.includes(wording),text);assert.equal(text.includes('讀取失敗'),reason==='read_failed',text);assert.ok(text.includes('部分資料'));assert.ok(!text.includes('Lark 即時'))}finally{await clean()}
});
test('VCC-119 no_linked_records wording names the right parent per table',async()=>{
 setup();
 try{
  const data=parsePilot({...payload(),status:'partial',table_states:{cases:'not_read',work_orders:'not_read',people:'not_read'},table_reasons:{work_orders:'no_linked_records',people:'no_linked_records'}});
  await render(React.createElement(PilotView,{data,now:Date.parse('2026-10-12T00:00:10Z')}));
  const text=document.body.textContent;
  assert.ok(text.includes('案件目前沒有關聯的工單'),text);assert.ok(text.includes('工單目前沒有關聯的人員'),text);
  assert.equal(text.split('案件目前沒有關聯的工單').length-1,1,text);
  const people=[...document.querySelectorAll('section,article,div')].find(e=>e.textContent.includes('人員名單')&&e.textContent.includes('工單目前沒有關聯的人員')&&!e.textContent.includes('外業工作單'));
  assert.ok(people&&!people.textContent.includes('案件目前沒有關聯的工單'));
 }finally{await clean()}
});
test('VCC-119 old payload and unknown reason degrade to plain table state',async()=>{
 setup();
 try{assert.deepEqual(parsePilot(payload()).table_reasons,{});const data=parsePilot({...payload(),table_reasons:{work_orders:'SYN_new_reason',people:{x:1}}});assert.deepEqual(data.table_reasons,{});await render(React.createElement(PilotView,{data,now:Date.parse('2026-10-12T00:00:10Z')}));assert.ok(document.body.textContent.includes('尚未讀取'));assert.ok(!document.body.textContent.includes('SYN_new_reason'))}finally{await clean()}
});
