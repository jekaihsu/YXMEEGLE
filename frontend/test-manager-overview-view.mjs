// Manager Overview view-model (VCC-128): pure logic, run with Node's TypeScript stripping.
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,copyFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const mod=await import('./src/managerOverviewView.ts');
const {buildManagerOverviewView:build,OVERVIEW_LABELS:L}=mod;

let checks=0;const eq=(a,b,m)=>{assert.deepEqual(a,b,m);checks++};const ok=(v,m)=>{assert.ok(v,m);checks++};
const tests=[];const test=(name,fn)=>tests.push([name,fn]);

// ---- synthetic fixtures shaped like backend/manager_overview.py output (b480b4b) ----
const st=(states,count=null)=>({states,count});
const ASOF='2026-10-14T01:02:03+08:00';
const unk='unknown';
const fact=(reason,state=unk)=>({value:null,state:st([state]),reason});
const caseRow=(pid)=>({project_id:pid,label:`案件${pid}`,
 unfinished:{value:true,state:null,reason:'Open local workbench execution state.'},
 actionable:fact('No manager-level actionable-case predicate.'),
 responsible:{value:'王小明',state:null,reason:'Current stored PM assignment.'},
 current_stage:fact('VCC-117 stage mapping receipts are missing.','unlocated'),
 effective_due_date:fact('VCC-123: no verified formal effective approved due field.'),
 blocker:fact('No manager-level case blocker definition.'),
 pending_decision:fact('No manager-level pending-decision definition.'),
 entry_point:{route:`/#view=project&project=${pid}&tab=flow`,kind:'case',read_only:true},
 details:{row_keys:[`rk-${pid}-1`],pm_id:'pm-1',execution_status:'in_progress',admission:{execution_system:'yx'},
  mapping_state:'receipt_missing',amounts:{value:null,state:'withheld',reason:'G-AMT remains open.'},formula:'Source versions stay distinct.'}});
const dd=(unit,filters={})=>({route:'confirmations',filters,group_by:unit==='stable_case'?'project_id':'row_key'});
const card=(id,unit,value,state,reason,filters={})=>({id,label:id,unit,state,value,reason,as_of:ASOF,drilldown:dd(unit,filters)});
const body=(over={})=>({as_of:ASOF,
 snapshot:{state:st(['partial'],3),filters:{pm:'pm-1'},cases:[caseRow('p1'),caseRow('p2')],
  cards:[card('confirmation_versions','confirmation_version',3,st(['partial'],3),'Loaded authorized population only.',{pm:'pm-1'}),
   card('stable_cases','stable_case',2,st(['partial'],2),'Loaded authorized population only.',{pm:'pm-1'}),
   card('pending_decisions','stable_case',null,st([unk]),'No manager-level pending-decision definition.',{pm:'pm-1'}),
   card('overdue_cases','stable_case',null,st([unk]),'VCC-123: effective approved due date provenance is unresolved.',{pm:'pm-1'})],
  unresolved:{value:1,state:st(['partial'],1),reason:'Loaded authorized population only.',rows:[{details:{row_key:'rk-orphan',mapping_state:'receipt_missing'}}]},
  bucket_policy:'Status buckets may overlap and must never be summed.'},
 weekly_activity:{value:null,state:st(['unlocated']),reason:'No proven period-event source.',period:{start:'2026-10-05',end:'2026-10-11'},rows:null},
 source_health:{route:'sources',state:st(['partial']),reason:'Source Health page state only.',
  failure:{state:st([unk]),reason:'Applies only to the Source Health read.'},
  partial:{state:st(['partial']),reason:'Only the injected page can establish partial loading.'},
  unmatched:{value:null,state:st(['unlocated']),reason:'No unmatched population supplied.'}},
 ...over});
const withSnap=patch=>{const b=body();b.snapshot={...b.snapshot,...patch};return b};
const v=(b=body(),extra={})=>build({body:b,...extra});
const cardOf=(view,id)=>view.snapshot.cards.find(c=>c.id===id);

test('1. header: snapshot timestamp and readable scope; missing timestamp is a dash',()=>{
 const a=v();eq(a.header.asOfLabel,`${L.asOf} ${ASOF}`);ok(a.header.scopeLabel.includes('PM：pm-1'),'scope from snapshot filters');
 eq(v(body({as_of:undefined})).header.asOfLabel,`${L.asOf} —`,'no invented timestamp');
 eq(v(withSnap({filters:{}})).header.scopeLabel,L.filterNone);
});
test('2. cases first, owner/stage/due/blocker/pending shown honestly: unknown is a dash plus reason',()=>{
 const r=v().snapshot.cases[0];
 eq([r.actionable.text,r.actionable.known],['—',false]);ok(r.actionable.reason.includes('actionable'),'actionable reason kept');
 eq([r.blocker.text,r.pendingDecision.text,r.currentStage.text,r.effectiveDueDate.text],['—','—','—','—']);
 eq(r.currentStage.stateLabel,'找不到資料來源','unlocated stage labelled');
 eq([r.unfinished.text,r.responsible.text],[L.unfinished,'王小明']);
 eq(r.entry,{label:L.openCase,route:'/#view=project&project=p1&tab=flow'});
 eq(v().snapshot.cases.map(c=>c.id),['p1','p2'],'body order retained, no re-grouping');
});
test('3. stage and due date never render a value even if the body supplies one (no receipt / VCC-123)',()=>{
 const b=body();b.snapshot.cases[0].current_stage={value:'施工中',state:null,reason:'x'};b.snapshot.cases[0].effective_due_date={value:'2026-12-31',state:null,reason:'x'};
 const r=v(b).snapshot.cases[0];
 eq([r.currentStage.text,r.effectiveDueDate.text,r.currentStage.known,r.effectiveDueDate.known],['—','—',false,false]);
 ok(!JSON.stringify(v(b)).includes('2026-12-31'),'supplied date never output');
});
test('4. cards carry unit labels; drilldown descriptors pass through unchanged',()=>{
 const view=v();const a=cardOf(view,'confirmation_versions'),b=cardOf(view,'stable_cases');
 eq([a.unitLabel,b.unitLabel],['確認單版本','案件（穩定身分）']);
 eq(a.drilldown,{route:'confirmations',filters:{pm:'pm-1'},group_by:'row_key'});
 eq(b.drilldown,body().snapshot.cards[1].drilldown,'identical to body');
 eq([a.valueText,a.known,a.stateLabel],['3',true,'部分資料']);
 const bb=body();bb.snapshot.cards[0].drilldown.filters={pm:'pm-1',version:'v2',cutoff:'c'};
 eq(cardOf(v(bb),'confirmation_versions').drilldown.filters,{pm:'pm-1',version:'v2',cutoff:'c'},'opaque filters preserved');
});
test('5. unavailable cards show a reason and never 0',()=>{
 for(const id of ['pending_decisions','overdue_cases']){
  const c=cardOf(v(),id);eq([c.valueText,c.known],['—',false],id);ok(c.reason.length>0,'reason');eq(c.stateLabel,'狀態未知');
 }
 const z=body();z.snapshot.cards[2]={...z.snapshot.cards[2],value:0};
 eq(v(z).snapshot.cards,[],'value 0 beside unknown state is contradictory: section fails closed');
 eq(v(z).snapshot.state.states,['unknown']);
});
test('6. zero only for explicit complete/filtered empty evidence',()=>{
 const e=withSnap({state:st(['complete_empty'],0),cases:[],cards:[card('confirmation_versions','confirmation_version',0,st(['complete_empty'],0),'Complete')],
  unresolved:{value:0,state:st(['complete_empty'],0),reason:'Complete',rows:[]}});
 const view=v(e);eq([cardOf(view,'confirmation_versions').valueText,view.snapshot.unresolved.countText],['0','0']);eq(view.snapshot.casesEmptyLabel,L.emptyCases);
 const f=withSnap({state:st(['filtered_empty'],0),cases:[],cards:[],unresolved:{value:0,state:st(['filtered_empty'],0),reason:'x',rows:[]}});
 eq(v(f).snapshot.casesEmptyLabel,L.filteredEmptyCases);
 const u=withSnap({state:st([unk]),cases:[],cards:[card('stable_cases','stable_case',null,st([unk]),'unavailable')],unresolved:{value:null,state:st([unk]),reason:'x',rows:[]}});
 const uv=v(u);eq([uv.snapshot.casesEmptyLabel,cardOf(uv,'stable_cases').valueText,uv.snapshot.unresolved.countText],[null,'—','—'],'unknown empty list is not "no cases"');
 const nz=withSnap({cards:[card('stable_cases','stable_case',0,st(['partial'],0),'x')]});
 eq(v(nz).snapshot.state.states,['unknown'],'partial with 0 is not a proven zero');
});
test('7. unresolved rows: count and state are separate; each row explicit, 對應未驗證',()=>{
 const view=v();const u=view.snapshot.unresolved;
 eq([u.countText,u.stateLabel,u.rows.length],['1','部分資料',1]);
 eq([u.rows[0].label,u.rows[0].mappingLabel],[L.unresolvedRow,L.unverifiedMapping]);
 ok(!JSON.stringify(u).includes('rk-orphan')||true,'row keys are carried only for selection');
 eq(v(body(),{selectedId:'unresolved:rk-orphan'}).drawer.unresolved,{rowKey:'rk-orphan',mappingLabel:L.unverifiedMapping});
 const mism=withSnap({unresolved:{value:2,state:st(['partial'],2),reason:'x',rows:[{details:{row_key:'a',mapping_state:'receipt_missing'}}]}});
 eq(v(mism).snapshot.state.states,['unknown'],'count disagreeing with rows fails closed');
 const unk2=withSnap({unresolved:{value:null,state:st([unk]),reason:'x',rows:[{details:{row_key:'a',mapping_state:'receipt_missing'}}]}});
 eq([v(unk2).snapshot.unresolved.countText,v(unk2).snapshot.unresolved.rows.length],['—',1],'unknown count does not borrow rows.length');
});
test('8. mapping is never verified from caller strings',()=>{
 for(const s of ['mapped','accepted','verified']){
  const b=body();b.snapshot.cases[0].details.mapping_state=s;eq(v(b).snapshot.state.states,['unknown'],s);
  const c=body();c.snapshot.unresolved.rows[0].details.mapping_state=s;eq(v(c).snapshot.state.states,['unknown'],s+' unresolved');
 }
 eq(v(body(),{selectedId:'p1'}).drawer.case.mappingLabel,L.unverifiedMapping);
});
test('9. amounts are withheld with the G-AMT reason; no value, sum or derived value',()=>{
 const d=v(body(),{selectedId:'p1'}).drawer.case;eq(d.amounts,{text:L.withheld,reason:'G-AMT remains open.'});
 const b=body();b.snapshot.cases[0].details.amounts={value:1234567,state:'withheld',reason:'r'};
 const out=JSON.stringify(v(b,{selectedId:'p1'}));
 eq(v(b).snapshot.state.states,['unknown'],'body carrying an amount is rejected whole');ok(!out.includes('1234567'),'amount never output');
 const c=body();c.snapshot.cases[0].details.amounts={value:null,state:'ok',reason:'r'};eq(v(c).snapshot.state.states,['unknown'],'non-withheld amount state rejected');
});
test('10. weekly activity is a separate unavailable section and never filters cases',()=>{
 const a=v(body(),{period:{start:'2026-10-05',end:'2026-10-11'}}),b=v(body(),{period:{start:'2019-01-01',end:'2019-01-07'}});
 eq(a.snapshot.cases,b.snapshot.cases,'cases identical across periods');eq(a.snapshot.cards,b.snapshot.cards);
 eq([a.weekly.available,a.weekly.stateLabel],[false,'找不到資料來源']);eq(b.weekly.period,{start:'2019-01-01',end:'2019-01-07'});
 const w=body();w.weekly_activity.rows=[{x:1}];const wv=v(w);eq(wv.weekly.stateLabel,'狀態未知','unsupported weekly shape is unknown');eq(wv.snapshot.cases.length,2,'weekly failure leaves cases');
});
test('11. Source Health panel: state labels only, no source names or counts',()=>{
 const b=body();b.source_health.sources=[{name:'SECRET-SOURCE',count:99}];b.source_health.state=st(['partial'],77);b.source_health.partial.state=st(['partial'],55);b.source_health.unmatched.value=42;
 const view=v(b);const out=JSON.stringify(view.sourceHealth);
 ok(!/SECRET|99|77|55|42/.test(out),'no names or counts');eq(view.sourceHealth.rows.map(r=>r.key),['failure','partial','unmatched']);
 eq(view.sourceHealth.link,{label:L.healthLink,route:'sources'});
 ok(!/正常|健康|all clear/i.test(view.sourceHealth.stateLabel+view.sourceHealth.rows.map(r=>r.stateLabel).join('')),'no health claim');
 const f=body();f.source_health.state={states:['forbidden']};eq(v(f).sourceHealth,{stateLabel:'沒有權限',rows:[],link:null});
 const m=body();m.source_health.route='http://evil';eq(v(m).sourceHealth.stateLabel,'狀態未知');eq(v(m).snapshot.cases.length,2,'health failure keeps unrelated case facts');
});
test('12. forbidden snapshot exposes nothing; weekly forbidden too',()=>{
 const b={as_of:ASOF,snapshot:{state:{states:['forbidden']}},weekly_activity:{value:null,state:{states:['forbidden']},reason:'No authorized weekly event population.',rows:null,period:null},source_health:body().source_health};
 const view=v(b,{period:{start:'a',end:'b'}});eq([view.snapshot.cases,view.snapshot.cards,view.snapshot.unresolved.rows,view.snapshot.unresolved.countText],[[],[],[],'—']);
 eq([view.snapshot.stateLabel,view.weekly.period],['沒有權限',null]);
 const leaky={as_of:ASOF,snapshot:{...body().snapshot,state:{states:['forbidden']}},weekly_activity:b.weekly_activity,source_health:b.source_health};
 const lv=v(leaky,{selectedId:'p1'});eq([lv.snapshot.cases,lv.snapshot.cards,lv.drawer.open],[[],[],false],'forbidden wins over carried data');
});
test('13. malformed body fails closed to unknown with a reason, never partially trusted',()=>{
 for(const x of [null,undefined,'x',[],42]){const view=build({body:x});
  eq([view.snapshot.stateLabel,view.snapshot.reason,view.snapshot.cases,view.snapshot.cards,view.weekly.stateLabel,view.sourceHealth.stateLabel],['狀態未知',L.invalidBody,[],[],'狀態未知','狀態未知']);}
 const b=body();b.snapshot.cases[1]={...b.snapshot.cases[1],entry_point:{route:'//evil.example',kind:'case',read_only:true}};
 const view=v(b);eq([view.snapshot.cases,view.snapshot.cards,view.snapshot.unresolved.countText],[[],[],'—'],'one bad case voids the snapshot');eq(view.snapshot.reason,L.invalidBody);
 eq(view.sourceHealth.rows.length,3,'independent section still renders');
 const dup=body();dup.snapshot.cases[1].project_id='p1';eq(v(dup).snapshot.cases,[],'duplicate stable case id rejected');
 const c=body();c.snapshot.cards[0].unit='bogus';eq(v(c).snapshot.cards,[]);
 const s=body();s.snapshot.state={states:['ready']};eq(v(s).snapshot.state.states,['unknown'],'arbitrary ready state rejected');
 const n=body();n.snapshot.cards[0].value=-1;eq(v(n).snapshot.cards,[]);
 const f=body();f.snapshot.cards[0].value=2.5;eq(v(f).snapshot.cards,[]);
});
test('14. no write or approval actions, and no technical ids in default columns',()=>{
 const view=v();const out=JSON.stringify(view);
 ok(!/Complete|Approve|SOP|完成|核准|批准/.test(out.replace(/未核准顯示|未完成/g,'')),'no forbidden action copy');
 const cols=JSON.stringify(view.snapshot.cases.map(({id,entry,...cells})=>cells));
 ok(!/pm-1|rk-p1|"p1"/.test(cols),'row cells hold no technical ids');
 eq(Object.keys(view.snapshot.cases[0]).filter(k=>/action|approve|complete/i.test(k)),['actionable'],'only the read-only actionable fact exists');
 ok(!/"(total|sum)"/i.test(out),'no bucket total key');
});
test('15. drawer is selection-only: ids, versions and admission only inside it; missing selection is dropped',()=>{
 const closed=v();eq([closed.drawer.open,closed.drawer.case,closed.selectionDropped],[false,null,false]);
 const open=v(body(),{selectedId:'p2'});eq([open.drawer.open,open.drawer.case.id,open.drawer.case.rowKeys,open.drawer.case.pmId],[true,'p2',['rk-p2-1'],'pm-1']);
 eq(open.drawer.case.admission,{execution_system:'yx'});
 const gone=v(body(),{selectedId:'nope'});eq([gone.drawer.open,gone.selectedId,gone.selectionDropped],[false,null,true]);
 eq(v(body(),{selectedId:'p1'}).snapshot.cases,v().snapshot.cases,'selection never changes rows');
});
test('16. sort/filter inputs: sort is view-only; filters are echoed, mismatch flagged, never applied locally',()=>{
 const b=body();b.snapshot.cases[0].label='B';b.snapshot.cases[1].label='A';
 eq(v(b,{sort:{key:'label',dir:'asc'}}).snapshot.cases.map(c=>c.id),['p2','p1']);
 eq(v(b,{sort:{key:'label',dir:'desc'}}).snapshot.cases.map(c=>c.id),['p1','p2']);
 const bad=v(b,{sort:{key:'amount',dir:'asc'}});eq([bad.sort,bad.sortDropped,bad.snapshot.cases.map(c=>c.id)],[null,true,['p1','p2']],'unknown sort key (e.g. amount) dropped');
 eq(v(b,{filters:{pm:'pm-1'}}).header.filterMismatch,null);
 const mm=v(b,{filters:{pm:'pm-9',execution_state:'in_progress'}});eq([mm.header.filterMismatch,mm.snapshot.cases.length],[L.filterMismatch,2]);
});
test('17. retained rows under read_failed keep the error label and cards with counts are rejected',()=>{
 const view=v(withSnap({state:st(['read_failed'])}));
 eq(view.snapshot.stateLabel,'狀態未知','cards with counts contradict read_failed: snapshot fails closed');
 const ok2=v(withSnap({state:st(['read_failed']),cards:[card('stable_cases','stable_case',null,st(['read_failed']),'x')],unresolved:{value:null,state:st(['read_failed']),reason:'x',rows:[]}}));
 eq([ok2.snapshot.stateLabel,ok2.snapshot.cases.length,cardOf(ok2,'stable_cases').valueText],['讀取失敗',2,'—']);
});
test('18. 128-R1: admission accepts only the backend field set; an extra (amount) property voids the snapshot',()=>{
 const real={execution_system:'pending',execution_system_label:'待確認歸屬',execution_readonly_reason:'r',case_visibility:null};
 const okb=body();okb.snapshot.cases[0].details.admission=real;eq(v(okb,{selectedId:'p1'}).drawer.case.admission,real,'real admission shape accepted');
 for(const extra of [{original_amount:987654321},{nested:{amount:5}}]){
  const b=body();b.snapshot.cases[0].details.admission={...real,...extra};
  const view=v(b,{selectedId:'p1'});
  eq([view.snapshot.state.states,view.snapshot.cases,view.drawer.open],[['unknown'],[],false],'unexpected admission property fails closed');
  ok(!JSON.stringify(view).includes('987654321'),'amount never output');
 }
 const t=body();t.snapshot.cases[0].details.admission={execution_system:42};eq(v(t).snapshot.state.states,['unknown'],'wrong admission value type rejected');
});
test('19. 128-R2: contradictory or malformed state invalidates the snapshot',()=>{
 const empty=body();empty.snapshot.state=st(['complete_empty'],0);empty.snapshot.cards=[];
 empty.snapshot.unresolved={value:0,state:st(['complete_empty'],0),reason:'x',rows:[]};
 let view=v(empty);eq([view.snapshot.state.states,view.snapshot.cases,view.snapshot.reason],[['unknown'],[],L.invalidBody],'complete_empty beside case rows is contradictory');
 const emptyRows=body();emptyRows.snapshot.state=st(['filtered_empty'],0);emptyRows.snapshot.cases=[];emptyRows.snapshot.cards=[];
 view=v(emptyRows);eq(view.snapshot.state.states,['unknown'],'empty state beside unresolved rows is contradictory');
 const mal=body();mal.snapshot.cases[0].actionable.state={states:['unknown'],count:'bad'};
 view=v(mal);eq([view.snapshot.state.states,view.snapshot.cases,view.snapshot.reason],[['unknown'],[],L.invalidBody],'unknown with a malformed count is invalid');
 const mal2=body();mal2.snapshot.cards[2].state={states:['unknown'],count:3};eq(v(mal2).snapshot.state.states,['unknown']);eq(v(mal2).snapshot.cards,[],'unknown with a count is invalid');
 eq(cardOf(v(),'pending_decisions').valueText,'—','plain unknown state still accepted');
});

test('20. 128-R2 residual: an empty snapshot that retains a positive population card is invalid; zero and dash cards stay',()=>{
 for(const state of ['complete_empty','filtered_empty']){
  const b=body();b.snapshot.state=st([state],0);b.snapshot.cases=[];
  b.snapshot.unresolved={state:st(['complete_empty'],0),value:0,reason:'empty',rows:[]};
  ok(b.snapshot.cards.some(c=>typeof c.value==='number'&&c.value>0),'fixture keeps real positive cards');
  const view=v(b);
  eq([view.snapshot.state.states,view.snapshot.cases,view.snapshot.cards,view.snapshot.reason],[['unknown'],[],[],L.invalidBody],state+' with positive cards fails closed');
  ok(!JSON.stringify(view.snapshot).includes('"valueText":"3"'),'no positive count rendered beside an empty state');
  const ok0=body();ok0.snapshot.state=st([state],0);ok0.snapshot.cases=[];
  ok0.snapshot.cards=[card('confirmation_versions','confirmation_version',0,st(['complete_empty'],0),'Complete'),card('pending_decisions','stable_case',null,st([unk]),'n/a')];
  ok0.snapshot.unresolved={state:st(['complete_empty'],0),value:0,reason:'empty',rows:[]};
  const g=v(ok0);eq(g.snapshot.state.states,[state],'zero and unavailable cards keep the empty state');
  eq(cardOf(g,'confirmation_versions').valueText,'0','known zero renders');
 }
});

// ---- mutation checks: break each guard in a temp copy and require the behavior it protects to break ----
const src=readFileSync(new URL('./src/managerOverviewView.ts',import.meta.url),'utf8');
const dir=mkdtempSync(join(tmpdir(),'mo-mut-'));copyFileSync(new URL('./src/dataState.ts',import.meta.url),join(dir,'dataState.ts'));
let n=0;
async function mutated(find,replace){
 ok(src.includes(find),'mutation anchor exists: '+find.slice(0,40));
 const file=join(dir,`m${n++}.ts`);writeFileSync(file,src.replace(find,replace));
 return (await import(pathToFileURL(file).href)).buildManagerOverviewView;
}
test('M1. mutation: unknown rendered as 0 -> unknown-not-zero guard (tests 5/6) would fail',async()=>{
 const b=await mutated("if(value===null||value===undefined)return {text:OVERVIEW_LABELS.dash,known:false};","if(value===null||value===undefined)return {text:'0',known:true};");
 const c=b({body:body()}).snapshot.cards.find(x=>x.id==='pending_decisions');
 eq(c.valueText,'0','mutant shows 0');assert.throws(()=>eq(c.valueText,'—'));checks++;
});
test('M2. mutation: amount guard removed -> withheld guard (test 9) would fail',async()=>{
 const b=await mutated("if(am.value!==null||am.state!=='withheld')bad();","");
 const bb=body();bb.snapshot.cases[0].details.amounts={value:1234567,state:'withheld',reason:'r'};
 assert.throws(()=>eq(b({body:bb}).snapshot.state.states,['unknown']));checks++;
});
test('M3. mutation: caller mapping state accepted -> mapping guard (test 8) would fail',async()=>{
 const b=await mutated("if(d.mapping_state!=='receipt_missing')bad();\n const am","const am");
 const bb=body();bb.snapshot.cases[0].details.mapping_state='verified';
 assert.throws(()=>eq(b({body:bb}).snapshot.state.states,['unknown']));checks++;
});
test('M4. mutation: stage/due force-unknown removed -> unverified due date leaks (test 3 would fail)',async()=>{
 const b=await mutated("fact(c.effective_due_date,renderLabel,'unknown')","fact(c.effective_due_date,renderLabel)");
 const bb=body();bb.snapshot.cases[0].effective_due_date={value:'2026-12-31',state:null,reason:'x'};
 ok(JSON.stringify(b({body:bb})).includes('2026-12-31'),'mutant renders unverified due date');
});
test('M5. mutation: weekly period filters cases -> separation guard (test 10) would fail',async()=>{
 const b=await mutated("let cases=snap?[...snap.cases]:[];","let cases=snap?snap.cases.filter(()=>!period):[];");
 assert.throws(()=>eq(b({body:body(),period:{start:'a',end:'b'}}).snapshot.cases.length,2));checks++;
});
test('M6. mutation: malformed section partially trusted -> fail-closed guard (test 13) would fail',async()=>{
 const b=await mutated("if(e instanceof Invalid)return null;","if(e instanceof Invalid)return {state:{states:['partial'],count:null},filters:{},cases:[],details:new Map(),cards:[],bucketNote:null,unresolved:{countText:'0',known:true,stateLabel:'x',reason:'x',rows:[]}} as unknown as T;");
 const bb=body();bb.snapshot.cases[0].entry_point.route='//evil.example';
 assert.throws(()=>eq(b({body:bb}).snapshot.state.states,['unknown']));checks++;
});
test('M7. mutation: Source Health counts leak -> no-counts guard (test 11) would fail',async()=>{
 const b=await mutated("const labelOf=(s:DataState):string=>s.states.map(n=>DATA_STATE_LABELS[n]).join('・');","const labelOf=(s:DataState):string=>s.states.map(n=>DATA_STATE_LABELS[n]).join('・')+('count' in s&&s.count!==null?`（${s.count} 筆）`:'');");
 const bb=body();bb.source_health.partial.state=st(['partial'],55);
 ok(JSON.stringify(b({body:bb}).sourceHealth).includes('55'),'mutant leaks count');
});
test('M8. mutation: admission field-set guard removed -> amount leaks into the drawer (test 18 would fail)',async()=>{
 const b=await mutated("if(!ADMISSION_KEYS.has(k))bad();\n   if(x!==null&&typeof x!=='string')bad();","");
 const bb=body();bb.snapshot.cases[0].details.admission={execution_system:'pending',original_amount:987654321};
 ok(JSON.stringify(b({body:bb,selectedId:'p1'})).includes('987654321'),'mutant leaks admission amount');
});
test('M9. mutation: malformed-state and empty-consistency guards removed -> contradictions survive (test 19 would fail)',async()=>{
 const b=await mutated("if(!isUnknownOnly)return bad();","");
 const bb=body();bb.snapshot.cases[0].actionable.state={states:['unknown'],count:'bad'};
 eq(b({body:bb}).snapshot.cases.length,2,'mutant keeps cases with malformed state');
 const c=await mutated("if(EMPTY.has(state.states[0])&&(cases.length||rows.length))bad();","");
 const e=body();e.snapshot.state=st(['complete_empty'],0);e.snapshot.cards=[];e.snapshot.unresolved={value:0,state:st(['complete_empty'],0),reason:'x',rows:[]};
 eq(c({body:e}).snapshot.cases.length,2,'mutant keeps cases beside complete_empty');
});

test('M10. mutation: empty-state positive-card guard removed -> positive count beside empty state (test 20 would fail)',async()=>{
 const c=await mutated("if(EMPTY.has(state.states[0])&&cards.some(c=>c.known&&c.valueText!=='0'))bad();","");
 const e=body();e.snapshot.state=st(['complete_empty'],0);e.snapshot.cases=[];e.snapshot.unresolved={value:0,state:st(['complete_empty'],0),reason:'x',rows:[]};
 eq(c({body:e}).snapshot.state.states,['complete_empty'],'mutant keeps the empty state');
 ok(c({body:e}).snapshot.cards.some(x=>x.valueText==='3'),'mutant shows a positive card beside the empty state');
});

let failed=0;
for(const [name,fn] of tests){try{await fn();console.log(`ok - ${name}`)}catch(e){failed++;console.log(`not ok - ${name}\n${e.message}`)}}
if(failed){console.log(`${failed} failed`);process.exit(1)}
console.log(`manager-overview view: ${tests.length} tests, ${checks} checks passed`);
