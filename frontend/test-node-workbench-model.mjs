import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';
const result=await build({stdin:{contents:"export * from './src/nodeWorkbenchModel';export {buildFlowModel} from './src/flowModel'",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
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
