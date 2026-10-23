import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','Event','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export * from './src/useNodeAssignments'; export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const temp=new URL('./.node-assignments-test.mjs',import.meta.url);await fs.writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await fs.unlink(temp);
let root,latest,calls,fixture,status,hold,release;
const response=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
function Probe({id='p1',enabled=true}){latest=ui.useNodeAssignments(id,enabled);return React.createElement('output',null,JSON.stringify({kind:latest.state.kind,notice:latest.notice,error:latest.error?.code,pending:latest.pending,refreshing:latest.refreshing}))}
async function mount({preload=false,enabled=true,strict=false}={}){
 ui.invalidateSessionEpoch();fixture=assignmentFixture();status=200;calls=[];hold=null;
 globalThis.fetch=async(url,init={})=>{
  const call={url,method:init.method||'GET',body:init.body?JSON.parse(init.body):null};calls.push(call);
  if(call.method!=='GET'){
   if(hold)await hold;
   if(status!==200)return response({code:status===409?'revision_conflict':status===422?'invalid':status===403?'forbidden':'outcome_unknown',detail:status===422?{assignee_open_id:'請選擇在職人員'}:'合成寫入失敗'},status);
   return response({...fixture.detail,record_id:fixture.detail.node.record_id});
  }
  if(url.includes('/nodes/'))return response({...fixture.detail,node:{...fixture.detail.node,key:url.split('/').at(-1)}});
  return response(fixture.list);
 };
 if(preload)await ui.prefetchNodeAssignments('p1');
 root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(strict?React.createElement(React.StrictMode,null,React.createElement(Probe,{enabled})):React.createElement(Probe,{enabled})));
}
afterEach(async()=>{if(root){await act(async()=>root.unmount());root=null}});
const mutation={action:'update_task',nodeKey:'control',taskId:'recTask1',expected_revision:'9b0c1d2e3f405162',patch:{assignee_open_id:'ou_anna'}};
const writes=()=>calls.filter(c=>c.method!=='GET');
test('prefetch and StrictMode share one case request',async()=>{await mount({preload:true,strict:true});assert.equal(calls.length,1);assert.equal(latest.state.kind,'ready');assert.equal(latest.state.data.code,'A115001-01');await act(async()=>latest.reload());assert.equal(calls.length,2)});
test('feature off makes zero source requests and has an explicit disabled state',async()=>{await mount({enabled:false});assert.equal(calls.length,0);assert.equal(latest.state.kind,'disabled');await act(async()=>root.render(React.createElement(Probe,{enabled:true})));assert.equal(calls.length,1);assert.equal(latest.state.kind,'ready')});
test('person attachment uses the existing revision checked task PATCH and merges returned details',async()=>{await mount();let result;await act(async()=>{result=await latest.mutate(mutation)});assert.equal(result,true);assert.equal(writes()[0].url,'/api/projects/p1/node-assignments/nodes/control/tasks/recTask1');assert.equal(writes()[0].method,'PATCH');const {request_id,...body}=writes()[0].body;assert.deepEqual(body,{assignee_open_id:'ou_anna',expected_revision:'9b0c1d2e3f405162'});assert.match(request_id,/^[a-f0-9-]{36}$/);assert.equal(latest.notice,'已儲存變更。');assert.equal(latest.state.data.node_details.control.tasks[0].title,'控制點成果核對');assert.equal(calls.filter(c=>c.method==='GET').length,1)});
test('uncertain outcome retries the same request UUID and exact payload',async()=>{await mount();status=500;await act(async()=>latest.mutate(mutation));assert.equal(latest.error.code,'outcome_unknown');const first=writes()[0].body;status=200;await act(async()=>latest.retryMutation());assert.deepEqual(writes()[1].body,first);assert.equal(latest.notice,'已儲存變更。')});
test('double submits are blocked while mutation is pending',async()=>{await mount();hold=new Promise(r=>release=r);let pending;await act(async()=>{pending=latest.mutate(mutation)});assert.equal(latest.pending,'update_task');let second;await act(async()=>{second=await latest.mutate(mutation)});assert.equal(second,false);assert.equal(writes().length,1);await act(async()=>{release();await pending});assert.equal(latest.pending,'');assert.equal(latest.notice,'已儲存變更。')});
test('revision conflict refreshes and keeps the task authority server owned',async()=>{await mount();status=409;await act(async()=>latest.mutate(mutation));assert.equal(latest.notice,'資料已被他人更新，已為你重新載入');assert.equal(calls.filter(c=>c.method==='GET').length,2);assert.equal(latest.state.data.can.control.assign,true)});
test('field errors retain the form field name and a definite failure gets a new request id',async()=>{await mount();status=422;await act(async()=>latest.mutate(mutation));assert.equal(latest.error.fields.assignee_open_id,'請選擇在職人員');const first=writes()[0].body.request_id;status=200;await act(async()=>latest.mutate(mutation));assert.notEqual(writes()[1].body.request_id,first);assert.equal(latest.notice,'已儲存變更。')});
test('detail prefetch shares a pending request and a fresh result',async()=>{await mount();const [a,b]=await Promise.all([ui.prefetchNodeAssignmentDetail('p1','control'),ui.prefetchNodeAssignmentDetail('p1','control')]);assert.equal(a.tasks[0].title,'控制點成果核對');assert.equal(b.node.key,'control');await ui.prefetchNodeAssignmentDetail('p1','control');assert.equal(calls.filter(c=>c.url.includes('/nodes/')).length,1)});
test('an unmounted mutation does not replace the next case snapshot',async()=>{await mount();hold=new Promise(r=>release=r);let pending;await act(async()=>{pending=latest.mutate(mutation)});await act(async()=>root.render(React.createElement(Probe,{id:'p2'})));await act(async()=>{release();await pending});assert.equal(latest.state.kind,'ready');assert.equal(latest.notice,'');assert.equal(latest.state.data.node_details,undefined)});
test('session change clears cached list and details before the next mount',async()=>{await mount({preload:true});await ui.prefetchNodeAssignmentDetail('p1','control');await act(async()=>root.unmount());root=null;ui.invalidateSessionEpoch();const before=calls.length;root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(Probe)));assert.equal(calls.length,before+1);assert.equal(latest.state.kind,'ready');await ui.prefetchNodeAssignmentDetail('p1','control');assert.equal(calls.length,before+2)});

test('round2 forced detail replaces a pending read and keeps newest cached result',async()=>{
 await mount();let releaseOld;const old=structuredClone(fixture.detail);old.tasks[0].assignee={open_id:'old',name:'舊負責人'};
 let count=0;globalThis.fetch=async()=>{count++;if(count===1){await new Promise(r=>releaseOld=r);return response(old)}return response(fixture.detail)};
 const first=ui.prefetchNodeAssignmentDetail('p1','control');const forced=ui.prefetchNodeAssignmentDetail('p1','control',undefined,true);releaseOld();const fresh=await forced;
 assert.equal(fresh.tasks[0].assignee.name,'陳威廷');assert.equal(count,2);releaseOld();await first;
 assert.equal((await ui.prefetchNodeAssignmentDetail('p1','control')).tasks[0].assignee.name,'陳威廷');
});
test('round2 browsing refreshes while an assignment edit input defers refresh',async()=>{
 await mount();const wrap=document.createElement('div');wrap.className='node-assignments';wrap.innerHTML='<button>瀏覽節點</button><form class="assignment-edit"><input/></form>';document.body.append(wrap);
 wrap.querySelector('button').focus();await act(async()=>document.dispatchEvent(new Event('visibilitychange')));assert.equal(calls.length,2);
 wrap.querySelector('input').focus();await act(async()=>document.dispatchEvent(new Event('visibilitychange')));assert.equal(calls.length,2);
 wrap.remove();
});

test('round2 sixty-second refresh runs while browsing and waits for an edit input',async()=>{
 const original=window.setInterval;let refresh;window.setInterval=(fn,ms)=>{assert.equal(ms,60000);refresh=fn;return 1};
 try{await mount();const wrap=document.createElement('div');wrap.className='assignment-edit';wrap.innerHTML='<input/><button>瀏覽</button>';document.body.append(wrap);
 wrap.querySelector('button').focus();await act(async()=>refresh());assert.equal(calls.length,2);
 wrap.querySelector('input').focus();await act(async()=>refresh());assert.equal(calls.length,2);wrap.remove();
 }finally{window.setInterval=original}
});
