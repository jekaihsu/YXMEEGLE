import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink,readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {assignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=work&tab=assigned',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;window.scrollTo=()=>{};
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {WorkPage} from './src/IntegratedPages';export {AssignmentTaskInspector} from './src/AssignmentTaskInspector';export {SopTaskInspector} from './src/SopTaskInspector';export {parseOverview} from './src/sopTaskApi';export {mutateNodeAssignment} from './src/nodeAssignmentApi';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.work-nonempty-test.mjs',import.meta.url);await writeFile(path,bundle.outputFiles[0].text);const ui=await import(path.href);await unlink(path);
const examples=JSON.parse(await readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8'));
const tick=()=>new Promise(resolve=>setTimeout(resolve,20));
const edit=async(label,value)=>act(async()=>{const element=document.querySelector(`[aria-label="${label}"]`);assert.ok(element,label);Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element),'value').set.call(element,value);element.dispatchEvent(new Event(element.tagName==='SELECT'?'change':'input',{bubbles:true}));});
for(const panel of ['assigned','delegated','local']){
 history.replaceState(null,'',`#view=work&tab=${panel}`);
 const root=createRoot(document.getElementById('root'));
 const fixture=assignmentFixture();let task=fixture.detail.tasks[0];
 let raw={...structuredClone(examples.sop_tasks),tasks:[{...structuredClone(examples.sop_tasks.tasks[0]),id:'local-task',title:'原 SOP 任務',instructions:'原備註',participants:{executor:'u1'},allowed_actions:['edit','start'],local:{...examples.sop_tasks.tasks[0].local,due_date:'2026-11-01',date_status:'manual'}}]};
 let local=ui.parseOverview(raw).tasks[0];let opened=false;let version=1;const writes=[];const reads=[];
 const person={id:'u1',name:'甲',avatar_url:null};
 const title=()=>panel==='local'?local.title:task.title;
 const target=panel==='local'?{view:'project',project:'p1',tab:'flow',task:'local-task',task_source:'sop_local',section:'assigned-sop'}:{view:'project',project:'p1',tab:'flow',assignment_node:'control',assignment_task:task.id};
 const body=()=>({panel,scope:'mine',readState:'ready',snapshot_version:String(version),as_of:null,freshness:{status:'fresh',last_success_at:null,refreshing:false},counts:{node_assignments:0,tasks:panel==='local'?0:1,local_workflow:0,sop_tasks:panel==='local'?1:0,complete:true},items:[{id:'work-task',kind:panel==='local'?'sop_task':'task',origin:panel==='local'?'sop_local':'lark',title:title(),status:'todo',source_status:null,case:{id:'p1',code:'C001',name:'QA 案件',relation_state:'verified'},assignees:[person],assigned_by:person,assignment_state:'assigned',deadline:'2026-11-01',next_due:null,original_deadline:null,deadline_basis:'task',can_execute:true,blocked_reasons:[],target,detail:'原備註',overdue:false,due_today:false}],next_cursor:null,has_more:false,complete:true,total_count:1,manager_view_available:false});
 const json=body=>new Response(JSON.stringify(body),{headers:{'content-type':'application/json'}});
 globalThis.fetch=async(url,init={})=>{
  if(!init.method||init.method==='GET'){reads.push(url);return json(body())}
  const payload=JSON.parse(init.body);writes.push({url,payload});
  if(panel==='local'){
   raw.tasks[0]={...raw.tasks[0],title:payload.title,instructions:payload.instructions,participants:payload.participants,revision:2,local:{...raw.tasks[0].local,due_date:payload.due_date,date_reason:payload.reason}};local=ui.parseOverview(raw).tasks[0];
   return json({task_id:'local-task',revision:2,checklist_revision:2});
  }
  task={...task,title:payload.title,detail:payload.detail,deadline:payload.deadline,assignee:{open_id:payload.assignee_open_id,name:'乙'},status:payload.status,revision:'abcdef1234567890'};
  return json({...fixture.detail,tasks:[task]});
 };
 const sop={assignees:[{id:'u1',name:'甲'},{id:'u2',name:'乙'}],state:{kind:'ready',data:ui.parseOverview(raw),refreshing:false},current:()=>true,reload:async()=>render()};
 const c={route:{view:'work',tab:panel},w:{version:1},s:{workspace_id:`nonempty-${panel}`,features:{node_assignment:true},user:{id:'u1',role:'manager'}},reloadVersion:version,refresh:async()=>{},go:route=>{assert.deepEqual(route,panel==='local'?{...target,node:undefined}:{view:'project',project:'p1',tab:'flow',node:'control',task:task.id});opened=true;render()}};
 function render(){root.render(opened?panel==='local'?React.createElement(ui.SopTaskInspector,{task:local,project:{id:'p1'},users:sop.assignees,sop,onClose:()=>{}}):React.createElement(ui.AssignmentTaskInspector,{assignment:task,people:[{open_id:'u2',name:'乙',departments:['控制']}],nodeLabel:'控制',nodeKey:'control',busy:false,reason:'',onClose:()=>{},mutate:async mutation=>{await ui.mutateNodeAssignment('p1',mutation,new AbortController().signal,()=>true,'qa-save');render();return true}}):React.createElement(ui.WorkPage,{c:{...c,reloadVersion:version}}))}
 try{
  await act(async()=>{render();await tick()});await act(tick);
  assert.equal(document.querySelectorAll('tbody tr').length,1);
  assert.match(document.querySelector('tbody').textContent,/QA 案件/);
  const open=[...document.querySelectorAll('tbody button')].find(button=>button.textContent=== (panel==='local'?'開啟任務':'開啟案件'));
  await act(async()=>open.click());
  await edit('任務名稱',`更新 ${panel}`);await edit('任務備註','已核對備註');await edit('任務負責人','u2');await edit('任務期限','2026-11-03');
  if(panel==='local')await edit('期限變更原因','配合現場');else await edit('任務狀態','待處理');
  await act(async()=>{document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await tick()});
  assert.equal(writes.length,1);
  if(panel==='local')assert.deepEqual(writes[0],{url:'/api/projects/p1/sop-tasks/local-task',payload:{expected_revision:1,title:'更新 local',instructions:'已核對備註',participants:{executor:'u2'},due_date:'2026-11-03',reason:'配合現場'}});
  else assert.deepEqual(writes[0],{url:'/api/projects/p1/node-assignments/nodes/control/tasks/recTask1',payload:{title:`更新 ${panel}`,assignee_open_id:'u2',deadline:'2026-11-03',detail:'已核對備註',status:'待處理',expected_revision:'9b0c1d2e3f405162',request_id:'qa-save'}});
  opened=false;version++;await act(async()=>{render();await tick()});
  assert.match(document.querySelector('tbody').textContent,new RegExp(`更新 ${panel}`));
  assert.equal(reads.length,2);
 }finally{await act(async()=>root.unmount())}
}
dom.window.close();
console.log('PASS nonempty assigned, delegated and local work lists open editors, save exact payloads and reload saved titles');
