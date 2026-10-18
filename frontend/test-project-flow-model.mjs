import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {assignmentFixture, projectFixture} from './fixtures/node-assignments.mjs';
const bundled=await build({stdin:{contents:"export * from './src/flowModel'; export {parseRoute} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
test('four old tabs keep node, task, completion and focus while selecting one workspace',()=>{
 for(const [tab,focus] of [['overview','top'],['progress','evidence'],['flow','node'],['tasks','tasks']]){
  const route=m.parseRoute(`#view=project&project=p1&tab=${tab}&node=control&task=recTask1&focus=t1&completion=node_control`);
  assert.deepEqual(m.projectFlowRoute(route),{tab:'flow',focus,allTasks:tab==='tasks'});
  assert.equal(route.node,'control');assert.equal(route.task,'recTask1');assert.equal(route.focus,'t1');assert.equal(route.completion,'node_control');
 }
 assert.deepEqual(m.projectFlowRoute({}),{tab:'flow',focus:'node',allTasks:false});
 assert.deepEqual(m.projectFlowRoute({tab:'daily'}),{tab:'daily',focus:'node',allTasks:false});
});
test('task basis excludes cancellation and superseded work and does not use opaque progress',()=>{
 const {list,detail}=assignmentFixture();const node=list.nodes.find(n=>n.key==='control');node.progress=.99;
 list.node_details={control:{tasks:[{...detail.tasks[0],id:'a',status:'已完成'},{...detail.tasks[0],id:'b',status:'進行中'},{...detail.tasks[0],id:'c',status:'取消'}],assignable_people:[]}};
 const flow=m.buildFlowModel({project:projectFixture().project,assignments:list,progress,today:'2026-10-21'});
 const n=flow.nodes.find(n=>n.key==='control');
 assert.deepEqual(n.tasks,{done:1,total:2});assert.deepEqual(n.progress,{basis:'tasks',percent:50,label:'Lark 任務完成度'});
 assert.equal(n.overdue,true);assert.equal(n.deadline,'2026-10-20');assert.equal(n.owners[0].name,'林安娜');
 assert.equal(flow.overall.percent,93);assert.equal(flow.overall.label,'Lark 任務完成度');
});
test('missing daily quantity remains unknown even with zero item counts and completed tasks',()=>{
 const {list}=assignmentFixture();const n=m.buildFlowModel({project:projectFixture().project,assignments:list,progress,today:'2026-10-21'}).nodes.find(n=>n.key==='field');
 assert.equal(n.quantity.actual,null);assert.equal(n.quantity.planned,'65');assert.match(n.quantity.reason,/未知|關聯|連結/);
 assert.equal(n.quantity.unit,null);assert.equal(n.progress.percent,100);assert.equal(n.progress.basis,'tasks');
 const empty=structuredClone(list);empty.nodes.forEach(n=>n.tasks={done:0,total:0});
 const unknown=m.buildFlowModel({project:projectFixture().project,assignments:empty,progress,today:'2026-10-21'}).nodes.find(n=>n.key==='field');
 assert.deepEqual(unknown.progress,{basis:'unknown',percent:null,label:'進度未知'});
});
test('known quantities retain unit text without adding unlike quantities',()=>{
 const p=structuredClone(progress);p.production.field.actual={known:true,value:'12.50',unit_note:'公尺',source:'v4_daily',reason:null};
 const n=m.buildFlowModel({project:projectFixture().project,progress:p,today:'2026-10-21'}).nodes.find(n=>n.key==='field');
 assert.equal(n.quantity.actual,'12.50');assert.equal(n.quantity.unit,'公尺');assert.equal(n.quantity.planned,'65');
 assert.equal(n.progress.percent,null);
});
test('legacy has one honest local-task number and source state never overwrites workflow authority',()=>{
 const project=projectFixture().project;project.nodes[3].tasks=[{id:'local1',status:'completed'},{id:'local2',status:'pending'},{id:'old',status:'superseded'}];
 const flow=m.buildFlowModel({project,progress,today:'2026-10-21'});
 assert.equal(flow.overall.percent,50);assert.equal(flow.overall.label,'本地流程任務完成度');assert.equal(flow.nodes[3].state,'已完成');
 assert.equal(m.buildFlowModel({project:{...project,nodes:[]},today:'2026-10-21'}).overall.percent,null);
});
test('task filters compose for mine, unassigned and overdue without hiding other source identities',()=>{
 const tasks=[{id:'a',nodeKey:'control',ownerId:'me',deadline:'2026-10-01',done:false},{id:'b',nodeKey:'field',ownerId:'',deadline:'2026-10-02',done:false},{id:'c',nodeKey:'control',ownerId:'me',deadline:'2026-10-01',done:true}];
 assert.deepEqual(m.filterFlowTasks(tasks,{node:'control',mine:true,unassigned:false,overdue:true,userId:'me',today:'2026-10-21'}).map(t=>t.id),['a']);
 assert.deepEqual(m.filterFlowTasks(tasks,{mine:false,unassigned:true,overdue:false,userId:'me',today:'2026-10-21'}).map(t=>t.id),['b']);
});
test('dispatch proposal uses stable case references and never treats the assignment row as parent obligation',()=>{
 const project={...projectFixture().project,project_ref:'project-native',confirmation_id:'recConfirmation'};
 assert.deepEqual(m.nodeDispatchProposal({project,node:{key:'field',label:'外業',departments:['外業組'],deadline:'2026-10-23'},parentTaskId:'recObligation'}),{
 project_ref:'project-native',case_ref:'recConfirmation',title:'南港基地測量與成果交付 · 外業',content:'',phase:'正式',kind:'execution',department:'外業組',parent_task_ref:'recObligation',deadline:'2026-10-23'
 });
});
