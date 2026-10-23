import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {assignmentFixture, projectFixture} from './fixtures/node-assignments.mjs';
const bundled=await build({stdin:{contents:"export * from './src/flowModel'; export {parseRoute} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
test('six tabs and every legacy tab preserve deep-link context',()=>{
 for(const [tab,destination,section] of [['overview','overview'],['flow','flow'],['tasks','flow','all-tasks'],['progress','items'],['daily','items','reports'],['logs','data','activity'],['files','files'],['data','data'],['items','items'],['people','people']]){
  const route=m.parseRoute(`#view=project&project=p1&tab=${tab}&node=control&task=recTask1&focus=t1&completion=node_control&approval=a1`);
  assert.equal(route.tab,destination);assert.equal(route.section,section);
  assert.equal(m.projectFlowRoute(route).tab,destination);assert.equal(m.projectFlowRoute(route).allTasks,tab==='tasks');
  assert.equal(route.node,'control');assert.equal(route.task,'recTask1');assert.equal(route.focus,'t1');assert.equal(route.completion,'node_control');assert.equal(route.approval,'a1');
 }
 assert.equal(m.parseRoute('#view=project&project=p1').tab,'overview');
 assert.equal(m.projectFlowRoute({}).tab,'overview');
 for(const param of ['node=field','task=t1','focus=t1'])assert.equal(m.parseRoute(`#view=project&project=p1&${param}`).tab,'flow');
 assert.equal(m.parseRoute('#view=project&project=p1&tab=data&section=files').tab,'files');
 const explicit=m.parseRoute('#view=project&project=p1&tab=logs&section=custom&node=field');assert.equal(explicit.section,'custom');
 const custom=m.parseRoute('#view=project&project=p1&tab=tasks&section=custom');assert.equal(custom.section,'custom');assert.equal(m.projectFlowRoute(custom).allTasks,true);assert.equal(m.projectFlowRoute(m.parseRoute('#'+new URLSearchParams(Object.entries(custom).filter(([,v])=>v)))).allTasks,true);
});
test('task basis excludes cancellation and superseded work and does not use opaque progress',()=>{
 const {list,detail}=assignmentFixture();const node=list.nodes.find(n=>n.key==='control');node.progress=.99;
 list.node_details={control:{tasks:[{...detail.tasks[0],id:'a',status:'已完成'},{...detail.tasks[0],id:'b',status:'進行中'},{...detail.tasks[0],id:'c',status:'取消'}],assignable_people:[]}};
 const flow=m.buildFlowModel({project:projectFixture().project,assignments:list,progress,today:'2026-10-21'});
 const n=flow.nodes.find(n=>n.key==='control');
 assert.deepEqual(n.tasks,{done:1,total:2});assert.deepEqual(n.progress,{basis:'tasks',percent:50,label:'Lark 任務完成度'});
 assert.equal(n.overdue,true);assert.equal(n.deadline,'2026-10-20');assert.equal(n.owners[0].name,'林安娜');
 assert.equal(flow.overall.percent,null);assert.equal(flow.overall.label,'部分節點進度未知（略過不計）');
});
test('missing daily quantity remains unknown even with zero item counts and completed tasks',()=>{
 const {list}=assignmentFixture();const n=m.buildFlowModel({project:projectFixture().project,assignments:list,progress,today:'2026-10-21'}).nodes.find(n=>n.key==='field');
 assert.equal(n.quantity.actual,null);assert.equal(n.quantity.planned,'65');assert.match(n.quantity.reason,/未知|關聯|連結/);
 assert.equal(n.quantity.unit,null);assert.equal(n.progress.percent,100);assert.equal(n.progress.basis,'nodes');
 const empty=structuredClone(list);empty.nodes.forEach(n=>n.tasks={done:0,total:0});
 const unknown=m.buildFlowModel({project:projectFixture().project,assignments:empty,progress,today:'2026-10-21'}).nodes.find(n=>n.key==='field');
 assert.deepEqual(unknown.progress,{basis:'nodes',percent:100,label:'節點已完成'});
 empty.nodes.find(n=>n.key==='field').derived_status='進行中';
 assert.deepEqual(m.buildFlowModel({project:projectFixture().project,assignments:empty,progress,today:'2026-10-21'}).nodes.find(n=>n.key==='field').progress,{basis:'unknown',percent:null,label:'進度未知'});
});
test('known quantities retain unit text without adding unlike quantities',()=>{
 const p=structuredClone(progress);p.production.field.actual={known:true,value:'12.50',unit_note:'公尺',source:'v4_daily',reason:null};
 const n=m.buildFlowModel({project:projectFixture().project,progress:p,today:'2026-10-21'}).nodes.find(n=>n.key==='field');
 assert.equal(n.quantity.actual,'12.50');assert.equal(n.quantity.unit,'公尺');assert.equal(n.quantity.planned,'65');
 assert.equal(n.progress.percent,100);
});
test('legacy has one honest local-task number and source state never overwrites workflow authority',()=>{
 const project=projectFixture().project;project.nodes[3].tasks=[{id:'local1',status:'completed'},{id:'local2',status:'pending'},{id:'old',status:'superseded'}];
 const flow=m.buildFlowModel({project,progress,today:'2026-10-21'});
 assert.equal(flow.overall.percent,null);assert.equal(flow.overall.label,'部分節點進度未知（略過不計）');assert.equal(flow.nodes[3].state,'已完成');
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

test('round2 node state overrides task ratio and skipped nodes have no bar',()=>{
 const {list}=assignmentFixture();list.nodes=list.nodes.filter(n=>['sales','field','control'].includes(n.key));
 Object.assign(list.nodes.find(n=>n.key==='sales'),{derived_status:'已完成',tasks:{done:0,total:0}});
 Object.assign(list.nodes.find(n=>n.key==='field'),{derived_status:'略過',tasks:{done:0,total:0}});
 Object.assign(list.nodes.find(n=>n.key==='control'),{derived_status:'已完成',tasks:{done:1,total:3}});
 const flow=m.buildFlowModel({project:projectFixture().project,assignments:list,today:'2026-10-21'});
 assert.deepEqual(flow.nodes.find(n=>n.key==='sales').progress,{basis:'nodes',percent:100,label:'節點已完成'});
 assert.deepEqual(flow.nodes.find(n=>n.key==='control').progress,{basis:'nodes',percent:100,label:'節點已完成'});
 assert.deepEqual(flow.nodes.find(n=>n.key==='field').progress,{basis:'skipped',percent:null,label:'略過'});
 assert.deepEqual(flow.overall,{basis:'nodes',percent:100,label:'節點完成度（略過不計）'});
});

test('round2 overall stays unknown when a counted node has unknown progress',()=>{
 const {list}=assignmentFixture();list.nodes=list.nodes.filter(n=>['sales','control'].includes(n.key));list.nodes.find(n=>n.key==='control').tasks={done:0,total:0};
 const flow=m.buildFlowModel({project:projectFixture().project,assignments:list,today:'2026-10-21'});
 assert.deepEqual(flow.overall,{basis:'unknown',percent:null,label:'部分節點進度未知（略過不計）'});
});

test('node needs use source facts in priority order and finished nodes need nothing',()=>{
 const {list}=assignmentFixture();const flow=m.buildFlowModel({project:projectFixture().project,assignments:list,progress,today:'2026-10-21'});
 const base={...flow.nodes[0],state:'進行中',owners:[{open_id:'owner',name:'負責人'}],tasks:{done:1,total:3},overdue:false,assignment:undefined};
 assert.equal(m.nodeNeeds({...base,state:'已完成',owners:[],overdue:true}),null);
 assert.equal(m.nodeNeeds({...base,state:'略過',owners:[],overdue:true}),null);
 assert.equal(m.nodeNeeds({...base,state:'待審核',owners:[],overdue:true}),'待主管審核');
 assert.equal(m.nodeNeeds({...base,owners:[],overdue:true}),'待指派負責人');
 assert.equal(m.nodeNeeds({...base,overdue:true,assignment:{can_submit_hint:true}}),'已逾期');
 assert.equal(m.nodeNeeds({...base,assignment:{can_submit_hint:true}}),'可送審');
 assert.equal(m.nodeNeeds(base),'尚餘 2 項任務');
 assert.equal(m.nodeNeeds({...base,tasks:{done:3,total:3}}),null);
 assert.equal(m.nodeNeeds({...base,tasks:{done:0,total:0}}),null);
 for(const node of flow.nodes)assert.equal(node.needs,m.nodeNeeds(node));
});
