import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';
const result=await build({stdin:{contents:"export * from './src/nodeWorkbenchModel';export {buildFlowModel,flowTaskTarget} from './src/flowModel'",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const m=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'));
test('registry never enables an action absent from the server permissions',()=>{
 const r=m.actionRegistry({can:{assign:true,complete:false}});assert.equal(r.assign.enabled,true);assert.equal(r.complete.enabled,false);assert.ok(r.complete.disabledReason);
 for(const busy of [true,false]){const r=m.actionRegistry({can:{assign:true},busy,reason:'寫入尚未開放'});assert.equal(r.assign.enabled,false);assert.equal(r.assign.disabledReason,'寫入尚未開放')}
});
test('local cases do not depend on confirmation or the remote feature',()=>{
 assert.equal(m.localCase({case_type:'intake',code:'Q115'}),true);assert.equal(m.localCase({code:''}),true);assert.equal(m.localCase({code:'C115001'}),false);
 const node=m.buildFlowModel({project:projectFixture().project,today:'2026-10-25'}).nodes[0];
 const local={key:'sales',id:'node_sales',revision:2,can:{assign:true,complete:true},disabledReason:null};
 const wb=m.buildNodeWorkbench({node,local,sop:{tasks:[]}});assert.equal(wb.source,'local-sop');assert.equal(wb.actions.complete.enabled,true);assert.equal(wb.actions.approve.visible,false);
});
test('task variants retain their source and revisions without title matching',()=>{
 const {list,detail}=assignmentFixture();list.node_details={control:detail};const node=m.buildFlowModel({project:projectFixture().project,assignments:list,today:'2026-10-25'}).nodes.find(n=>n.key==='control');
 const task={id:'s1',title:detail.tasks[0].title,nodes:[{node_key:'control'}]};
 const wb=m.buildNodeWorkbench({node,sop:{tasks:[task]},can:list.can.control});assert.deepEqual(wb.tasks.map(t=>t.source),['lark','local-sop']);assert.equal(wb.tasks[0].task.revision,detail.tasks[0].revision);
});
test('draft changes ignore a reason alone and preserve cleared assignees and dates',()=>{
 const a={title:'核對',assignee:'u1',due:'2026-10-25',notes:'',status:'pending',reason:''};assert.equal(m.draftChanged(a,{...a,reason:'原因'}),false);assert.equal(m.draftChanged(a,{...a,assignee:''}),true);assert.equal(m.draftChanged(a,{...a,due:''}),true);
});

test('a checklist-only case uses authorized node projections and preserves unknown case facts',()=>{
 assert.equal(m.checklistProject({caseHeader:{id:'local',name:'規劃案'},localNodes:[]}),undefined);
 const p=m.checklistProject({caseHeader:{id:'local',name:'規劃案',code:null},localNodes:[{id:'sales-id',key:'sales',status:'completed',ownerId:'u1',completedAt:'2026-10-25'}]});
 assert.equal(p.id,'local');assert.equal(p.contract_amount,null);assert.equal(p.pm_id,'');assert.equal(p.nodes[0].status,'completed');assert.equal(p.nodes[0].owner_id,'u1');assert.equal(p.sop_only,true);
});

test('local SOP tasks enter overview rows with their source-specific deep link',()=>{
 const nodes=m.buildFlowModel({project:projectFixture().project,today:'2026-10-25'}).nodes;
 const sop={tasks:[{id:'sop-task',title:'本案確認',state:'pending',applicability:'applicable',nodes:[{node_key:'sales'}],participants:{executor:'u1'},dueDate:'2026-10-28',allowedActions:['start']}],nodeCounts:{sales:{done:0,total:1}},localNodes:[{key:'sales',status:'pending',ownerId:'u1'}]};
 const node=m.withLocalChecklist(nodes,sop,[{id:'u1',name:'執行人'}])[0];
 assert.equal(node.taskRows[0].source,'SOP 任務');assert.equal(node.taskRows[0].owner,'執行人');assert.equal(node.tasks.total,1);
 assert.deepEqual(m.flowTaskTarget(node.taskRows[0]),{tab:'flow',node:'sales',task:'sop-task',task_source:'sop_local'});
});
test('assign reason follows the verified node status, never a blanket completed claim',()=>{
 const node=m.buildFlowModel({project:projectFixture().project,today:'2026-10-25'}).nodes[0];
 const local=status=>({key:'sales',id:'n',revision:1,status,can:{assign:false,complete:false},disabledReason:null});
 const pending=m.buildNodeWorkbench({node,local:local('pending'),sop:{tasks:[]},busy:true});
 assert.equal(pending.actions.assign.disabledReason,'讀取中，稍後再試');
 const idle=m.buildNodeWorkbench({node,local:local('pending'),sop:{tasks:[]}});
 assert.notEqual(idle.actions.assign.disabledReason,'節點已完成');
 const done=m.buildNodeWorkbench({node,local:local('completed'),sop:{tasks:[]}});
 assert.equal(done.actions.assign.disabledReason,'節點已完成');
});
