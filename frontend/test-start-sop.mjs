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
const bundle=await build({stdin:{contents:"export * from './src/startSop';export {defaultChecklistState} from './src/sopTaskModel';export {useStartSop} from './src/useStartSop';export {SopControls,PlanLine} from './src/StartSopControls';export {EnsureSopStatus} from './src/EnsureSopStatus';export {useEnsureSop} from './src/useEnsureSop';export {invalidateSessionEpoch} from './src/api';",resolveDir:new URL('.',import.meta.url).pathname},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
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
test('start controls label node existence and template preview separately',async()=>{
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.SopControls,{sop:{state:{kind:'ready',data:{already_started:false}}}})));
 assert.equal(document.querySelector('button'),null);assert.equal(document.body.textContent,'');
 await act(async()=>root.render(React.createElement(ui.SopControls,{sop:{state:{kind:'ready',data:{already_started:true,seeds_pending:4}}}})));
 assert.equal(document.body.textContent,'流程節點已建立範本預覽 4 項（尚未建立為任務）');assert.equal(document.querySelector('button'),null);
});
test('preview parser still rejects malformed data and preserves plan quantities',()=>{
 assert.equal(ui.parseSopPreview(previewFixture()).nodes[0].planned_qty,'123.4500');
 assert.throws(()=>ui.parseSopPreview({...previewFixture(),nodes:[{}]}));
});

test('parser rejects malformed data and duplicate production nodes',()=>{assert.equal(ui.parseSopPreview(previewFixture()).nodes.length,4);const exponent=previewFixture();exponent.nodes[0].planned_qty='1.23e2';assert.equal(ui.parseSopPreview(exponent).nodes[0].planned_qty,'1.23e2');for(const patch of [{eligible:1},{nodes:[{}]},{blockers:null},{nodes:[previewFixture().nodes[0],previewFixture().nodes[0]]}])assert.throws(()=>ui.parseSopPreview({...previewFixture(),...patch}));});
test('preview parser keeps the optional seed_tasks echo and rejects a non-boolean',()=>{assert.equal(ui.parseSopPreview({...previewFixture(),seed_tasks:true}).seed_tasks,true);assert.equal(ui.parseSopPreview(previewFixture()).seed_tasks,undefined);assert.throws(()=>ui.parseSopPreview({...previewFixture(),seed_tasks:'yes'}),/啟動預覽格式不正確/)});
test('nodes-only result message talks about nodes, not tasks',()=>{const result=ui.parseSopResult({started:true,complete:true,overview:{},results:[{key:'field',node:'created',task:'skipped',error:null},{key:'control',node:'existing',task:'skipped',error:null}]});assert.equal(ui.sopResultMessage(result,previewFixture()),'已啟動 SOP。外業：節點已建立、控制：節點已存在');assert.equal(ui.sopResultMessage({...result,started:false,results:[result.results[1]]},previewFixture()),'已啟動，無需再建立。控制：節點已存在')});
test('rate limit explains completed count and safe resume',()=>{assert.match(ui.sopResultMessage({complete:false,results:[{key:'field',node:'created',task:'created',error:null},{key:'control',node:'failed',task:'skipped',error:'rate_limited'}]},previewFixture()),/已完成 1 個節點.*稍後再按一次.*安全續做/)});
test('all backend failure codes have Chinese messages',()=>{assert.deepEqual(Object.fromEntries(['forbidden','preview_stale','rate_limited','lark_permission','lark_error','outcome_unknown','busy'].map(k=>[k,ui.SOP_ERRORS[k]])),{forbidden:'僅案件 PM、主管或節點主管可以啟動',preview_stale:'計畫已變更，請重新讀取預覽後確認。',rate_limited:'操作過於頻繁，請稍後再按一次，可安全續做。',lark_permission:'Lark 權限不足，請聯絡管理員。',lark_error:'Lark 寫入失敗，請稍後再試。',outcome_unknown:'上次建立結果不確定，請稍後再試',busy:'其他啟動操作進行中，請稍後再試。'})});
test('optional result parser keeps only literal contract values',()=>{const base={started:false,complete:false,overview:{},results:[{key:'field',node:'existing',task:'existing',error:null}]};for(const [sync,warning,expected] of [['ok','content_differs',{sync:'ok',warning:'content_differs'}],['failed',null,{sync:'failed'}],['unknown',42,{}],[{},[],{}],[undefined,undefined,{}]]){assert.deepEqual(ui.parseSopResult({...base,results:[{...base.results[0],sync,warning}]}).results,[{key:'field',node:'existing',task:'existing',error:null,...expected}])}});
test('pure result message excludes unsynced node from completed count',()=>{assert.equal(ui.sopResultMessage({started:true,complete:false,overview:{},results:[{key:'field',node:'created',task:'created',error:null,sync:'failed'}]},previewFixture()),'已完成 0 個節點。未完成：部分節點尚未建立。稍後再按一次可安全續做。\n外業：節點進度同步失敗，再按一次可補同步')});
test('preview parser carries seeds_pending and seeds_optional, defaults them for older servers and rejects bad types',()=>{const p=previewFixture();p.already_started=true;p.seeds_pending=4;p.seeds_optional=true;const parsed=ui.parseSopPreview(p);assert.equal(parsed.seeds_pending,4);assert.equal(parsed.seeds_optional,true);const old=previewFixture();delete old.seeds_pending;delete old.seeds_optional;const legacy=ui.parseSopPreview(old);assert.equal(legacy.seeds_pending,0);assert.equal(legacy.seeds_optional,false);for(const patch of [{seeds_pending:-1},{seeds_pending:'4'},{seeds_pending:1.5},{seeds_optional:'yes'}])assert.throws(()=>ui.parseSopPreview({...previewFixture(),...patch}),/啟動預覽格式不正確/)});

for(const allowed of [{import:true,manage:true,startAllNodes:true},{import:false,manage:false}])test(`legacy nodes without checklist stay unapplied and never write (${allowed.import})`,async()=>{
 ui.invalidateSessionEpoch();posts=[];
 globalThis.fetch=async(url,init={})=>{posts.push({url,method:init.method});throw new Error('No request expected')};
 root=createRoot(document.getElementById('root'));
 const props={c:{s:{features:{node_assignment:true}}},p:{id:'legacy',nodes:assignmentFixture().list.nodes},sop:{state:{kind:'ready',data:{tasks:[],enrollment:null,checklistRevision:0,allowed}},reload:async()=>{}},assignments:{reload:async()=>{}}};
 await act(async()=>root.render(React.createElement(ui.EnsureSopStatus,props)));
 assert.match(document.body.textContent,/預設清單尚未套用/);
 assert.match(document.body.textContent,/具備此節點匯入與管理權限.*匯入預設任務/);
 assert.doesNotMatch(document.body.textContent,/已啟動/);
 assert.equal(document.querySelector('button'),null);assert.deepEqual(posts,[]);
 await act(async()=>root.render(React.createElement(ui.EnsureSopStatus,{...props,sop:{...props.sop,state:{kind:'ready',data:{...props.sop.state.data,tasks:[{manual:false}]}}}})));
 assert.equal(document.body.textContent,'SOP 已啟動');assert.deepEqual(posts,[]);
});
test('checklist evidence distinguishes manual tasks, successful enrollment and uncertain revisions',()=>{
 const base={tasks:[],enrollment:null,checklistRevision:0};
 assert.equal(ui.defaultChecklistState(), 'unknown');
 assert.equal(ui.defaultChecklistState(base),'not-applied');
 assert.equal(ui.defaultChecklistState({...base,tasks:[{manual:true}]}),'not-applied');
 assert.equal(ui.defaultChecklistState({...base,enrollment:{policy:'managed',attempt:{status:'pending'}}}),'not-applied');
 assert.equal(ui.defaultChecklistState({...base,enrollment:{policy:'managed',attempt:{status:'succeeded'}}}),'applied');
 assert.equal(ui.defaultChecklistState({...base,checklistRevision:2}),'unknown');
 assert.equal(ui.defaultChecklistState({...base,enrollment:{policy:'needs_review'}}),'not-applied');
 assert.equal(ui.defaultChecklistState({...base,checklistRevision:2,enrollment:{policy:'legacy'}}),'not-applied');
});
