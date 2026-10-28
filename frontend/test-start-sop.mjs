import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture} from './fixtures/node-assignments.mjs';
const dom = new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const k of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','Element','HTMLElement','navigator']) Object.defineProperty(globalThis,k,{value:dom.window[k],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){};
HTMLElement.prototype.getClientRects=function(){return [{width:40,height:40}]};
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export * from './src/startSop';export {useStartSop} from './src/useStartSop';export {SopControls,PlanLine} from './src/StartSopControls';export {EnsureSopStatus} from './src/EnsureSopStatus';export {useEnsureSop} from './src/useEnsureSop';export {invalidateSessionEpoch} from './src/api';",resolveDir:new URL('.',import.meta.url).pathname},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.start-sop-test.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
export const previewFixture=()=>({project_id:'p1',code:'A115001',eligible:true,can_start:true,already_started:false,seeds_pending:4,seeds_optional:false,blockers:[],warnings:[{code:'derived_links',message:'依工編推導，非 Lark 關聯。',node:null}],nodes:Object.entries({field:'外業',control:'控制',mapping:'圖資',report:'報告'}).map(([key,label])=>({key,label,category:label,planned_qty:'123.4500',lines:2,items:5,items_basis:{native:1,derived:4,ambiguous:0,unlinked:0},deadline:null,node_exists:false,seed_task_exists:false,will_create_node:true,will_create_task:true,task_title:'開始作業',task_detail:''})),chain_note:'依工項交接，可並行處理。',preview_hash:'h1',plan_rule_version:'v1'});
let root, posts, reloads, reply, release;
const response=body=>new Response(JSON.stringify(body),{status:200});
const button=t=>[...document.querySelectorAll('button')].find(b=>b.textContent===t);
function Harness({mayStart=true,exists=false,id='p1'}={}) {
 const flow=ui.useEnsureSop(id,mayStart,exists,async()=>{reloads++});
 return React.createElement('div',null,flow.state.kind,flow.state.kind==='failed'&&React.createElement('button',{onClick:flow.retry},'重試'));
}
async function mount(props={},strict=false) {
 ui.invalidateSessionEpoch();posts=[];reloads=0;reply={state:'started'};release=null;
 globalThis.fetch=async(url,init)=>{posts.push({url,method:init.method});if(release)await release;return response(reply)};
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(strict?React.createElement(React.StrictMode,null,React.createElement(Harness,props)):React.createElement(Harness,props)));
}
afterEach(async()=>{if(root){await act(async()=>root.unmount());root=null}});
test('automatic ensure posts once and reloads on success',async()=>{
 await mount();assert.deepEqual(posts,[{url:'/api/projects/p1/sop/ensure',method:'POST'}]);assert.equal(reloads,1);assert.equal(document.body.textContent,'started');
 await act(async()=>root.render(React.createElement(Harness)));assert.equal(posts.length,1);
});
test('viewers and existing SOPs never post',async()=>{
 await mount({mayStart:false});assert.equal(posts.length,0);
 await act(async()=>root.render(React.createElement(Harness,{exists:true})));assert.equal(posts.length,0);
});
test('StrictMode and remount reuse the same attempt',async()=>{
 await mount({},true);assert.equal(posts.length,1);assert.equal(reloads,1);
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(Harness)));assert.equal(posts.length,1);assert.equal(document.body.textContent,'started');
});
test('failed ensure waits for explicit retry',async()=>{
 await mount({mayStart:false});reply={state:'not_ready',reason:'no_template'};
 await act(async()=>root.render(React.createElement(Harness)));assert.equal(posts.length,1);assert.equal(document.body.textContent,'failed重試');
 await act(async()=>root.render(React.createElement(Harness)));assert.equal(posts.length,1);
 reply={state:'started'};await act(async()=>button('重試').click());assert.equal(posts.length,2);assert.equal(reloads,1);
});
test('session changes permit a new attempt and suppress stale completion',async()=>{
 await mount({mayStart:false});release=new Promise(resolve=>{globalThis.finishEnsure=resolve});
 await act(async()=>root.render(React.createElement(Harness)));assert.equal(posts.length,1);assert.equal(document.body.textContent,'preparing');
 ui.invalidateSessionEpoch();await act(async()=>globalThis.finishEnsure());assert.equal(reloads,0);
 release=null;await act(async()=>root.render(React.createElement(Harness,{id:'p2'})));assert.equal(posts.length,2);assert.equal(reloads,1);
});
test('start controls keep the existing chip and render no start button',async()=>{
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.SopControls,{sop:{state:{kind:'ready',data:{already_started:false}}}})));
 assert.equal(document.querySelector('button'),null);assert.equal(document.body.textContent,'');
 await act(async()=>root.render(React.createElement(ui.SopControls,{sop:{state:{kind:'ready',data:{already_started:true}}}})));
 assert.equal(document.body.textContent,'SOP 已啟動');assert.equal(document.querySelector('button'),null);
});
test('preview parser still rejects malformed data and preserves plan quantities',()=>{
 assert.equal(ui.parseSopPreview(previewFixture()).nodes[0].planned_qty,'123.4500');
 assert.throws(()=>ui.parseSopPreview({...previewFixture(),nodes:[{}]}));
});

test('detail status shows preparing skeleton and one explicit retry link',async()=>{
 ui.invalidateSessionEpoch();posts=[];reloads=0;reply={state:'not_ready',reason:'no_template'};
 let finish;const pending=new Promise(resolve=>{finish=resolve});
 globalThis.fetch=async(url,init)=>{posts.push({url,method:init.method});await pending;return response(reply)};
 const props={c:{s:{features:{}}},p:{id:'p1',case_type:'intake'},sop:{state:{kind:'ready',data:{tasks:[],allowed:{import:true,startAllNodes:true}}},reload:async()=>{reloads++}},assignments:{reload:async()=>{}}};
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.EnsureSopStatus,props)));
 assert.match(document.body.textContent,/SOP 準備中/);assert.ok(document.querySelector('.skeleton'));assert.equal(posts.length,1);
 await act(async()=>finish());assert.equal(document.body.textContent,'SOP 尚未就緒重試');assert.equal(document.querySelectorAll('button').length,1);
 reply={state:'started'};await act(async()=>button('重試').click());assert.equal(posts.length,2);assert.equal(document.body.textContent,'SOP 已啟動');
});
test('parser rejects malformed data and duplicate production nodes',()=>{assert.equal(ui.parseSopPreview(previewFixture()).nodes.length,4);const exponent=previewFixture();exponent.nodes[0].planned_qty='1.23e2';assert.equal(ui.parseSopPreview(exponent).nodes[0].planned_qty,'1.23e2');for(const patch of [{eligible:1},{nodes:[{}]},{blockers:null},{nodes:[previewFixture().nodes[0],previewFixture().nodes[0]]}])assert.throws(()=>ui.parseSopPreview({...previewFixture(),...patch}));});
test('preview parser keeps the optional seed_tasks echo and rejects a non-boolean',()=>{assert.equal(ui.parseSopPreview({...previewFixture(),seed_tasks:true}).seed_tasks,true);assert.equal(ui.parseSopPreview(previewFixture()).seed_tasks,undefined);assert.throws(()=>ui.parseSopPreview({...previewFixture(),seed_tasks:'yes'}),/啟動預覽格式不正確/)});
test('nodes-only result message talks about nodes, not tasks',()=>{const result=ui.parseSopResult({started:true,complete:true,overview:{},results:[{key:'field',node:'created',task:'skipped',error:null},{key:'control',node:'existing',task:'skipped',error:null}]});assert.equal(ui.sopResultMessage(result,previewFixture()),'已啟動 SOP。外業：節點已建立、控制：節點已存在');assert.equal(ui.sopResultMessage({...result,started:false,results:[result.results[1]]},previewFixture()),'已啟動，無需再建立。控制：節點已存在')});
test('rate limit explains completed count and safe resume',()=>{assert.match(ui.sopResultMessage({complete:false,results:[{key:'field',node:'created',task:'created',error:null},{key:'control',node:'failed',task:'skipped',error:'rate_limited'}]},previewFixture()),/已完成 1 個節點.*稍後再按一次.*安全續做/)});
test('all backend failure codes have Chinese messages',()=>{assert.deepEqual(Object.fromEntries(['forbidden','preview_stale','rate_limited','lark_permission','lark_error','outcome_unknown','busy'].map(k=>[k,ui.SOP_ERRORS[k]])),{forbidden:'僅案件 PM、主管或節點主管可以啟動',preview_stale:'計畫已變更，請重新讀取預覽後確認。',rate_limited:'操作過於頻繁，請稍後再按一次，可安全續做。',lark_permission:'Lark 權限不足，請聯絡管理員。',lark_error:'Lark 寫入失敗，請稍後再試。',outcome_unknown:'上次建立結果不確定，請稍後再試',busy:'其他啟動操作進行中，請稍後再試。'})});
test('optional result parser keeps only literal contract values',()=>{const base={started:false,complete:false,overview:{},results:[{key:'field',node:'existing',task:'existing',error:null}]};for(const [sync,warning,expected] of [['ok','content_differs',{sync:'ok',warning:'content_differs'}],['failed',null,{sync:'failed'}],['unknown',42,{}],[{},[],{}],[undefined,undefined,{}]]){assert.deepEqual(ui.parseSopResult({...base,results:[{...base.results[0],sync,warning}]}).results,[{key:'field',node:'existing',task:'existing',error:null,...expected}])}});
test('pure result message excludes unsynced node from completed count',()=>{assert.equal(ui.sopResultMessage({started:true,complete:false,overview:{},results:[{key:'field',node:'created',task:'created',error:null,sync:'failed'}]},previewFixture()),'已完成 0 個節點。未完成：部分節點尚未建立。稍後再按一次可安全續做。\n外業：節點進度同步失敗，再按一次可補同步')});
test('preview parser carries seeds_pending and seeds_optional, defaults them for older servers and rejects bad types',()=>{const p=previewFixture();p.already_started=true;p.seeds_pending=4;p.seeds_optional=true;const parsed=ui.parseSopPreview(p);assert.equal(parsed.seeds_pending,4);assert.equal(parsed.seeds_optional,true);const old=previewFixture();delete old.seeds_pending;delete old.seeds_optional;const legacy=ui.parseSopPreview(old);assert.equal(legacy.seeds_pending,0);assert.equal(legacy.seeds_optional,false);for(const patch of [{seeds_pending:-1},{seeds_pending:'4'},{seeds_pending:1.5},{seeds_optional:'yes'}])assert.throws(()=>ui.parseSopPreview({...previewFixture(),...patch}),/啟動預覽格式不正確/)});

test('opening a local case on a tab without an active SOP read still ensures it',async()=>{
 ui.invalidateSessionEpoch();posts=[];
 const examples=JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8'));
 const overview={...examples.sop_tasks,project_id:'direct-tab',tasks:[],allowed_actions:{import:true,manage:true,work:true,start_all_nodes:true}};
 globalThis.fetch=async(url,init={})=>{
  if(init.method==='POST'){posts.push(url);return response({state:'started'})}
  return response(url.endsWith('/sop-assignees')?{people:[],restricted:false}:overview);
 };
 const props={c:{s:{workspace_id:'w',features:{}}},p:{id:'direct-tab',case_type:'intake'},sop:{state:{kind:'forbidden'},reload:async()=>{}},assignments:{reload:async()=>{}}};
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.EnsureSopStatus,props)));
 assert.deepEqual(posts,['/api/projects/direct-tab/sop/ensure']);assert.equal(document.body.textContent,'SOP 已啟動');
});

test('single-node managers see passive authorization text and never ensure all nodes',async()=>{
 ui.invalidateSessionEpoch();posts=[];
 globalThis.fetch=async(url,init={})=>{posts.push({url,method:init.method});return response({state:'not_permitted'})};
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.EnsureSopStatus,{
  c:{s:{features:{}}},p:{id:'scoped-manager',case_type:'intake'},
  sop:{state:{kind:'ready',data:{tasks:[],allowed:{import:false}}},reload:async()=>{}},assignments:{reload:async()=>{}}
 })));
 assert.equal(document.body.textContent,'需由有權限的人員準備 SOP');assert.deepEqual(posts,[]);
});

for(const result of [{state:'not_ready',reason:'writes_disabled'},{state:'not_ready'}])test(`legacy coded case stays quiet for ${result.reason || result.state}`,async()=>{
 ui.invalidateSessionEpoch();posts=[];
 globalThis.fetch=async(url,init={})=>{posts.push({url,method:init.method});return response(result)};
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.EnsureSopStatus,{
  c:{s:{features:{node_assignment:false}}},p:{id:'legacy-case',code:'C001'},
  sop:{state:{kind:'ready',data:{tasks:[],allowed:{import:true,startAllNodes:true}}},reload:async()=>{}},assignments:{reload:async()=>{}}
 })));
 assert.equal(posts.length,1);assert.equal(document.body.textContent,'');assert.equal(document.querySelector('button'),null);
});

test('node-scoped import authority never triggers case-wide automatic ensure',async()=>{
 ui.invalidateSessionEpoch();posts=[];
 globalThis.fetch=async(url,init={})=>{posts.push(url);return response({state:'started'})};
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.EnsureSopStatus,{
  c:{s:{features:{}}},p:{id:'node-manager-review',case_type:'intake'},sop:{state:{kind:'ready',data:{tasks:[],allowed:{import:true,startAllNodes:false}}},reload:async()=>{}},assignments:{reload:async()=>{}}
 })));
 assert.deepEqual(posts,[]);assert.equal(document.body.textContent,'需由有權限的人員準備 SOP');
});
for(const result of [{state:'not_ready',reason:'no_startable_nodes'},{state:'already_started'}])test(`blocked enrollment status is passive while real SOP stays started: ${result.state}`,async()=>{
 ui.invalidateSessionEpoch();posts=[];
 globalThis.fetch=async(url,init={})=>{posts.push(url);return response(result)};
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.EnsureSopStatus,{
  c:{s:{features:{}}},p:{id:'blocked-enrollment',case_type:'intake'},sop:{state:{kind:'ready',data:{tasks:[],allowed:{import:true,startAllNodes:true}}},reload:async()=>{}},assignments:{reload:async()=>{}}
 })));
 assert.equal(document.body.textContent,result.state==='already_started'?'SOP 已啟動':'');assert.equal(document.querySelector('button'),null);
});
