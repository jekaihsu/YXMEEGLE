import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {renderToStaticMarkup} from 'react-dom/server';
import {JSDOM} from 'jsdom';
const bundle=await build({stdin:{contents:"export {UnifiedHome} from './src/UnifiedHome';export {AppShell} from './src/AppShell';export * from './src/dispatchAccess';export * from './src/dispatchLinks';export {HomeDispatchFrame} from './src/HomeDispatchCard';export {parseDispatchBoard} from './src/dispatchBoardModel';export {availableCardIds,parseHomeLayout,homeSections} from './src/homeLayout';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.home-dispatch-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);
let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
const session={features:{dispatch_board:true},user:{role:'pm'},mode:'lark',workspace_id:'company'};
for(const [change,expected] of [[{},true],[{user:{role:'manager'}},true],[{user:{role:'member'}},false],[{features:{}},false],[{features:{dispatch_board:'true'}},false],[{mode:'demo'},false],[{workspace_id:'test-one'},false],[{workspace_id:'demo-one'},false]])assert.equal(m.canReadDispatch({...session,...change}),expected);
assert.equal(m.canReadDispatch(null),false);
assert.equal(m.availableCardIds('company',session.user,{unavailable:true},session).includes('dispatch'),true);
assert.equal(m.availableCardIds('company',session.user,{unavailable:false},{...session,user:{role:'member'}}).includes('dispatch'),false);
const saved=m.parseHomeLayout('{"version":2,"layouts":{"company":{"order":["cases"],"hidden":["dispatch"]}}}');
assert.equal(saved.version,2);assert.equal(saved.layouts.company.hidden.includes('dispatch'),true);
assert.deepEqual(m.homeSections('company',{order:['dispatch','cases'],hidden:[]}).map(s=>[s.id,s.cards]),[['todo',['dispatch','cases']]]);
assert.equal(m.parseHomeLayout(null).layouts.assign.order.includes('dispatch'),true);
assert.equal(m.parseHomeLayout(null).layouts.mine.order.includes('dispatch'),true);
const projects=[{id:'project A',code:'C001',name:'測量案'},{id:'project B',code:'C002',name:'另案'}];
assert.equal(m.dispatchCaseHref({code:'C001',name:null,ref:'recSecret'},projects),'#view=project&project=project+A&tab=flow');
assert.equal(m.dispatchCaseHref({code:null,name:'測量案',ref:null},projects),'#view=project&project=project+A&tab=flow');
assert.equal(m.dispatchCaseHref({code:'missing',name:null,ref:'project A'},projects),null);
assert.equal(m.dispatchCaseHref({code:'missing',name:'測量案',ref:null},projects),null);
assert.equal(m.dispatchCaseHref({code:null,name:'測量案',ref:null},[...projects,{id:'duplicate',code:'C003',name:'測量案'}]),null);
assert.equal(m.dispatchCaseHref({code:'C001',name:'另案',ref:null},projects),null);
const {variants}=JSON.parse(await fs.readFile(new URL('./fixtures/dispatchBoardSample.json',import.meta.url),'utf8'));
const frame=(variant,error='')=>new JSDOM(renderToStaticMarkup(React.createElement(m.HomeDispatchFrame,{from:'2026-07-27',read:{data:variant?m.parseDispatchBoard(variant):undefined,loading:!variant&&!error,error,reload(){}}}))).window.document;
let doc=frame(variants.loaded);
assert.deepEqual([...doc.querySelectorAll('.home-dispatch-count')].map(el=>el.textContent),['1','2','2']);
assert.equal(doc.querySelector('a[href="#view=dispatch"]').getAttribute('href'),'#view=dispatch');
assert.equal(doc.querySelector('a[href="#view=dispatch&tab=work"]').textContent,'查看工作進度與需要我處理');
for(const state of ['forbidden','empty_future_window']){
 doc=frame(variants[state]);assert.deepEqual([...doc.querySelectorAll('.home-dispatch-count')].map(el=>el.textContent),['—','—','—']);
}
assert.deepEqual([...frame(variants.read_failed).querySelectorAll('.home-dispatch-count')].map(el=>el.textContent),['1','2','2']);
assert.deepEqual([...frame({...variants.read_failed,slots:[]}).querySelectorAll('.home-dispatch-count')].map(el=>el.textContent),['—','—','—']);
assert.deepEqual(m.parseDispatchProjects({items:projects,total:2}),projects);
assert.deepEqual(m.parseDispatchProjects({items:projects,total:3}),null);
assert.deepEqual(m.parseDispatchProjects({items:[{id:'recSecret'}],total:1}),null);
assert.equal(frame(variants.empty_future_window).body.textContent.includes('2026-08-19 之後沒有預排紀錄'),true);
assert.equal(frame(undefined,'failed').body.textContent.includes('派工資料讀取失敗'),true);
assert.equal(frame(undefined).querySelector('[aria-busy="true"]')!==null,true);
assert.equal(frame({...variants.stale,source:{...variants.stale.source,quality:{states:['stale'],age_seconds:7200}}}).body.textContent.includes('120 分鐘前'),true);
assert.equal(frame(variants.forbidden).body.textContent.includes('recSynthetic'),false);
console.log('Home dispatch literal access, v2 layout, case routes and rendered source states passed.');

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=dashboard',pretendToBeVisual:true});
for(const key of ['window','document','location','history','Event','HTMLElement','localStorage','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
dom.window.scrollTo=()=>{};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const root=createRoot(document.getElementById('root'));
let dispatchStatus=200,dispatchBody=variants.loaded,dispatchCalls=0;
globalThis.fetch=async(url)=>{
 const q=new URL(url,'http://localhost').searchParams;
 if(String(url).includes('/dispatch/board')){dispatchCalls++;const body=structuredClone(dispatchBody);body.window={from:q.get('from'),to:q.get('to'),tz:'Asia/Taipei'};return new Response(JSON.stringify(dispatchStatus===200?body:{detail:'failure'}),{status:dispatchStatus})}
 if(String(url).includes('company-dashboard'))return new Response(JSON.stringify({as_of:'2026-10-18',source:{status:'ready'},complete:true,totals:{execution_status_counts:{},tasks_overdue:0,pending_local_reviews:0,pending_native_reviews:0},groups:[],cases:[]}));
 if(String(url).includes('reports/home'))return new Response('{}',{status:403});
 if(String(url).includes('attendance'))return new Response(JSON.stringify({status:'not-connected'}));
 return new Response(JSON.stringify({panel:q.get('panel'),scope:q.get('scope'),readState:'ready',snapshot_version:'test',as_of:null,freshness:{status:'fresh',last_success_at:null,refreshing:false},counts:{node_assignments:0,tasks:0,local_workflow:0,complete:true},items:[],next_cursor:null,has_more:false,complete:true,total_count:0,manager_view_available:true}));
};
const c={go(){},refresh:async()=>{},s:{...session,user:{id:'pm',name:'測試',role:'pm'}},w:{version:1,scope:'shell',projects:[],users:[]}};
const render=async(context=c)=>{await act(async()=>root.render(React.createElement(m.UnifiedHome,{c:context})));await act(async()=>new Promise(resolve=>setTimeout(resolve,10)))};
const click=async(label,scope=document)=>{await act(async()=>[...scope.querySelectorAll('button')].find(button=>button.textContent.trim()===label).click());await act(async()=>new Promise(resolve=>setTimeout(resolve,10)))};
try{
 await render();assert.deepEqual([...document.querySelectorAll('.home-dispatch-count')].map(el=>el.textContent),['1','2','2']);
 for(const label of ['分配工作','我的工作','全公司']){await click(label);assert.equal(document.querySelector('[data-home-card=dispatch] h3').textContent,'派工看板')}
 dispatchStatus=500;await click('重新讀取',document.querySelector('[data-home-card=dispatch]'));
 assert.equal(document.querySelector('.home-dispatch-summary').dataset.dispatchState,'retained');
 assert.equal(document.querySelector('[data-home-card=confirmation] h3').textContent,'待我確認');
 assert.deepEqual([...document.querySelectorAll('.home-dispatch-count')].map(el=>el.textContent),['1','2','2']);
 dispatchStatus=403;await click('重試',document.querySelector('[data-home-card=dispatch]'));
 assert.deepEqual([...document.querySelectorAll('.home-dispatch-count')].map(el=>el.textContent),['—','—','—']);
 const before=dispatchCalls;
 await render({...c,s:{...c.s,features:{dispatch_board:false}}});assert.equal(document.querySelector('[data-home-card=dispatch]'),null);assert.equal(dispatchCalls,before);
 await render({...c,s:{...c.s,user:{id:'member',role:'member'}}});assert.equal(document.querySelector('[data-home-card=dispatch]'),null);assert.equal(dispatchCalls,before);
 for(const [role,expected] of [['pm',true],['manager',true],['member',false]]){
  await act(async()=>root.render(React.createElement(m.AppShell,{s:{...c.s,user:{name:'測試',role}},route:{view:'dashboard'},error:'',ready:true,go(){},children:null})));
  assert.equal(document.querySelector('.workspace-nav-groups').textContent.includes('派工看板'),expected);
 }
}finally{await act(async()=>root.unmount());dom.window.close()}
console.log('Home dispatch mounted views, independent HTTP failure, 403 clearing, feature/role request gates and navigation passed.');
