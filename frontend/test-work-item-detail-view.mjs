// Work Item Detail view-model (VCC-132): pure logic, run with Node's TypeScript stripping.
// Mutation mode: MUTATE=<name> node test-work-item-detail-view.mjs rewrites the module source
// in memory to break one guard; the matching test must then fail.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync,mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';

const MUTATIONS={
 'unknown-not-zero':[["unknownCell=(reason?:unknown):Cell=>({state:'unknown',text:WORK_ITEM_LABELS.unknown","unknownCell=(reason?:unknown):Cell=>({state:'unknown',text:'0'"]],
 'amount-withheld':[["amounts:withheld()},\n  planActual:planActual(rec(body.plan_actual))","amounts:{state:'known',text:String(rec(wc?.amounts)?.value??'0')}},\n  planActual:planActual(rec(body.plan_actual))"]],
 'forbidden-absent':[["if(!page.states.every(s=>s==='partial'||s==='stale'))return base(onlyState('unknown',null,page));","if(page.states.includes('forbidden')===false&&false)return base(onlyState('unknown',null,page));"]],
 'fail-closed':[["if(!rows)return failed('unknown','malformed_section') as Section<T>;","if(!rows)return {state,rows:[],emptyRow:null,reason:null};"]],
 'receipt-missing':[["const VERIFICATION=WORK_ITEM_LABELS.receiptMissing;","const VERIFICATION='已驗證';"]],
 'evidence-only':[["r.evidence_only!==true||",""]],
};
let target='./src/workItemDetailView.ts';
if(process.env.MUTATE){
 let src=readFileSync(new URL(target,import.meta.url),'utf8');
 for(const [from,to] of MUTATIONS[process.env.MUTATE]){assert.ok(src.includes(from),'mutation anchor missing');src=src.replace(from,to)}
 const dir=mkdtempSync(join(tmpdir(),'wid-'));
 for(const f of ['dataState.ts'])writeFileSync(join(dir,f),readFileSync(new URL(`./src/${f}`,import.meta.url)));
 writeFileSync(join(dir,'workItemDetailView.ts'),src);
 target=pathToFileURL(join(dir,'workItemDetailView.ts')).href;
}
const {buildWorkItemDetailView:build,WORK_ITEM_LABELS:L}=await import(target);

let checks=0;const eq=(a,b,m)=>{assert.deepEqual(a,b,m);checks++};const ok=(v,m)=>{assert.ok(v,m);checks++};
const tests=[];const test=(name,fn)=>tests.push([name,fn]);

const KEY='base1/tbl1/rec1';
const unk=reason=>({state:'unknown',value:null,reason});
const task=(id,extra={})=>({id,title:`任務 ${id}`,status:'in_progress',completed_at:null,input:'輸入',output:'輸出',required:true,...extra});
const nodeRow=(nid,tid,round,extra={})=>({instance_identity:{project_id:'p1',node_id:nid,task_id:tid,sop_round:round},
 node:{id:nid,key:'k',name:`節點 ${nid}`,status:'open',completed_at:null},task:task(tid),verification:'verified',history:[],operations:[],...extra});
const section=(state,rows,extra={})=>({read_state:{states:[state],count:null},rows,...extra});
const body=(over={})=>({
 read_state:{states:['partial'],count:null},as_of:'2026-10-13T00:00:00Z',
 header:{id:KEY,name:{state:'existing',values:['工作項甲']},category:'類別A',source_identity:{base_token:'base1',table_id:'tbl1',record_id:'rec1'},
  execution_state:{state:'existing',tasks:[{id:'t1',status:'in_progress',completed_at:null}]}},
 work_content:{read_state:{states:['unknown']},quantity:unk('quantity_field_unlocated'),unit:unk('unit_field_unlocated'),amounts:{state:'withheld',reason:'G-AMT approval absent'}},
 plan_actual:{read_state:{states:['unlocated']},available:false,reason:'Calculation contract not approved; same item, unit and period required'},
 work_orders:{read_state:{states:['unlocated']},rows:[],verification:'receipt_missing',reason:'G-RCODE: R01/R02/R09/R10 work-order models unverified',source_health_link:{view:'sources'}},
 side:{read_state:{states:['unknown']},effective_due:unk('VCC-123 formal deadline provenance unresolved'),pending_due:unk('requested_date_field_unlocated'),
  estimated_due:unk('estimated_date_field_unlocated'),source_updated_at:unk('source_updated_time_unlocated'),responsible_people:[],missing_edge_warnings:[]},
 case_daily_reports:{read_state:{states:['unlocated']},reason:'work-item daily-report edge unverified',link:{view:'project',project_id:'p1',tab:'daily'}},
 parents:section('partial',[{id:'c1',title:'合約項目一',item_number:'1',verification:'receipt_missing',confirmations:[{id:'f1',code:'確認-001',verification:'receipt_missing'}]}]),
 nodes:section('partial',[nodeRow('n1','t1',1,{history:[{instance_identity:{},opened_round:1,before:{status:'done',output:'舊輸出',completed_at:'2026-09-01'}}]})]),
 deliverables:section('partial',[{id:'a1',name:'檔案甲',created_at:'2026-09-02',kind:'attachment',relation_scope:'node',evidence_only:true},
  {id:'a2',name:'檔案乙',created_at:'2026-09-05',kind:'attachment',relation_scope:'work_item',evidence_only:true}],{reason:'evidence_is_not_workflow_completion'}),
 ...over});
const view=(over,ui)=>build({body:body(over),ui});
const dump=v=>JSON.stringify(v);

test('1. breadcrumb runs Confirmation → Contract Line → Work Item and tabs are the five named ones',()=>{
 const v=view();
 eq(v.breadcrumbs.length,1);
 const b=v.breadcrumbs[0];
 eq([b.confirmations[0].text,b.contractLine,b.workItem],['確認-001','合約項目一','工作項甲']);
 eq(v.tabs.map(t=>t.label),['工作內容','工單','工作流程節點／SOP','交付物','歷程']);
 eq([v.activeTab,v.tabs.filter(t=>t.active).length],['work_content',1],'Work Content open by default');
 eq(view({}, {tab:'bogus'}).activeTab,'work_content','invalid tab falls back');
 eq(view({}, {tab:'history'}).activeTab,'history');
});
test('2. unknown-not-zero: quantity, unit, plan/actual and dates render an em dash plus reason, never 0',()=>{
 const v=view();
 for(const c of [v.workContent.quantity,v.workContent.unit,v.side.dates.effectiveDue,v.side.dates.pendingDue,v.side.dates.estimatedDue,v.side.dates.sourceUpdatedAt]){
  eq([c.state,c.text],['unknown','—']);ok(c.reason&&c.reason!==L.reasonUnspecified,'has mapped reason');
 }
 eq([v.planActual.available,v.planActual.state.states],[false,['unlocated']]);
 ok(v.planActual.reason.includes('計算規則尚未核准'));
 ok(!/"text":"0"/.test(dump(v)),'no zero text');
 // a body that smuggles values for unproven fields is ignored
 const b=body();b.work_content.quantity={state:'existing',value:5,reason:'x'};b.side.effective_due={state:'existing',value:'2026-10-01'};
 const s=build({body:b});
 eq([s.workContent.quantity.text,s.side.dates.effectiveDue.text],['—','—']);
});
test('3. amount withheld: 未核准顯示 + G-AMT reason, no value even when the body carries one',()=>{
 const b=body();b.work_content.amounts={state:'known',value:123456,total:99999};
 const v=build({body:b});
 eq([v.workContent.amounts.state,v.workContent.amounts.text],['withheld','未核准顯示']);
 ok(v.workContent.amounts.reason.includes('G-AMT'));
 ok(!dump(v).includes('123456')&&!dump(v).includes('99999'),'no amount value or derived value');
});
test('4. work orders are unlocated with an explicit row and Source Health link; body rows never render',()=>{
 const b=body();b.work_orders.rows=[{id:'wo1',name:'偽工單'}];
 const v=build({body:b});
 eq([v.workOrders.rows,v.workOrders.emptyRow,v.workOrders.state.states,v.workOrders.verification],[[],'找不到資料來源',['unlocated'],'對應未驗證']);
 eq(v.workOrders.sourceHealthLink,{label:'前往來源健康',target:{view:'sources'}});
 ok(!dump(v).includes('偽工單'));
 eq(build({body:body({work_orders:{read_state:{states:['unlocated']},rows:[]}})}).workOrders.sourceHealthLink,null,'no link invented');
});
test('5. rework instances are distinct rows with round history; duplicate identity fails closed',()=>{
 const rows=[nodeRow('n1','t1',2,{history:[{opened_round:1,before:{status:'done',output:'o1',completed_at:'2026-09-01'}},{opened_round:2,before:{status:'done',output:'o2',completed_at:'2026-09-09'}}]}),nodeRow('n1','t1b',1),nodeRow('n1','t1',3)];
 const v=view({nodes:section('partial',rows)});
 eq(v.nodes.rows.length,3);eq(new Set(v.nodes.rows.map(r=>r.key)).size,3,'distinct keys');
 eq(v.nodes.rows[0].round.text,'第 2 輪');
 eq(v.nodes.rows[0].reworkRounds.map(r=>r.label),['開啟第 1 輪前的狀態','開啟第 2 輪前的狀態']);
 eq(v.history.rounds.length,2);
 const dup=view({nodes:section('partial',[nodeRow('n1','t1',1),nodeRow('n1','t1',1)])});
 eq([dup.nodes.rows.length,dup.nodes.state.states],[0,['unknown']],'duplicate identity untrusted');
});
test('6. receipt_missing renders 對應未驗證 and body claims of verified are never upgraded',()=>{
 const b=body();b.parents.rows[0].verification='verified';b.parents.rows[0].confirmations[0].verification='mapped';
 const v=build({body:b});
 eq([v.parents.rows[0].verification,v.parents.rows[0].confirmations[0].verification,v.nodes.rows[0].verification,v.breadcrumbs[0].verification],Array(4).fill('對應未驗證'));
 ok(!/已驗證|mapped|accepted/.test(dump(v)));
});
test('7. missing confirmation edge renders an explicit unresolved path, not a blank',()=>{
 const p={id:'c2',title:'合約項目二',confirmations:[],unresolved:{reason:'native_confirmation_edge_unresolved'}};
 const v=view({parents:section('partial',[p],{reason:'native_parent_edge_absent',unresolved:[{reason:'native_parent_edge_absent'}]}),side:{...body().side,missing_edge_warnings:['native_parent_edge_absent']}});
 eq([v.breadcrumbs[0].confirmationUnresolved,v.breadcrumbs[0].confirmations],[true,[]]);
 eq(v.side.warnings,['找不到原生上層關聯']);
 eq(view({parents:section('unlocated',[])}).parents.emptyRow,'找不到資料來源');
});
test('8. evidence rows are evidence-only, never completion; evidence cannot set execution state',()=>{
 const v=view();
 ok(v.deliverables.rows.every(r=>r.evidenceOnly===true&&r.note==='僅作證據，不代表完成'));
 eq(v.header.executionState.text,'in_progress','execution state only from task status');
 const none=view({header:{...body().header,execution_state:unk('no_work_item_execution_state')}});
 eq(none.header.executionState.text,'—','evidence present but state stays unknown');
 const bad=view({deliverables:section('partial',[{id:'a1',name:'x',kind:'attachment',relation_scope:'node'}])});
 eq([bad.deliverables.rows.length,bad.deliverables.state.states],[0,['unknown']],'row not marked evidence_only is untrusted');
});
test('9. deliverables sort by date (default desc) then stable id; undated last',()=>{
 const rows=['b','a','c','d'].map((id,i)=>({id,name:id,created_at:id==='d'?undefined:i<2?'2026-09-05':'2026-09-01',kind:'attachment',relation_scope:'node',evidence_only:true}));
 const names=ui=>view({deliverables:section('partial',rows)},ui).deliverables.rows.map(r=>r.name.text);
 eq(names(),['a','b','c','d'],'desc, id tiebreak, undated last');
 eq(names({sortDir:'asc'}),['c','a','b','d'],'asc keeps undated last');
});
test('10. case_daily_reports is a link-only entry with no count, no rows, no state count',()=>{
 const v=view();
 eq(Object.keys(v.caseDailyReports).sort(),['label','link','note']);
 eq(v.caseDailyReports.link.target,{view:'project',projectId:'p1',tab:'daily'});
 ok(!('count' in v.caseDailyReports)&&!('rows' in v.caseDailyReports));
 eq(view({case_daily_reports:{read_state:{states:['unlocated']},link:{view:'project',tab:'weekly',project_id:'p1'}}}).caseDailyReports.link,null,'bad link dropped');
 eq(view({case_daily_reports:{read_state:{states:['unlocated']}}}).caseDailyReports.link,null);
});
test('11. hand-built {states:[unlocated]} envelope without count normalizes safely',()=>{
 const v=view({case_daily_reports:{read_state:{states:['unlocated']},reason:'x'},work_orders:{read_state:{states:['unlocated']},rows:[]}});
 eq(v.workOrders.state.states,['unlocated']);
 ok(v.hasContent);
 // missing/garbage envelopes read unknown, not zero or empty
 eq(view({nodes:{rows:[]}}).nodes.state.states,['unknown']);
 eq(view({nodes:{read_state:{states:['unlocated'],count:3},rows:[]}}).nodes.state.states,['unknown'],'contradictory count');
});
test('12. side dates are four distinct unknown cells with distinct reasons',()=>{
 const d=view().side.dates;
 eq(new Set(Object.values(d).map(c=>c.reason)).size,4);
 ok(view().asOfLabel.includes('非來源更新時間'),'fetch time is not source time');
 eq(view({as_of:undefined}).asOfLabel,'—');
});
test('13. forbidden-absent: forbidden page renders only the state; forbidden section shows no rows or hints',()=>{
 const v=build({body:{read_state:{states:['forbidden'],count:5,name:'秘密'},header:{id:KEY},nodes:section('partial',[nodeRow('n1','t1',1)])}});
 eq([v.hasContent,v.pageState,v.header,v.nodes.rows],[false,{states:['forbidden']},null,[]]);
 ok(!dump(v).includes('秘密')&&!dump(v).includes('base1')&&!dump(v).includes('節點 n1'));
 const s=view({deliverables:{read_state:{states:['forbidden'],count:3},rows:[{id:'zz',name:'隱藏檔',evidence_only:true}]}});
 eq([s.deliverables.state.states,s.deliverables.rows,s.deliverables.emptyRow],[['forbidden'],[],null]);
 ok(!dump(s).includes('隱藏檔')&&!dump(s).includes('zz'));
});
test('14. missing selection (body is only unknown) shows state only, no key, count or label',()=>{
 const v=build({body:{read_state:{states:['unknown'],count:null}}});
 eq([v.hasContent,v.pageState.states,v.header,v.breadcrumbs],[false,['unknown'],null,[]]);
 ok(!dump(v).includes('base1'));
});
test('15. malformed body fails closed to unknown with a reason, never partially trusted',()=>{
 for(const bad of [null,undefined,'x',[],7,{},{read_state:'partial'},{read_state:{states:['partial']}},
  {...body(),header:{...body().header,id:'a/b'}},
  {...body(),header:{...body().header,source_identity:{base_token:'other',table_id:'tbl1',record_id:'rec1'}}},
  {...body(),read_state:{states:['complete_empty'],count:0}},{...body(),read_state:{states:['unknown','partial']}}]){
  const v=build({body:bad});
  eq([v.hasContent,v.header],[false,null],JSON.stringify(bad)?.slice(0,60));
  ok(v.pageState.states[0]!=='partial'||v.hasContent===false);
 }
 eq(build({body:null}).unknownReason,'回應格式不符，無法採信');
 // one malformed row poisons its whole section, not the others
 const v=view({nodes:section('partial',[nodeRow('n1','t1',1),{instance_identity:{}}])});
 eq([v.nodes.rows.length,v.nodes.state.states,v.nodes.reason],[0,['unknown'],'區段格式不符，無法採信']);
 ok(v.parents.rows.length===1,'other sections unaffected');
 eq(view({parents:'oops',deliverables:5}).deliverables.state.states,['unknown']);
 eq(view({nodes:section('partial',[nodeRow('n1','t1',-1)])}).nodes.rows.length,0,'negative round rejected');
});
test('16. IDs live only in the drawer model; default rows carry none',()=>{
 const v=view();
 const visible=dump({...v,drawer:null,nodes:{...v.nodes,rows:v.nodes.rows.map(r=>({...r,key:''}))},parents:{...v.parents,rows:v.parents.rows.map(r=>({...r,key:''}))},
  deliverables:{...v.deliverables,rows:v.deliverables.rows.map(r=>({...r,key:''}))},history:{...v.history,rounds:[]},ui:null,caseDailyReports:null});
 for(const id of ['base1','tbl1','rec1','"p1"','"n1"','"t1"','"c1"','"f1"','"a1"'])ok(!visible.includes(id),`${id} not in display model`);
 const d=view({}, {selectedKey:v.nodes.rows[0].key}).drawer;
 eq([d.open,d.model.kind],[true,'node']);
 ok(d.model.fields.some(f=>f.value==='n1')&&d.model.fields.some(f=>f.value==='t1'));
 eq(view({}, {selectedKey:'work_item'}).drawer.model.fields[0].value,KEY);
 eq(view({}, {selectedKey:v.deliverables.rows[0].key}).drawer.model.kind,'deliverable');
});
test('17. drawer is selection-only: stale selection dropped, never resurrected',()=>{
 const v=view({}, {selectedKey:'node:p9/n9/t9/1'});
 eq([v.drawer.open,v.drawer.model,v.ui.selectedKey,v.selectionDropped],[false,null,null,true]);
 eq(view().selectionDropped,false);
 eq(build({body:null,ui:{selectedKey:'work_item'}}).selectionDropped,true);
});
test('18. forbidden actions absent: no Complete/Approve/SOP write control or key anywhere',()=>{
 const s=dump(view({}, {selectedKey:'work_item'}));
 ok(!/"(actions?|onComplete|approve|complete|submit|retry)"/i.test(s),'no action keys');
 ok(!/>完成<|核准並|送出|重新提交|標記完成/.test(s.replace(L.operationUnknown,'')),'no write labels');
 const op=view({nodes:section('partial',[nodeRow('n1','t1',1,{operations:[{id:'j1',status:'outcome_unknown'}]})])});
 eq(op.nodes.rows[0].operationNote,L.operationUnknown,'unknown outcome says do not resubmit');
 ok(!dump(op).includes('j1'));
});
test('19. unknown body reason strings are not echoed (no ID smuggling through reasons)',()=>{
 const v=view({work_orders:{read_state:{states:['unlocated']},rows:[],reason:'secret-case-9999'},nodes:section('partial',[],{reason:'secret-case-9999'})});
 eq([v.workOrders.reason,v.nodes.reason],[L.reasonUnspecified,L.reasonUnspecified]);
 ok(!dump(v).includes('9999'));
});
test('20. history tab: completed history collapsed until expanded; round history always listed',()=>{
 const rows=[nodeRow('n1','t1',1,{task:task('t1',{completed_at:'2026-09-10'})})];
 const c=view({nodes:section('partial',rows)}),e=view({nodes:section('partial',rows)},{historyExpanded:true});
 eq([c.history.completed,e.history.completed.length],[null,1]);
});

let failed=0;
for(const [name,fn] of tests){try{await fn();console.log('ok',name)}catch(e){failed++;console.log('FAIL',name,'\n ',e.message.split('\n')[0])}}
console.log(`${tests.length-failed}/${tests.length} tests, ${checks} checks`);
process.exit(failed?1:0);
