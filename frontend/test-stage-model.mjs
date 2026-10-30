import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';
const bundled=await build({stdin:{contents:"export * from './src/flowModel'; export * from './src/stageModel';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const TODAY='2026-10-18';
const none={pending:false,unassigned:false,blocked:false,mine:false};
const can={edit_status:true,cancel:true,assign:true,claim:false,edit_details:true};
const task=(id,over={})=>({id,title:`任務 ${id}`,detail:'',assignee:{open_id:'ou_wei',name:'陳威廷'},assigned_by:null,department:'控制',deadline:null,status:'待處理',revision:`r-${id}`,record_id:id,done_at:null,created_at:null,can,...over});
function scenario({current='sales',states={},tasks={},counts={},mutate}={}){
 const {list}=assignmentFixture();
 list.summary.current_node=current;list.node_details={};
 for(const n of list.nodes){
  n.derived_status=states[n.key]??(n.key===current?'進行中':'未開始');
  const rows=tasks[n.key]||[];list.node_details[n.key]={tasks:rows,assignable_people:[]};
  n.tasks=counts[n.key]||{done:rows.filter(t=>t.status==='已完成').length,total:rows.filter(t=>t.status!=='取消').length};
  list.can[n.key]={claim:false,assign:true,complete:true,approve:false,reject:false,create_task:true};
 }
 mutate?.(list);
 const project={...projectFixture().project,nodes:[]};
 const flow=m.buildFlowModel({project,assignments:list,today:TODAY});
 return {list,flow,ctx:m.resolveStages({nodes:flow.nodes,list})};
}
const step=(s,over={})=>m.stageNextStep({ctx:s.ctx,list:s.list,userId:'ou_anna',today:TODAY,fresh:true,...over});

test('T01 the first screen reads the current stage from the server',()=>{
 const s=scenario({current:'sales'});
 assert.deepEqual(s.ctx.currentIds,['sales']);assert.equal(s.ctx.selectedId,'sales');assert.equal(s.ctx.selectedReason,'current');
});
test('T02 selecting another node keeps the current stage and offers the way back',()=>{
 const s=scenario({current:'sales',tasks:{settlement:[task('s1')]}});
 const picked=m.resolveStages({nodes:s.flow.nodes,list:s.list,requested:'settlement'});
 assert.equal(picked.selectedId,'settlement');assert.deepEqual(picked.currentIds,['sales']);assert.equal(picked.currentSelected,false);assert.equal(picked.selectedReason,'url');
});
test('T03 a workflow with another node count and a long name has no nine-node assumption',()=>{
 const {list}=assignmentFixture();
 list.nodes=[{...list.nodes[2],key:'review',label:'第三方獨立複核與外部單位會審'},{...list.nodes[4],key:'deliver',label:'交付'}];
 list.summary={done:0,total:2,current_node:'deliver'};list.node_details={};
 const flow=m.buildFlowModel({project:{...projectFixture().project,nodes:[]},assignments:list,today:TODAY});
 assert.deepEqual(flow.nodes.map(n=>n.key),['review','deliver']);assert.equal(flow.nodes[0].label,'第三方獨立複核與外部單位會審');
 const ctx=m.resolveStages({nodes:flow.nodes,list});assert.equal(ctx.selectedId,'deliver');
});
test('T04 authoritative counts show 3 / 5 and 60% and unassigned does not change them',()=>{
 const rows=[1,2,3].map(i=>task(`d${i}`,{status:'已完成'})).concat([task('o1',{assignee:null}),task('o2')]);
 const s=scenario({current:'control',tasks:{control:rows}});
 const stats=m.nodeStats(s.flow.nodes.find(n=>n.key==='control'));
 assert.deepEqual([stats.label,stats.percent],['3 / 5 已完成',60]);
 const zero=m.nodeStats(scenario({current:'control'}).flow.nodes.find(n=>n.key==='control'));
 assert.deepEqual([zero.label,zero.percent],['無適用任務',null]);
 const bad=m.nodeStats({tasks:{done:6,total:5}});assert.equal(bad.label,'數據待確認');assert.equal(bad.percent,null);
});
test('T05 a pending task with no executor keeps both facts and is not turned into blocked',()=>{
 const s=scenario({current:'control',tasks:{control:[task('u',{assignee:null,status:'待處理'})]}});
 const node=s.flow.nodes.find(n=>n.key==='control');
 const view=m.taskView(node.taskRows[0],node,TODAY);
 assert.equal(view.statusText,'待處理');assert.equal(view.flags.unassigned,true);assert.equal(view.flags.blocker.state,'unknown');
 const only=m.matchesFilters(view,{...none,blocked:true},'ou_anna');assert.equal(only,false);
});
test('T06 case, node and task status come from separate dictionaries and unknown values are not guessed',()=>{
 assert.equal(m.caseStatusLabel('pending'),'尚未開始');assert.equal(m.taskStatusText('進行中'),'進行中');
 assert.equal(m.caseStatusLabel('???'),'狀態待確認');assert.equal(m.taskStatusText('???'),'狀態待確認');
 assert.match(m.STATUS_LEVEL_NOTE,/案件狀態描述整體案件/);
});
test('T14 recommendation stays in the current stage even when another node is selected',()=>{
 const s=scenario({current:'sales',tasks:{sales:[task('a',{assignee:null})],settlement:[task('z',{deadline:'2026-10-01'})]}});
 const picked=m.resolveStages({nodes:s.flow.nodes,list:s.list,requested:'settlement'});
 const result=step({...s,ctx:picked});
 assert.equal(result.kind,'action');assert.equal(result.nodeKey,'sales');assert.equal(result.taskId,'a');assert.equal(result.needs,'assign');
});
test('T15 an unfinished dependency yields blocker navigation and never a start action',()=>{
 const {list}=assignmentFixture();
 const project={...projectFixture().project};
 project.nodes=project.nodes.map(n=>n.key==='field'?{...n,tasks:[{id:'lt',title:'本地任務',owner_id:'ou_anna',status:'pending',required:true,start_date:null,due_date:null,original_due_date:null,started_at:null,completed_at:null,points:null,work_item_id:'',description:'',input:'',output:'',comments:[],revision:1,execution_blockers:['前置成果尚未交付'],can_execute:true}]}:n);
 const flow=m.buildFlowModel({project,today:TODAY,users:[{id:'ou_anna',name:'安娜'}]});
 const ctx=m.resolveStages({nodes:flow.nodes,list:undefined});
 const field=flow.nodes.find(n=>n.key==='field');
 const view=m.taskView(field.taskRows[0],field,TODAY);
 assert.deepEqual(view.flags.blocker,{state:'blocked',reasons:['前置成果尚未交付']});
 const only={...ctx,currentIds:['field'],currentKnown:true,selectedId:'field'};
 const result=m.stageNextStep({ctx:only,list:undefined,userId:'ou_anna',today:TODAY,fresh:true});
 assert.equal(result.kind,'view');assert.equal(result.button,'查看前置任務');
});
test('T16 no executable candidate in the current stage says so and never recommends settlement',()=>{
 const s=scenario({current:'sales',tasks:{sales:[task('d',{status:'已完成'})],settlement:[task('z')]}});
 const result=step(s);
 assert.equal(result.kind,'none');assert.equal(result.title,'目前沒有你可執行的動作');assert.ok(result.reasons.length>0);
});
test('T17 cross-stage execution needs an explicit allowance and names the target and reason',()=>{
 const s=scenario({current:'sales',tasks:{sales:[],pm:[task('p1')]}});
 const none1=step(s);assert.equal(none1.kind,'none');
 const allowed=step(s,{crossStageAllowed:(from,to)=>from==='sales'&&to==='pm'?'流程設定允許並行':null});
 assert.equal(allowed.kind,'action');assert.equal(allowed.nodeKey,'pm');assert.match(allowed.reason,/目前階段無可執行項；依流程允許先處理PM/);assert.match(allowed.reason,/流程設定允許並行/);
});
test('T18 approval only matters when the node is awaiting review with approve capability',()=>{
 const s=scenario({current:'control',states:{control:'待審核'},tasks:{control:[task('x',{status:'已完成'})]},mutate:l=>{l.can.control.approve=true}});
 assert.equal(step(s).needs,'approve');
 const noApprove=scenario({current:'control',tasks:{control:[task('x',{status:'進行中'})]}});
 assert.notEqual(step(noApprove).needs,'approve');
 const without=scenario({current:'control',states:{control:'待審核'},tasks:{control:[]}});
 assert.equal(step(without).kind,'none');
});
test('stale or write-disabled data blocks executable recommendations',()=>{
 const s=scenario({current:'sales',tasks:{sales:[task('a',{assignee:null})]}});
 const result=step(s,{fresh:false});assert.equal(result.kind,'none');assert.match(result.reasons.join(' '),/過期/);
});
test('missing workflow and unknown current stage are stated, not invented',()=>{
 const empty=m.resolveStages({nodes:[],list:undefined});
 assert.equal(m.stageNextStep({ctx:empty,userId:'u',today:TODAY,fresh:true}).title,'流程尚未設定');
 const s=scenario({current:'sales'});
 const unknown={...s.ctx,currentIds:[],currentKnown:false};
 assert.equal(m.stageNextStep({ctx:unknown,list:s.list,userId:'u',today:TODAY,fresh:true}).title,'目前階段待確認');
});
test('T21 filters compose with AND and keep the node total apart from the matching count',()=>{
 const rows=[task('a',{assignee:null}),task('b',{assignee:null,status:'已完成'}),task('c',{assignee:{open_id:'ou_anna',name:'安娜'}})];
 const s=scenario({current:'control',tasks:{control:rows}});
 const groups=m.groupTasks({ctx:m.resolveStages({nodes:s.flow.nodes,list:s.list}),filters:{...none,unassigned:true,pending:true},userId:'ou_anna',today:TODAY,loaded:()=>true});
 assert.deepEqual(groups.selected.matching.map(t=>t.id),['a']);assert.equal(groups.selected.total,3);
 const mine=m.groupTasks({ctx:s.ctx,filters:{...none,mine:true},userId:'ou_anna',today:TODAY,loaded:()=>true});
 assert.deepEqual(mine.selected.matching.map(t=>t.id),['c']);
 const empty=m.groupTasks({ctx:s.ctx,filters:{...none,blocked:true},userId:'ou_anna',today:TODAY,loaded:()=>true});
 assert.equal(empty.selected.matching.length,0);assert.equal(m.blockedKnown(empty.selected.rows),false);
});
test('other stages are grouped in workflow order and exclude the selected node',()=>{
 const s=scenario({current:'sales',tasks:{sales:[task('a')],pm:[task('p')],field:[task('f')]}});
 const g=m.groupTasks({ctx:s.ctx,filters:none,userId:'u',today:TODAY,loaded:()=>false});
 assert.equal(g.selected.node.key,'sales');assert.deepEqual(g.others.map(x=>x.node.key),['pm','field']);
});
