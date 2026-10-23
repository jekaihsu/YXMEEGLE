import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';
const bundle=await build({stdin:{contents:"export * from './src/overviewDashboardModel';export * from './src/projectOverviewModel';export {buildFlowModel} from './src/flowModel';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
function fixture(){const {list,detail}=assignmentFixture();for(const node of list.nodes){node.owners=[{open_id:'owner',name:'負責人'}];node.tasks={done:0,total:0}}list.node_details={control:{tasks:[detail.tasks[0],{...detail.tasks[0],id:'unassigned',assignee:null},{...detail.tasks[0],id:'completed',status:'已完成'},{...detail.tasks[0],id:'cancelled',status:'取消'}],assignable_people:[]}};list.nodes.find(node=>node.key==='control').tasks={done:1,total:3};return {list,nodes:m.buildFlowModel({project:projectFixture().project,assignments:list,today:'2026-10-23'}).nodes}}
test('KPI contract counts items without summing 5/10/50 and keeps quantities unknown',()=>{
 const {nodes}=fixture(),field=structuredClone(progress.production.field);
 field.items=[5,10,50].map((q,i)=>({item_id:`id-${i}`,planned_qty:String(q),code:i?'C115264-1':'C115264-2',name:'測量',link_basis:'native'}));field.items_total=3;
 const issues=m.needsAttention(nodes,field),cells=m.overviewKpis({field,nodes,issues,available:true});
 assert.equal(cells.find(cell=>cell.id==='items').value,'3 筆');assert.equal(cells.find(cell=>cell.id==='planned').value,'依各工項顯示');assert.equal(cells.find(cell=>cell.id==='field').value,'尚無可信完成量');assert.equal(cells.find(cell=>cell.id==='actual').value,'未知');assert.equal(JSON.stringify(cells).includes('65'),false);assert.equal(cells.find(cell=>cell.id==='issues').value,String(issues.length));assert.equal(cells.find(cell=>cell.id==='issues').alert,issues.length>0);
 const noPlan={...field,planned:null};assert.equal(m.overviewKpis({field:noPlan,nodes,issues,available:true}).find(cell=>cell.id==='items').value,'未知');
 field.actual={known:true,value:'32',unit_note:'公尺',source:'daily',reason:null};assert.equal(m.overviewKpis({field,nodes,issues,available:true}).find(cell=>cell.id==='actual').value,'未知');
});
test('open task counts separate assigned from unassigned and exclude completed/cancelled',()=>{
 const {nodes}=fixture();const result=m.overviewTasks(nodes,true);assert.equal(result.assigned,1);assert.equal(result.unassigned,1);assert.equal(result.complete,true);
 const cells=m.overviewKpis({field:progress.production.field,nodes,issues:[],available:true});assert.equal(cells.find(cell=>cell.id==='tasks').value,'1');assert.equal(cells.find(cell=>cell.id==='tasks').detail,'尚未指派 1');assert.equal(cells.find(cell=>cell.id==='issues').alert,false);
 const control=nodes.find(node=>node.key==='control');control.taskRows[0].status='來源不明';assert.equal(m.overviewTasks(nodes,true).complete,false);assert.equal(m.overviewTasks(nodes,true).assigned,0);control.taskRows[0].status='進行中';
 nodes.find(node=>node.key==='control').tasks.total=10;assert.equal(m.overviewTasks(nodes,true).complete,false);assert.equal(m.overviewKpis({nodes,issues:[],available:false}).find(cell=>cell.id==='tasks').value,'待核對');assert.equal(m.overviewKpis({nodes,issues:[],available:false}).find(cell=>cell.id==='issues').value,'待核對');
 assert.equal(m.overviewKpis({field:progress.production.field,nodes,issues:[],available:true,stale:true}).find(cell=>cell.id==='issues').value,'待核對');
});
test('document counts use explicit categories and records, not filenames or extensions',()=>{
 const files=[{id:'1',name:'report.pdf',category_id:'field_raw'},{id:'2',category_id:'field_raw'},{id:'3',category_id:'drawing'},{id:'4',category_id:'report',withdrawn:true},{id:'5',name:'contract.pdf'},{id:'6',category_id:'custom'}];
 assert.deepEqual(m.overviewDocuments(files,[{id:'custom',name:'合約'}]),[{id:'field_raw',label:'測量資料',count:2},{id:'drawing',label:'圖資',count:1},{id:'unclassified',label:'分類待核對',count:1},{id:'custom',label:'合約',count:1}]);assert.deepEqual(m.overviewDocuments([]),[]);
});
test('todo rows preserve one primary action, task identity, owner and exact target without duplicates',()=>{
 const {nodes,list}=fixture();const action=m.selectNextAction({nodes,list,user:projectFixture().user,today:'2026-10-23',execution:{allowed:true,reason:''},localLead:true,assignmentsUnavailable:false});const issues=m.needsAttention(nodes,progress.production.field);const rows=m.overviewTodos(action,issues,nodes);
 assert.equal(rows[0].primary,true);assert.equal(rows.filter(row=>row.primary).length,1);assert.deepEqual(rows[0].target,{tab:'flow',node:'control',task:'recTask1'});assert.equal(rows[0].owner,'陳威廷');assert.equal(rows[0].deadline,'2026-10-20');assert.equal(rows.filter(row=>row.target.task==='recTask1').length,1);assert.ok(rows.some(row=>row.target.task==='unassigned'));assert.equal(rows.some(row=>row.target.task==='completed' || row.target.task==='cancelled'),false);
});
