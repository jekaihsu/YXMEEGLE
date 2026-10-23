import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';
const bundle=await build({stdin:{contents:"export * from './src/projectOverviewModel';export {buildFlowModel} from './src/flowModel';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
function input(){const {list,detail}=assignmentFixture();for(const n of list.nodes)n.owners=[{open_id:'owner',name:'節點負責人'}];list.node_details={control:{tasks:detail.tasks,assignable_people:[]}};return {nodes:m.buildFlowModel({project:projectFixture().project,assignments:list,today:'2026-10-21'}).nodes,list,user:projectFixture().user,today:'2026-10-21',execution:{allowed:true,reason:''},localLead:false,assignmentsUnavailable:false}}
test('next action order is ownership, overdue, review, due soon, ordinary work',()=>{
 const x=input(),control=x.nodes.find(n=>n.key==='control'),mapping=x.nodes.find(n=>n.key==='mapping');mapping.state='待審核';
 assert.equal(m.selectNextAction(x).kind,'overdue');
 const blocked=m.selectNextAction({...x,blockingApproval:{id:'approval1',title:'設計變更',node:'control',owner:'主管'}});assert.equal(blocked.kind,'blocking');assert.equal(blocked.target.approval,'approval1');assert.equal(blocked.button,'查看詳情');
 control.owners=[];assert.equal(m.selectNextAction(x).kind,'blocking');control.owners=[{open_id:'owner',name:'負責人'}];
 assert.equal(m.selectNextAction({...x,execution:{allowed:false,reason:'歸屬待核定'}}).title,'先確認案件執行歸屬');
 control.taskRows[0].deadline='2026-10-23';assert.equal(m.selectNextAction(x).kind,'review');
 mapping.state='未開始';assert.equal(m.selectNextAction(x).kind,'soon');
 control.taskRows[0].deadline='2026-11-20';assert.equal(m.selectNextAction(x).kind,'work');
 assert.equal(m.selectNextAction(x).target.task,'recTask1');
});
test('unauthorized and stale viewers get responsible actor and view-details fallback',()=>{
 const x=input();let action=m.selectNextAction(x);assert.equal(action.allowed,true);assert.equal(action.button,'開啟任務');assert.equal(m.selectNextAction({...x,assignmentsUnavailable:true}).button,'查看詳情');
 x.nodes.find(n=>n.key==='control').taskRows[0].task.can.edit_status=false;
 action=m.selectNextAction(x);assert.equal(action.allowed,false);assert.equal(action.button,'查看詳情');assert.equal(action.owner,'陳威廷');
 const control=x.nodes.find(n=>n.key==='control');control.owners=[];x.list.can.control={};action=m.selectNextAction(x);assert.equal(action.allowed,false);assert.equal(action.button,'查看詳情');assert.equal(action.owner,'林安娜');
 x.list.can.control={assign:true};x.list.stale=true;assert.equal(m.selectNextAction(x).allowed,false);
});
test('finished or paused tasks never become ordinary next work, and unknown sources require checking',()=>{
 const x=input(),control=x.nodes.find(n=>n.key==='control');control.state='已完成';assert.equal(m.selectNextAction(x).target.task,undefined);
 control.state='暫停';assert.equal(m.selectNextAction(x).target.task,undefined);
 const action=m.selectNextAction({...x,nodes:[],assignmentsUnavailable:true});assert.match(action.title,/需要核對/);assert.equal(action.button,'查看詳情');
});
test('completed node with 0/1 tasks is a reconciliation warning, followed by missing quantity and owner',()=>{
 const x=input(),field=x.nodes.find(n=>n.key==='field');Object.assign(field,{state:'已完成',tasks:{done:0,total:1},owners:[]});
 const issues=m.needsAttention(x.nodes,progress.production.field);assert.equal(issues[0].id,'reconcile:field');assert.match(issues[0].title,/狀態待核對/);assert.match(issues[0].reason,/0\/1/);assert.match(issues[0].reason,/不代表工程量未完成/);assert.deepEqual(issues[0].target,{tab:'flow',node:'field'});assert.equal(issues[1].id,'field:unlinked');assert.equal(issues[2].id,'owner:field');
 field.tasks={done:1,total:1};field.owners=[{open_id:'o',name:'負責人'}];assert.deepEqual(m.needsAttention(x.nodes),[]);
});
test('C115264 has 3 linked items and unknown percent, never a sum of planned 5,10,50',()=>{
 const field=structuredClone(progress.production.field);field.items=[5,10,50].map((qty,i)=>({item_id:`immutable-${i}`,code:i ? 'C115264-1' : 'C115264-2',name:'工項',planned_qty:String(qty),link_basis:'native'}));field.items_total=3;
 const snapshot=m.fieldworkSnapshot(field);assert.equal(snapshot.percent,null);assert.equal(snapshot.count,3);assert.equal(snapshot.latestDate,null);assert.equal('planned' in snapshot,false);assert.match(snapshot.reason,/連結|關聯/);
 field.actual={known:true,value:'29',unit_note:'公尺',source:'v4_daily',reason:null};assert.equal(m.fieldworkSnapshot(field).percent,null);assert.match(m.fieldworkSnapshot(field).reason,/分母/);
 field.items[0].link_basis='ambiguous';assert.equal(m.fieldworkSnapshot(field).percent,null);assert.match(m.fieldworkSnapshot(field).reason,/關聯/);
 assert.equal(m.fieldworkSnapshot(undefined).count,null);assert.match(m.fieldworkSnapshot(field,[],true).reason,/上次成功/);
});
test('only approved explicitly matched field reports provide the latest valid report date',()=>{
 const report={department:'外業組',date:'2026-10-20',review:{status:'approved'},match_basis:'native'};
 const snapshot=m.fieldworkSnapshot(progress.production.field,[report,{...report,date:'2026-10-21',match_basis:'derived'},{...report,date:'2026-10-22',review:{status:'pending'}},{...report,date:'not-a-date'}]);assert.equal(snapshot.latestDate,'2026-10-20');assert.equal(m.fieldworkSnapshot(progress.production.field,[{...report,match_basis:'source_case_or_link'}]).latestDate,'2026-10-20');assert.equal(m.fieldworkSnapshot(progress.production.field,[{...report,date:'2026-02-31'}]).latestDate,null);
});
