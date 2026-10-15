import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture, projectFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=dashboard',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;
HTMLElement.prototype.scrollIntoView=function(){};
window.scrollTo=()=>{};
window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {default as App} from './src/App';export {AssignmentTable} from './src/MyWorkTable';export {parseRoute} from './src/api';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.home-target-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await fs.unlink(file)}
const {project,user,workspace}=projectFixture();const fixture=assignmentFixture();
fixture.detail.tasks.push({...fixture.detail.tasks[0],id:'recTask2',title:'子任務核對'});
const item={id:'task/field/recTask1',kind:'task',origin:'lark',title:'首頁外業任務',status:'in_progress',source_status:'進行中',case:{id:'p1',code:project.code,name:project.name,relation_state:'verified'},assignees:[],assigned_by:null,assignment_state:'assigned',deadline:null,next_due:null,original_deadline:null,deadline_basis:'lark_task_deadline',can_execute:true,blocked_reasons:[],target:{view:'project',project:'p1',tab:'flow',assignment_node:'field',assignment_task:'recTask1'},detail:null,overdue:false,due_today:false,children:[{id:'recTask2',title:'子任務核對',deadline:null,status:'進行中',assignee:null,detail:''}]};
const reply=body=>new Response(JSON.stringify(body),{status:200,headers:{'content-type':'application/json'}});
globalThis.fetch=async url=>{
 if(url==='/api/session')return reply({user,users:[user],mode:'lark',workspace_id:'test',features:{node_assignment:true}});
 if(url==='/api/workspace')return reply(workspace);
 if(url.includes('/node-assignments/nodes/'))return reply({...fixture.detail,node:fixture.list.nodes.find(n=>n.key==='field'),can:fixture.list.can.field});
 if(url.endsWith('/node-assignments'))return reply(fixture.list);
 if(url.includes('/home-panels')){const panel=new URL(url,'http://localhost').searchParams.get('panel');return reply({panel,scope:'mine',readState:'complete',snapshot_version:'v1',as_of:null,freshness:{status:'fresh',last_success_at:null,refreshing:false},counts:{node_assignments:0,tasks:1,local_workflow:0,complete:true},items:panel==='assigned'?[item]:[],next_cursor:null,has_more:false,complete:true,total_count:1,manager_view_available:false})}
 return reply({});
};
const root=createRoot(document.getElementById('root'));
const flush=async fn=>act(async()=>{fn?.();await new Promise(r=>setTimeout(r,30))});
try{
 await flush(()=>root.render(React.createElement(ui.App)));await flush();await flush();
 const open=[...document.querySelectorAll('button')].find(b=>b.textContent==='開啟案件');assert.ok(open,'home panel row is mounted by App');
 await flush(()=>open.click());await flush();
 assert.equal(ui.parseRoute(location.hash).node,'field','real App go preserves the home node through the hash');
 assert.equal(ui.parseRoute(location.hash).task,'recTask1','real App go preserves the task through the hash');
 await flush(()=>window.dispatchEvent(new Event('hashchange')));await flush();
 assert.equal(document.querySelector('.na-row[aria-label^="外業節點"]').getAttribute('aria-expanded'),'true');
 assert.match(document.activeElement.textContent,/控制點成果核對/,'ProjectDetail focuses the target task');
 await flush(()=>document.querySelector('a.brand').click());await flush();
 await flush(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='首頁外業任務').click());
 await flush(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='開啟任務').click());await flush();
 assert.equal(ui.parseRoute(location.hash).node,'field','child target retains its node');
 assert.equal(ui.parseRoute(location.hash).task,'recTask2','child target overrides the parent task');
 assert.equal(document.activeElement.getAttribute('data-assignment-task'),'recTask2');
 for(const tab of document.querySelectorAll('.project-tabs button'))assert.equal(window.getComputedStyle(tab).minWidth,'44px','project tabs retain the 44px width floor');
 await flush(()=>root.render(React.createElement(ui.AssignmentTable,{items:[],onNavigate(){}})));
 assert.equal(document.querySelector('[aria-label="工作表格，可左右捲動"]').getAttribute('role'),'region');
 console.log('PASS home panel click through real App go and parseRoute expands field and focuses recTask1');
}finally{await act(async()=>root.unmount())}
