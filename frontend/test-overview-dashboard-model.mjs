import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';
const bundle=await build({stdin:{contents:"export * from './src/overviewDashboardModel';export * from './src/projectOverviewModel';export {withLocalChecklist} from './src/nodeWorkbenchModel';export {buildFlowModel} from './src/flowModel';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
function fixture(){const {list,detail}=assignmentFixture();for(const node of list.nodes){node.owners=[{open_id:'owner',name:'負責人'}];node.tasks={done:0,total:0}}list.node_details={control:{tasks:[detail.tasks[0],{...detail.tasks[0],id:'unassigned',assignee:null},{...detail.tasks[0],id:'completed',status:'已完成'},{...detail.tasks[0],id:'cancelled',status:'取消'}],assignable_people:[]}};list.nodes.find(node=>node.key==='control').tasks={done:1,total:3};return {list,nodes:m.buildFlowModel({project:projectFixture().project,assignments:list,today:'2026-10-23'}).nodes}}
test('KPI tiles show real values and fold unsupported quantities into one summary',()=>{
 const {nodes}=fixture(),field=structuredClone(progress.production.field);
 field.items=[5,10,50].map((q,i)=>({item_id:`id-${i}`,planned_qty:String(q),code:i?'C115264-1':'C115264-2',name:'測量',link_basis:'native'}));field.items_total=3;
 const issues=m.needsAttention(nodes,field),cells=m.overviewKpis({field,nodes,issues,available:true});
 assert.equal(cells.find(cell=>cell.id==='items').value,'3 筆');assert.equal(cells.find(cell=>cell.id==='items').label,'外業關聯工項');
 assert.equal(cells.some(cell=>['planned','field','actual'].includes(cell.id)),false);assert.equal(JSON.stringify(cells).includes('65'),false);assert.equal(cells.find(cell=>cell.id==='issues').value,String(issues.length));assert.equal(cells.find(cell=>cell.id==='issues').alert,issues.length>0);
 assert.doesNotMatch(cells.map(cell=>cell.value).join(' '),/未知|待核對|依各工項顯示/);
 assert.match(m.overviewMissingSummary(cells),/^待核實：外業完成量/);
 const noPlan={...field,planned:null};assert.equal(m.overviewKpis({field:noPlan,nodes,issues,available:true}).some(cell=>cell.id==='items'),false);
 field.actual={known:true,value:'32',unit_note:'公尺',source:'daily',reason:null};assert.equal(m.overviewKpis({field,nodes,issues,available:true}).some(cell=>cell.id==='actual'),false);
 const empty=m.overviewKpis({nodes,issues:[],available:false});assert.deepEqual(empty,[]);assert.equal(m.overviewMissingSummary(empty),'待核實：外業完成量、回報日期、工項筆數、任務統計、異常統計。');
});
test('open task counts separate assigned from unassigned and exclude completed/cancelled',()=>{
 const {nodes}=fixture();const result=m.overviewTasks(nodes,true);assert.equal(result.assigned,1);assert.equal(result.unassigned,1);assert.equal(result.complete,true);
 const cells=m.overviewKpis({field:progress.production.field,nodes,issues:[],available:true});assert.equal(cells.find(cell=>cell.id==='tasks').value,'1');assert.equal(cells.find(cell=>cell.id==='tasks').detail,'尚未指派 1');assert.equal(cells.find(cell=>cell.id==='issues').alert,false);
 const control=nodes.find(node=>node.key==='control');control.taskRows[0].status='來源不明';assert.equal(m.overviewTasks(nodes,true).complete,false);assert.equal(m.overviewTasks(nodes,true).assigned,0);control.taskRows[0].status='進行中';
 nodes.find(node=>node.key==='control').tasks.total=10;assert.equal(m.overviewTasks(nodes,true).complete,false);assert.equal(m.overviewKpis({nodes,issues:[],available:false}).some(cell=>cell.id==='tasks'),false);assert.equal(m.overviewKpis({nodes,issues:[],available:false}).some(cell=>cell.id==='issues'),false);
 assert.equal(m.overviewKpis({field:progress.production.field,nodes,issues:[],available:true,stale:true}).some(cell=>cell.id==='issues'),false);
 assert.equal(m.overviewKpis({field:progress.production.field,nodes,issues:[],available:true,assignmentsStale:true}).some(cell=>['tasks','issues'].includes(cell.id)),false);
});
test('document counts use explicit categories and records, not filenames or extensions',()=>{
 const files=[{id:'1',name:'report.pdf',category_id:'field_raw'},{id:'2',category_id:'field_raw'},{id:'3',category_id:'drawing'},{id:'4',category_id:'report',withdrawn:true},{id:'5',name:'contract.pdf'},{id:'6',category_id:'custom'}];
 assert.deepEqual(m.overviewDocuments(files,[{id:'custom',name:'合約'}]),[{id:'field_raw',label:'測量資料',count:2},{id:'drawing',label:'圖資',count:1},{id:'unclassified',label:'分類待核對',count:1},{id:'custom',label:'合約',count:1}]);assert.deepEqual(m.overviewDocuments([]),[]);
});
test('todo rows preserve one primary action, task identity, owner and exact target without duplicates',()=>{
 const {nodes,list}=fixture();const action=m.selectNextAction({nodes,list,user:projectFixture().user,today:'2026-10-23',execution:{allowed:true,reason:''},localLead:true,assignmentsUnavailable:false});const issues=m.needsAttention(nodes,progress.production.field);const rows=m.overviewTodos(action,issues,nodes);
 assert.equal(rows[0].primary,true);assert.equal(rows.filter(row=>row.primary).length,1);assert.deepEqual(rows[0].target,{tab:'flow',node:'control',task:'recTask1'});assert.equal(rows[0].owner,'陳威廷');assert.equal(rows[0].deadline,'2026-10-20');assert.equal(rows.filter(row=>row.target.task==='recTask1').length,1);assert.ok(rows.some(row=>row.target.task==='unassigned'));assert.equal(rows.some(row=>row.target.task==='completed' || row.target.task==='cancelled'),false);
});

test('SOP on remote-assigned nodes retains identity, permissions, source and revision; shared tasks count once',()=>{
 const {nodes}=fixture();
 const task={id:'sop-1',title:'現場核對',state:'blocked',applicability:'applicable',participants:{executor:'u1'},dueDate:null,revision:7,allowedActions:['edit'],nodes:[{node_key:'control'},{node_key:'mapping'}]};
 const enriched=m.withLocalChecklist(nodes,{tasks:[task],nodeCounts:{control:{done:0,total:1},mapping:{done:0,total:1}},localNodes:[]},[{id:'u1',name:'王執行'}]);
 const action={title:'先確認案件執行歸屬',reason:'案件權責',owner:'案件主管',button:'查看詳情',target:{tab:'data',section:'participants'}};
 const rows=m.overviewTodos(action,[{id:'duplicate',title:'重複建議',owner:'主管',reason:'核對',target:{tab:'flow',node:'control',task:'recTask1'}}],enriched);
 assert.deepEqual(rows.map(r=>r.kind),['recommendation','larkTask','larkTask','sopTask']);
 assert.equal(rows[0].source,'recommendation');assert.equal('task' in rows[0],false);assert.equal('permissions' in rows[0],false);
 const sop=rows.find(r=>r.kind==='sopTask');assert.equal(sop.task,task);assert.equal(sop.source,'sop_local');assert.equal(sop.revision,7);assert.deepEqual(sop.permissions,['edit']);assert.equal(sop.owner,'王執行');assert.deepEqual(sop.target,{tab:'flow',node:'control',task:'sop-1',task_source:'sop_local'});
 const lark=rows.find(r=>r.kind==='larkTask');assert.equal(lark.task.id,'recTask1');assert.equal(lark.revision,'9b0c1d2e3f405162');assert.equal(lark.permissions.assign,true);assert.equal(lark.source,'lark');
 assert.equal(rows.filter(r=>r.kind!=='recommendation').length,3);assert.equal(m.overviewTasks(enriched,true).rows.length,3);
 assert.equal(enriched.find(n=>n.key==='control').tasks.total,4);assert.equal(enriched.find(n=>n.key==='control').taskRows.find(t=>t.id==='sop-1').status,'受阻');
 assert.equal(rows.filter(r=>r.target.task==='recTask1').length,1);
});
test('paused and blocked tasks stay visible even in paused or completed nodes',()=>{
 const {nodes}=fixture(),node=nodes.find(n=>n.key==='control');node.state='暫停';node.taskRows[0].status='暫停';
 assert.deepEqual(m.overviewTasks(nodes,true).rows.map(t=>t.id),['recTask1','unassigned']);
 const action={title:'核對',reason:'核對',owner:'主管',button:'查看詳情',target:{tab:'flow',node:'control'}};
 assert.equal(m.overviewTodos(action,[],nodes).filter(r=>r.kind==='larkTask').length,2);
});
