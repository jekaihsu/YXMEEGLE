// My Work view-model (VCC-126): pure logic, run with Node's TypeScript stripping.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const mod=await import('./src/myWorkView.ts');
const {buildMyWorkView,encodeReturnContext,decodeReturnContext,MY_WORK_LABELS}=mod;

let checks=0;const eq=(a,b,m)=>{assert.deepEqual(a,b,m);checks++};const ok=(v,m)=>{assert.ok(v,m);checks++};
const tests=[];const test=(name,fn)=>tests.push([name,fn]);

const ep=(kind,extra={})=>({kind,exists:true,authorized:true,route:`/${kind}/x`,...extra});
const row=(id,extra={})=>({id,title:`任務 ${id}`,case_title:`案件 ${id}`,work_item_title:`工項 ${id}`,assignee_name:'我',workflow_state:'進行中',ended:false,...extra});
const view=(rows,extra={})=>buildMyWorkView({rows,readState:'ready',assignment:'assigned',canSeeAwaitingConfirmation:false,...extra});
const ids=v=>v.rows.map(r=>r.id);
const weekly=(start,end,items=[])=>({period:{start,end},items});

test('1. default table is all unfinished tasks across history; no due-date default filter',()=>{
 const rows=[row('old',{effective_due:{value:'2019-01-01',verified_formal:true}}),row('mid'),row('new',{effective_due:{value:'2030-01-01',verified_formal:true}}),row('done',{ended:true})];
 eq(ids(view(rows)),['mid','new','old'],'all history, finished excluded');
});
test('1b. changing the weekly-activity period never removes an unfinished task',()=>{
 const rows=[row('old',{effective_due:{value:'2019-01-01',verified_formal:true}}),row('cur')];
 const a=view(rows,{weeklyActivity:weekly('2026-10-05','2026-10-11',[{id:'w1',date:'2026-10-06'},{id:'w2',date:'2019-01-01'}])});
 const b=view(rows,{weeklyActivity:weekly('2018-12-30','2019-01-05',[{id:'w1',date:'2026-10-06'},{id:'w2',date:'2019-01-01'}])});
 eq(ids(a),ids(b),'main table identical across periods');
 eq(ids(a),['cur','old'],'older unfinished task still shown');
 eq(a.weekly.items.map(i=>i.id),['w1'],'weekly dataset follows its own period');
 eq(b.weekly.items.map(i=>i.id),['w2'],'weekly dataset changed');
});
test('2. mode toggle only with capability; awaiting is never approved/completed',()=>{
 const rows=[row('a'),row('b',{queue:'awaiting_my_confirmation'})];
 const off=view(rows,{filters:{mode:'awaiting_my_confirmation'}});
 eq([off.showModeToggle,off.mode,off.modes.map(m=>m.mode)],[false,'todo',['todo']],'toggle absent, forced to To Do');
 eq(ids(off),['a'],'awaiting rows not exposed without capability');
 const on=view(rows,{canSeeAwaitingConfirmation:true,filters:{mode:'awaiting_my_confirmation'}});
 eq([on.showModeToggle,on.mode,ids(on)],[true,'awaiting_my_confirmation',['b']],'awaiting mode offered');
 const label=JSON.stringify(on.rows[0]);
 ok(!/approved|completed|已核准|已完成/i.test(label.replace(/尚未核准/g,'')),'awaiting not labelled approved/completed');
 ok(on.rows[0].handoffLabel.includes('尚未核准'),'awaiting label says not yet approved');
 eq(ids(view(rows,{canSeeAwaitingConfirmation:true})),['a'],'To Do mode excludes awaiting rows');
});
test('3. filters and selection round-trip; stale/forbidden selection dropped',()=>{
 const ctx={search:'任務',mode:'awaiting_my_confirmation',selectedId:'b'};
 eq(decodeReturnContext(encodeReturnContext(ctx)),ctx,'round trip');
 eq(decodeReturnContext('not json'),{search:'',mode:'todo',selectedId:null},'garbage decodes to defaults');
 eq(decodeReturnContext(JSON.stringify({v:1,mode:'approve',selectedId:7})),{search:'',mode:'todo',selectedId:null},'invalid fields default');
 const rows=[row('a'),row('b',{queue:'awaiting_my_confirmation'})];
 const restored=view(rows,{canSeeAwaitingConfirmation:true,filters:decodeReturnContext(encodeReturnContext(ctx))});
 eq([restored.drawer.open,restored.filters],[true,ctx],'restored');
 const gone=view([row('a')],{canSeeAwaitingConfirmation:true,filters:ctx});
 eq([gone.drawer.open,gone.drawer.task,gone.filters.selectedId,gone.selectionDropped],[false,null,null,true],'missing task not resurrected');
 const forb=view([row('a'),row('b',{queue:'awaiting_my_confirmation',forbidden:true})],{canSeeAwaitingConfirmation:true,filters:ctx});
 eq([forb.drawer.open,forb.selectionDropped],[false,true],'forbidden task selection dropped');
 const lost=view(rows,{canSeeAwaitingConfirmation:false,filters:ctx});
 eq([lost.mode,lost.drawer.open],['todo',false],'revoked capability drops awaiting selection');
});
test('4. drawer is open only when a task is selected',()=>{
 const rows=[row('a'),row('b')];
 eq(view(rows).drawer,{open:false,task:null},'closed with no selection');
 const sel=view(rows,{filters:{selectedId:'b'}});
 eq([sel.drawer.open,sel.drawer.task.id],[true,'b'],'open on select');
 eq(view(rows,{filters:{selectedId:null}}).drawer.open,false,'deselect closes');
 eq(view(rows,{filters:{selectedId:'zzz'}}).drawer.open,false,'unknown id never opens');
});
test('5. page states stay distinct; unknown is never zero; forbidden leaks nothing',()=>{
 const state=v=>v.pageState&&v.pageState.states;
 eq(state(buildMyWorkView({rows:[],readState:'ready',assignment:'unassigned'})),['complete_empty'],'unassigned');
 eq(buildMyWorkView({rows:[],readState:'ready',assignment:'unassigned'}).emptyReason,'unassigned','unassigned reason');
 const none=buildMyWorkView({rows:[],readState:'ready',assignment:'assigned'});
 eq([state(none),none.emptyReason,none.count],[['complete_empty'],'no_pending',0],'genuinely none pending');
 eq(state(buildMyWorkView({rows:[],readState:'ready'})),['unknown'],'empty with unknown assignment is not claimed empty');
 eq(state(view([row('a')],{filters:{search:'zzz'}})),['filtered_empty'],'filtered empty');
 eq(state(buildMyWorkView({rows:[]})),['loading'],'not loaded');
 eq(state(buildMyWorkView({rows:[],readState:{states:['read_failed'],count:null}})),['read_failed'],'read failed');
 eq(state(buildMyWorkView({rows:[row('a')],readState:{states:['unlocated']}})),['unlocated'],'unlocated');
 const part=buildMyWorkView({rows:[row('a')],readState:{states:['partial','stale'],count:null}});
 eq([state(part),part.count,ids(part)],[['partial','stale'],null,['a']],'partial+stale keep rows, no invented count');
 const unk=buildMyWorkView({rows:[row('a')],readState:{states:['unknown'],count:0}});
 eq([state(unk),unk.count,unk.rows.length],[['unknown'],null,0],'unknown has no count and no rows');
 const noRows=buildMyWorkView({readState:'ready'});
 eq([state(noRows),noRows.count],[['unknown'],null],'missing rows is unknown, not an empty dataset');
 const f=buildMyWorkView({rows:[row('a')],readState:{states:['forbidden'],count:3,name:'機密'},filters:{selectedId:'a',search:'x'}});
 eq([f.pageState,f.count,f.rows,f.drawer.open],[{states:['forbidden']},null,[],false],'forbidden exposes nothing');
 ok(!JSON.stringify(f).includes('機密')&&!JSON.stringify(f).includes('任務'),'forbidden leaks no name or row');
 const malformed=view([row('a'),{title:'no id'},null,'x']);
 eq([state(malformed),ids(malformed)],[['partial'],['a']],'malformed rows mark partial, not dropped silently');
 eq(state(view([row('a'),row('a')])),['partial'],'duplicate ids are partial');
 eq(state(view([row('a')])),null,'clean read has no page-level state');
 const stale=buildMyWorkView({rows:[],readState:{states:['stale'],count:null},assignment:'assigned'});
 eq([state(stale),stale.count,stale.emptyReason],[['stale'],null,null],'stale with unknown count stays unknown, never zero or no_pending');
 const known=buildMyWorkView({rows:[],readState:{states:['stale'],count:2},assignment:'assigned'});
 eq([state(known),known.count,known.emptyReason],[['stale'],2,null],'a supplied known stale count passes through');
});
test('6. due date only when verified formal; evidence never completes',()=>{
 const v=view([row('a',{effective_due:{value:'2026-10-20',verified_formal:true}}),row('b',{effective_due:{value:'2026-10-20'}}),row('c',{due_date:'2026-10-20',estimated_due:'2026-10-21'}),row('d',{effective_due:{value:'2026-10-20',verified_formal:'true'}})]);
 const by=Object.fromEntries(v.rows.map(r=>[r.id,r.dueLabel]));
 eq(by,{a:'2026-10-20',b:'unknown',c:'unknown',d:'unknown'},'only verified formal date shown');
 const e=view([row('e',{evidence:[{id:'doc1',title:'交付文件'}],ended:undefined})]);
 eq(ids(e),['e'],'evidence does not remove task from table');
 eq([e.rows[0].evidencePresent,e.rows[0].finishedKnown],[true,false],'evidence is only a fact');
 ok(!/完成|completed/i.test(e.rows[0].statusLabel+e.rows[0].workflowLabel),'no completed label from evidence');
 eq(view([row('e',{evidence:[{id:'d'}],ended:undefined})]).pageState.states,['partial'],'unverified finish state is flagged');
});
test('7. actions are navigation only for existing+authorized entries; unknown outcome blocks resubmit',()=>{
 const entries=[ep('task'),ep('case',{exists:false}),ep('document',{authorized:false}),ep('work_item',{authorized:'yes'}),ep('delivery'),ep('confirmation'),ep('complete'),ep('approve'),ep('write'),ep('document',{route:'https://evil.example/x'}),ep('case',{route:'//evil'})];
 const r=view([row('a',{entry_points:entries})]).rows[0];
 eq(r.actions.map(a=>a.kind),['task','delivery','confirmation'],'only verified navigation kinds');
 ok(r.actions.every(a=>a.route.startsWith('/')&&Object.keys(a).sort().join()==='kind,label,route'),'descriptors are navigation only');
 const u=view([row('a',{entry_points:entries,operation_outcome:'unknown'})]).rows[0];
 eq(u.actions.map(a=>a.kind),['task'],'unknown outcome removes delivery/confirmation');
 eq(u.outcomeNote,MY_WORK_LABELS.outcomeUnknown,'unknown outcome explained');
 eq(view([row('a',{entry_points:entries,operation_outcome:'garbage'})]).rows[0].actions.map(a=>a.kind),['task'],'unrecognised outcome treated as unknown');
 eq(view([row('a')]).rows[0].actions,[],'no entry points, no actions');
 ok(!JSON.stringify(Object.values(MY_WORK_LABELS.actions)).match(/Complete|Approve|完成|核准/),'no write-style labels exist');
});
test('8. text status labels and stable sort; retrieval time is not a key',()=>{
 const rows=[row('c'),row('z',{pending_reason:'等待客戶'}),row('a',{attention:true}),row('d',{attention:true,retrieved_at:'2000-01-01',updated_at:'1999'}),row('e',{retrieved_at:'2030-01-01'})];
 const v=view(rows);
 eq(ids(v),['a','d','z','c','e'],'attention, pending (sorts after ordinary ids), rest; id tiebreak');
 eq(ids(view([...rows].reverse())),ids(v),'input order does not matter');
 eq(ids(view(rows.map(r=>({...r,retrieved_at:'2099-01-01'})))),ids(v),'retrieval time does not affect order');
 ok(v.rows.every(r=>r.statusLabel&&/[一-鿿A-Za-z]/.test(r.statusLabel)),'every status has text');
 eq(v.rows[0].statusLabel,MY_WORK_LABELS.attention,'attention is text');
});
test('shape tolerance: hostile input never throws and never invents values',()=>{
 for(const rows of [undefined,null,'x',7,{},[null],[[]],[{id:5}]]){
  const v=buildMyWorkView({rows,readState:'ready',assignment:'assigned'});
  ok(Array.isArray(v.rows),'rows array');
 }
 const r=view([{id:'x'}]).rows[0];
 eq([r.title,r.assignee,r.nextDeliverable,r.dueLabel],['unknown','unknown','unknown','unknown'],'missing fields read unknown');
 eq(view([row('a')],{filters:{search:'ＡＢ',mode:{},selectedId:{}}}).filters.mode,'todo','bad filters default');
 eq(ids(view([row('a',{title:'Hello World'}),row('b')],{filters:{search:'hello'}})),['a'],'search is case-insensitive');
});
test('module stays pure: no React, fetch or routing',()=>{
 const src=readFileSync(new URL('./src/myWorkView.ts',import.meta.url),'utf8');
 ok(!/from\s+['"](react|react-dom|react-router)|fetch\(|window\.|document\./.test(src),'no framework or network');
 ok(!/types|api\./.test(src.match(/import[^;]*;/g).join('')),'imports only dataState');
});

test('9. FIX1: revocation hides weekly; stale/unknown never invented; missing facts read unknown',()=>{
 const items=[{id:'SECRET-ID',title:'SECRET-NAME',date:'2026-10-13'}];
 for(const s of ['forbidden','loading','unlocated','read_failed','unknown']){
  const v=buildMyWorkView({readState:{states:[s],count:9,name:'SECRET-PAGE'},rows:[row('a')],weeklyActivity:{period:{start:'2026-10-12',end:'2026-10-18'},items}});
  eq(v.weekly.items,[],s+' weekly items empty');
  ok(!JSON.stringify(v).includes('SECRET'),s+' leaks nothing');
  ok(!('count' in v.weekly),s+' weekly has no count');
 }
 eq(buildMyWorkView({rows:[row('a')],readState:'ready',assignment:'assigned',weeklyActivity:{items}}).weekly.items.map(i=>i.id),['SECRET-ID'],'ready read keeps weekly');
 const bare={id:'a',ended:false};
 const r=buildMyWorkView({readState:'ready',rows:[bare],assignment:'assigned'}).rows[0];
 eq([r.handoffLabel,r.statusLabel],['unknown','unknown'],'missing handoff/status facts read unknown');
 const known=view([row('a',{handoff_state:'已交接'})]).rows[0];
 eq([known.handoffLabel,known.statusLabel],['已交接','unknown'],'handoff shown; no derived status from workflow_state');
 eq(known.workflowLabel,'進行中','workflow_state kept verbatim as source text');
});
test('10. FIX2: task-level revocation applies to every dataset; status needs a known vocabulary value',()=>{
 const items=[{id:'SECRET-ID',title:'SECRET-NAME',date:'2026-10-13'},{id:'OPEN-ID',title:'OPEN-NAME',date:'2026-10-13'}];
 const mk=forbidden=>view([row('SECRET-ID',{title:'SECRET-NAME',...(forbidden?{forbidden:true}:{})}),row('OPEN-ID',{title:'OPEN-NAME'})],{weeklyActivity:{items},filters:{selectedId:'SECRET-ID'}});
 eq(mk(false).weekly.items.map(i=>i.id),['SECRET-ID','OPEN-ID'],'control: not revoked keeps weekly');
 const d=mk(true);
 eq(d.weekly.items.map(i=>i.id),['OPEN-ID'],'revoked task removed from weekly, others kept');
 ok(!JSON.stringify(d).includes('SECRET'),'revoked task leaks nowhere');
 eq([d.drawer.open,d.filters.selectedId],[false,null],'selection cleared');
 const dup=view([row('SECRET-ID'),row('SECRET-ID',{forbidden:true})],{weeklyActivity:{items}});
 eq([ids(dup),dup.weekly.items.map(i=>i.id)],[[],['OPEN-ID']],'revocation wins over a duplicate allowed row');
 const bare={id:'a',ended:false};
 const label=extra=>view([{...bare,...extra}]).rows[0].statusLabel;
 for(const extra of [{workflow_state:'unknown'},{queue:'unknown'},{workflow_state:'garbage'},{workflow_state:'  '},{attention:false}])eq(label(extra),'unknown','not established: '+JSON.stringify(extra));
 });
test('11. FIX3: no derived in-progress claim; unknown pending sentinel stays unknown and ordinary',()=>{
 const bare={id:'a',ended:false};
 const one=extra=>view([{...bare,...extra}]).rows[0];
 for(const extra of [{workflow_state:'active'},{queue:'active'},{workflow_state:'in_progress'},{workflow_state:'進行中'},{workflow_state:'ACTIVE'},{queue:'in_progress'}]){
  const r=one(extra);eq(r.statusLabel,'unknown','no affirmative status: '+JSON.stringify(extra));
  ok(!JSON.stringify(r).includes('進行中')||extra.workflow_state==='進行中','no derived 進行中 label: '+JSON.stringify(extra));
 }
 eq(one({workflow_state:'Active '}).workflowLabel,'Active','workflow_state shown as supplied (trimmed only)');
 eq(one({queue:'active'}).workflowLabel,'unknown','queue is not turned into workflow text');
 const u=one({pending_reason:'unknown'});eq([u.pendingReason,u.statusLabel],['unknown','unknown'],'pending_reason unknown stays unknown');
 eq(ids(view([row('z',{pending_reason:'unknown'}),row('a')])),['a','z'],'unknown pending reason keeps ordinary rank (id order)');
 eq(ids(view([row('a'),row('z',{pending_reason:'等待客戶'})])),['z','a'],'known pending reason ranks first');
 eq(one({pending_reason:'等待客戶'}).statusLabel,MY_WORK_LABELS.pending,'known pending reason is pending');
 eq(buildMyWorkView({rows:[{...bare,queue:'awaiting_my_confirmation'}],readState:'ready',assignment:'assigned',canSeeAwaitingConfirmation:true,filters:{mode:'awaiting_my_confirmation'}}).rows[0].statusLabel,MY_WORK_LABELS.pending,'awaiting flag is pending');
 eq(one({attention:true,workflow_state:'active'}).statusLabel,MY_WORK_LABELS.attention,'attention flag unchanged');
});
test('7. F1: absent evidence is unknown, only an explicit empty list is none; F2: data as-of',()=>{
 const sel=extra=>view([row('a',extra)],{filters:{selectedId:'a'}}).drawer.task;
 eq(sel({}).evidence,null,'evidence field absent is unknown, not an empty list');
 eq(sel({evidence:'x'}).evidence,null,'malformed evidence is unknown');
 eq(sel({evidence:[]}).evidence,[],'explicit empty list is the only none');
 eq(sel({evidence:[{id:'d',title:'T'}]}).evidence,[{id:'d',title:'T'}],'supplied evidence listed');
 eq(view([row('a')]).rows[0].evidencePresent,false,'absent evidence is not present');
 eq(view([row('a')],{asOf:'2026-10-14'}).dataAsOfLabel,'資料日期 2026-10-14','as_of shown');
 eq(view([row('a')]).dataAsOfLabel,'資料日期 '+MY_WORK_LABELS.unknown,'missing as_of is unknown');
 eq(view([row('a')],{asOf:42}).dataAsOfLabel,'資料日期 '+MY_WORK_LABELS.unknown,'malformed as_of is unknown');
});
let failed=0;
for(const [name,fn] of tests){try{await fn();console.log(`ok - ${name}`)}catch(e){failed++;console.log(`not ok - ${name}\n${e.message}`)}}
if(failed){console.log(`${failed} failed`);process.exit(1)}
console.log(`my-work view: ${tests.length} tests, ${checks} checks passed`);
