import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','HTMLElement','Node','Element','DOMException','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
HTMLElement.prototype.scrollIntoView=function(){};
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {OverviewTaskRow} from './src/OverviewTaskRow';export {ProjectOverview} from './src/ProjectOverview';export {parseOverview} from './src/sopTaskApi';export {useNodeAssignments} from './src/useNodeAssignments';export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.overview-row-test.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const examples=JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8'));
const response=(body,status=200)=>new Response(JSON.stringify(body),{status});
let root,calls,reloads,applied,route,release,writeStatus,row;
const tick=()=>new Promise(r=>setTimeout(r,5));
const flush=fn=>act(async()=>{fn?.();await tick()});
const key=(element,key)=>element.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true}));
const byText=text=>[...document.querySelectorAll('button')].find(b=>b.textContent===text);
async function mount({source='sop',assign=true,due=null}={}){
 ui.invalidateSessionEpoch();calls=[];reloads=0;applied=[];route=null;release=null;writeStatus=200;
 const fixture=assignmentFixture();fixture.detail.tasks[0].assignee=null;fixture.detail.tasks[0].can.assign=assign;fixture.detail.tasks[0].can.edit_details=assign;fixture.list.node_details={control:fixture.detail};
 const task={...ui.parseOverview(examples.sop_tasks).tasks[0],id:'sop-1',title:'現場核對',participants:{executor:'old',checker:'checker'},allowedActions:assign?['edit']:[],revision:7,dueDate:due,state:'blocked',overdue:!!due};
 row={id:'row',kind:source==='sop'?'sopTask':'larkTask',source:source==='sop'?'sop_local':'lark',task:source==='sop'?task:{...fixture.detail.tasks[0],assignee:null,can:{...fixture.detail.tasks[0].can,assign,edit_details:assign}},revision:source==='sop'?7:'9b0c1d2e3f405162',permissions:source==='sop'?task.allowedActions:{...fixture.detail.tasks[0].can,assign,edit_details:assign},title:'現場核對',owner:'原執行人',ownerId:source==='sop'?'old':'',deadline:due,target:{tab:'flow',node:'control',task:source==='sop'?'sop-1':'recTask1',...(source==='sop'?{task_source:'sop_local'}:{})},node:{key:'control',label:'控制',tasks:{done:2,total:5},progress:{basis:'tasks'}},primary:false};
 globalThis.fetch=async(url,init={})=>{
  const call={url:String(url),method:init.method||'GET',body:init.body?JSON.parse(init.body):null};calls.push(call);
  if(call.method==='PATCH'){
   if(release)await release.promise;
   if(writeStatus!==200)return response({code:writeStatus===409?(source==='sop'?'task_revision_conflict':'revision_conflict'):'invalid',detail:'無法儲存'},writeStatus);
   if(source==='lark'){const updated=structuredClone(fixture.detail);updated.tasks[0].assignee={open_id:'new',name:'新執行人'};return response(updated)}
   const wire=structuredClone(examples.sop_tasks.tasks[0]);wire.id='sop-1';wire.participants=call.body.participants;wire.revision=8;
   return response({task_id:'sop-1',revision:8,checklist_revision:9,task:wire});
  }
  if(call.url.includes('sop-assignees'))return response({people:[{id:'new',name:'新執行人',teams:['控制']}],next_cursor:null});
  if(call.url.endsWith('/node-assignments'))return response(fixture.list);
  return response(fixture.list);
 };
 const sop={current:()=>true,reload:async()=>{reloads++},applyTask:(...args)=>applied.push(args)};
 function Harness(){const assignments=ui.useNodeAssignments('p1',source==='lark');const saved=assignments.state.kind==='ready'?assignments.state.data.node_details?.control?.tasks[0]:null;const displayed=source==='lark'&&saved?{...row,task:saved,ownerId:saved.assignee?.open_id||'',owner:saved.assignee?.name||'未指派',revision:saved.revision,permissions:saved.can}:row;return React.createElement('ul',null,React.createElement(ui.OverviewTaskRow,{row:displayed,projectId:'p1',today:'2026-10-28',sop,assignments,go:target=>{route=target},href:'#detail'}))}
 root=createRoot(document.getElementById('root'));await flush(()=>root.render(React.createElement(Harness)));
}
async function pick(){await flush(()=>document.querySelector('[aria-haspopup="listbox"]').click());await flush(()=>document.querySelector('[role="option"][aria-selected="false"]:last-child').click())}
afterEach(async()=>{if(root)await act(async()=>root.unmount());root=null});
test('SOP inline assignment PATCH preserves other roles, revision, receipt and focus',async()=>{
 await mount();await pick();
 assert.deepEqual(calls.find(c=>c.method==='PATCH'),{url:'/api/projects/p1/sop-tasks/sop-1',method:'PATCH',body:{expected_revision:7,participants:{executor:'new',checker:'checker'}}});
 assert.equal(applied[0][0].participants.executor,'new');assert.equal(applied[0][0].revision,8);assert.equal(applied[0][1],9);assert.equal(reloads,0);
 assert.equal(document.activeElement.getAttribute('aria-haspopup'),'listbox');assert.match(document.body.textContent,/已更新負責人/);assert.match(document.body.textContent,/受阻/);assert.match(document.body.textContent,/節點 2\/5 已完成/);
});
test('permission denied rows have plain assignee and date; no picker or edit',async()=>{
 await mount({assign:false});assert.equal(document.querySelector('[aria-haspopup="listbox"]'),null);assert.match(document.body.textContent,/原執行人/);assert.match(document.body.textContent,/未排定日期/);assert.equal(byText('排定日期'),undefined);
 await flush(()=>document.querySelector('[aria-haspopup="menu"]').click());assert.equal(document.querySelector('[role="menuitem"]').textContent,'查看詳情');
});
test('saving blocks a second change without dropping focus; errors remain inline',async()=>{
 await mount();let done;release={promise:new Promise(r=>done=r)};writeStatus=422;await pick();
 assert.equal(document.querySelector('[aria-busy="true"]')?.tagName,'LI');assert.equal(document.querySelector('[role="status"]').textContent,'儲存中…');assert.equal(document.activeElement.getAttribute('aria-haspopup'),'listbox');
 await flush(()=>document.querySelector('[aria-haspopup="listbox"]').click());assert.equal(document.querySelector('[role="listbox"]'),null);assert.equal(calls.filter(c=>c.method==='PATCH').length,1);
 await flush(()=>done());assert.ok(document.querySelector('[role="alert"]'));assert.equal(document.querySelector('[aria-busy="true"]'),null);
});
test('SOP revision conflict reloads that source exactly once and asks for a fresh choice',async()=>{
 await mount();writeStatus=409;await pick();assert.equal(reloads,1);assert.equal(applied.length,0);assert.equal(calls.filter(c=>c.method==='PATCH').length,1);assert.equal(document.querySelector('[role="alert"]').textContent,'資料已被他人更新，已重新載入，請重新選擇負責人');
});
test('Lark row uses existing mutation endpoint with its own revision and applies returned detail',async()=>{
 await mount({source:'lark'});assert.equal(byText('指派').textContent,'指派');await pick();
 const call=calls.find(c=>c.method==='PATCH');assert.equal(call.url,'/api/projects/p1/node-assignments/nodes/control/tasks/recTask1');assert.equal(call.body.expected_revision,'9b0c1d2e3f405162');assert.equal(call.body.assignee_open_id,'new');assert.equal(typeof call.body.request_id,'string');assert.equal(applied.length,0);assert.match(document.body.textContent,/已更新負責人/);assert.equal(byText('新執行人').textContent,'新執行人');
});
test('Lark revision conflict reloads once through the existing mutation hook',async()=>{
 await mount({source:'lark'});const before=calls.filter(c=>c.method==='GET'&&c.url.endsWith('/node-assignments')).length;writeStatus=409;await pick();
 assert.equal(calls.filter(c=>c.method==='GET'&&c.url.endsWith('/node-assignments')).length,before+1);assert.equal(calls.filter(c=>c.method==='PATCH').length,1);assert.equal(document.querySelector('[role="alert"]').textContent,'資料已被他人更新，已為你重新載入');assert.equal(reloads,0);
});
test('menu arrows, Escape and focus return; details and unscheduled action reuse task route',async()=>{
 await mount({due:'2026-10-20'});assert.match(document.body.textContent,/2026-10-20已逾期/);
 const trigger=document.querySelector('[aria-haspopup="menu"]');await flush(()=>key(trigger,'ArrowDown'));assert.equal(trigger.getAttribute('aria-expanded'),'true');assert.equal(document.activeElement.getAttribute('role'),'menuitem');
 await flush(()=>key(document.activeElement,'ArrowUp'));assert.equal(document.activeElement.textContent,'編輯詳情');await flush(()=>key(document.activeElement,'Escape'));assert.equal(document.activeElement,trigger);assert.equal(document.querySelector('[role="menu"]'),null);
 await flush(()=>trigger.click());await flush(()=>document.querySelector('[role="menuitem"]').click());assert.deepEqual(route,{tab:'flow',node:'control',task:'sop-1',task_source:'sop_local'});assert.equal(document.activeElement,trigger);
});

test('overview keeps suggestions distinct and count equals visible SOP plus Lark rows on remote nodes',async()=>{
 ui.invalidateSessionEpoch();const {list,detail}=assignmentFixture(),{project,user,workspace}=projectFixture();
 list.node_details=Object.fromEntries(list.nodes.map(n=>[n.key,{tasks:n.key==='control'?detail.tasks:[],assignable_people:[]}]));
 const sopData=ui.parseOverview(examples.sop_tasks);sopData.localNodes=[];sopData.tasks=[{...sopData.tasks[0],id:'s1',state:'pending',applicability:'applicable',nodes:[{node_key:'control'}],allowedActions:['edit']}];sopData.nodeCounts.control={done:0,total:1};
 const progress=JSON.parse(await fs.readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
 globalThis.fetch=async url=>response(String(url).includes('/progress')?progress:list);
 const sop={state:{kind:'ready',data:sopData,refreshing:false},assignees:[],current:()=>true,applyTask:()=>{},reload:async()=>{}};
 const assignments={state:{kind:'ready',data:list},revision:1,refreshing:false,pending:'',error:null,notice:'',mutate:async()=>true,reload:async()=>{}};
 const c={w:workspace,s:{user,features:{}},route:{view:'project',project:'p1',tab:'overview'},go:()=>{}};
 root=createRoot(document.getElementById('root'));await flush(()=>root.render(React.createElement(ui.ProjectOverview,{c,p:project,assignments,selectedKey:'control',sopTasks:sop,workbench:null})));
 assert.equal(document.querySelectorAll('.po-task-row').length,2);assert.equal([...document.querySelectorAll('button')].find(b=>b.textContent.startsWith('查看全部任務')).textContent,'查看全部任務 (2) →');
 assert.ok(document.querySelector('.po-recommendation'));assert.equal(document.querySelector('.po-recommendation [aria-haspopup="listbox"]'),null);assert.equal(document.querySelector('.po-recommendation .ds-badge').textContent,'建議');
});

test('unassigned Lark row without server assignment permission is plain text',async()=>{
 await mount({source:'lark',assign:false});assert.equal(document.querySelector('[aria-haspopup="listbox"]'),null);assert.match(document.body.textContent,/未指派/);assert.equal(byText('排定日期'),undefined);
});
test('unscheduled permitted task opens existing editor from date action',async()=>{
 await mount();await flush(()=>byText('排定日期').click());assert.deepEqual(route,{tab:'flow',node:'control',task:'sop-1',task_source:'sop_local'});
});
test('overview reads remote task details when summary has no embedded task payload',async()=>{
 ui.invalidateSessionEpoch();const {list,detail}=assignmentFixture(),{project,user,workspace}=projectFixture();const reads=[];
 globalThis.fetch=async url=>{reads.push(String(url));const key=String(url).split('/').at(-1);if(String(url).includes('/nodes/'))return response({...detail,node:{...detail.node,key},tasks:key==='control'?detail.tasks:[]});return response({detail:'unavailable'},503)};
 const data=ui.parseOverview(examples.sop_tasks);data.tasks=[];data.localNodes=[];for(const count of Object.values(data.nodeCounts)){count.total=0;count.done=0}
 const sop={state:{kind:'ready',data,refreshing:false},assignees:[],current:()=>true,applyTask:()=>{},reload:async()=>{}};
 const assignments={state:{kind:'ready',data:list},revision:1,refreshing:false,pending:'',error:null,notice:'',mutate:async()=>true,reload:async()=>{}};
 const c={w:workspace,s:{user,features:{}},route:{view:'project',project:'p1',tab:'overview'},go:()=>{}};
 root=createRoot(document.getElementById('root'));await flush(()=>root.render(React.createElement(ui.ProjectOverview,{c,p:project,assignments,selectedKey:'control',sopTasks:sop,workbench:null})));
 assert.equal(reads.filter(url=>url.includes('/nodes/')).length,9);assert.equal(document.querySelectorAll('.po-task-row').length,1);assert.equal([...document.querySelectorAll('button')].find(b=>b.textContent.startsWith('查看全部任務')).textContent,'查看全部任務 (1) →');assert.match(document.querySelector('.po-task-row').textContent,/控制點成果核對/);
});
