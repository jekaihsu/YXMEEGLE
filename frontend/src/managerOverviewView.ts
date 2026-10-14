// Manager Overview view-model (VCC-128). Pure and framework-free: no React, fetch or routing; unwired.
// Input is the JSON body of backend/manager_overview.py build_manager_overview (reviewed at b480b4b), treated
// as untrusted. Each top-level section (snapshot, weekly_activity, source_health) is validated all-or-nothing:
// any malformed or contradictory field makes that whole section unknown with a reason, never a partial render.
// Nothing here widens authorization: only what the body carries is rendered, forbidden carries nothing.
import {DATA_STATE_LABELS,parseDataState} from './dataState.ts';
import type {DataState,DataStateName} from './dataState.ts';

export const OVERVIEW_LABELS={
 dash:'—',
 title:'主管總覽',
 asOf:'資料日期',
 unverifiedMapping:'對應未驗證',
 withheld:'未核准顯示',
 invalidBody:'回應格式無效，已停止顯示此區塊',
 unfinished:'本機執行中（未完成）',
 unfinishedUnknown:'是否未完成：未知',
 yes:'是',no:'否',
 units:{confirmation_version:'確認單版本',stable_case:'案件（穩定身分）'} as Record<string,string>,
 cards:{confirmation_versions:'確認單版本',stable_cases:'案件',pending_decisions:'待決策',overdue_cases:'逾期案件'} as Record<string,string>,
 unresolvedRow:'未歸屬案件的確認單版本',
 sections:{cases:'未完成案件',cards:'快照摘要',unresolved:'未歸屬資料',weekly:'本期活動',health:'來源健康'},
 filterKeys:{pm:'PM',execution_state:'執行狀態'} as Record<string,string>,
 filterNone:'目前篩選：無',
 filterMismatch:'此快照的篩選與目前選取不同，尚未套用',
 healthRows:{failure:'來源讀取',partial:'部分載入',unmatched:'未比對資料'},
 healthLink:'前往來源健康',
 openCase:'開啟案件',
 emptyCases:'尚無未完成案件',
 filteredEmptyCases:'沒有符合篩選條件的案件',
} as const;

// ---- local mirrors of P2-NAV (frontend/src/drilldownContext.ts @ a529080); not imported, for P2-INT to bind ----
export type OverviewSort={key:string;dir:'asc'|'desc'}|null;          // = SortSpec
export type OverviewPeriod={start:string;end:string}|null;             // = Period (weekly activity only)
export type OverviewFilterSet=Readonly<Record<string,string>>;         // = FilterSet; overview keys: pm, execution_state
export const OVERVIEW_SORT_KEYS=['label','responsible','unfinished'] as const;

export type ManagerOverviewInput={
 body?:unknown;                       // JSON returned by the read model
 filters?:OverviewFilterSet;          // UI filter state (accepted, never applied locally)
 sort?:OverviewSort;
 period?:OverviewPeriod;              // governs weekly activity only
 selectedId?:unknown;                 // selection-only drawer
};

export type FactCell={text:string;known:boolean;reason:string|null;stateLabel:string|null};
export type Drilldown={route:string;filters:Record<string,unknown>;group_by:string};
export type CaseRow={
 id:string;               // stable project_id: selection/navigation key, never a default column
 label:FactCell;unfinished:FactCell;actionable:FactCell;responsible:FactCell;currentStage:FactCell;
 effectiveDueDate:FactCell;blocker:FactCell;pendingDecision:FactCell;
 entry:{label:string;route:string}|null;
};
export type CaseDetail={
 id:string;rowKeys:string[];pmId:string|null;executionStatus:string|null;admission:Record<string,unknown>|null;
 mappingLabel:string;amounts:{text:string;reason:string};formula:string|null;
};
export type CardView={
 id:string;label:string;unitLabel:string;valueText:string;known:boolean;stateLabel:string;reason:string;asOfLabel:string;drilldown:Drilldown;
};
export type UnresolvedRowView={id:string;label:string;mappingLabel:string;rowKey:string};
export type SectionState={stateLabel:string;reason:string|null};
export type HealthRow={key:'failure'|'partial'|'unmatched';label:string;stateLabel:string;reason:string};
export type ManagerOverviewView={
 header:{title:string;asOfLabel:string;scope:{key:string;label:string;value:string}[];scopeLabel:string;filterMismatch:string|null};
 snapshot:{
  state:DataState;stateLabel:string;reason:string|null;
  cases:CaseRow[];casesEmptyLabel:string|null;
  cards:CardView[];bucketNote:string|null;
  unresolved:{countText:string;known:boolean;stateLabel:string;reason:string;rows:UnresolvedRowView[]};
 };
 weekly:{available:false;stateLabel:string;reason:string;period:OverviewPeriod};
 sourceHealth:{stateLabel:string;rows:HealthRow[];link:{label:string;route:'sources'}|null};
 sort:{key:string;dir:'asc'|'desc'}|null;sortDropped:boolean;
 drawer:{open:boolean;case:CaseDetail|null;unresolved:{rowKey:string;mappingLabel:string}|null};
 selectedId:string|null;selectionDropped:boolean;
};

// ---- defensive parsing -----------------------------------------------------
class Invalid extends Error{}
const bad=():never=>{throw new Invalid('invalid')};
const rec=(v:unknown):Record<string,unknown>|null=>v&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:null;
const need=(v:unknown):Record<string,unknown>=>rec(v)??bad();
const str=(v:unknown):string=>typeof v==='string'?v.trim():'';
const reqStr=(v:unknown):string=>str(v)||bad();
const optStr=(v:unknown):string|null=>v===null||v===undefined?null:typeof v==='string'&&v.trim()?v.trim():bad();
const isCount=(v:unknown):v is number=>typeof v==='number'&&Number.isInteger(v)&&v>=0;
// Navigation only: same-origin absolute paths, never a scheme or protocol-relative URL.
const safeRoute=(v:unknown):string=>{const s=str(v);return s.startsWith('/')&&!s.startsWith('//')&&!/[\\\s]/.test(s)?s:bad()};
const EMPTY:ReadonlySet<DataStateName>=new Set(['complete_empty','filtered_empty']);
const UNCOUNTED:ReadonlySet<DataStateName>=new Set(['loading','unlocated','read_failed','unknown']);
// Labels only: describeDataState would append a count, which the side panel must not show.
const labelOf=(s:DataState):string=>s.states.map(n=>DATA_STATE_LABELS[n]).join('・');
const stateOf=(v:unknown):DataState=>{
 // Strictness beyond parseDataState: a malformed envelope is invalid, not silently "unknown".
 const r=rec(v);if(!r||!Array.isArray(r.states))return bad();
 const p=parseDataState(v);
 if(p.states.length===1&&p.states[0]==='unknown'){
  // parseDataState collapses anything malformed to unknown; only a literal unknown (no count) is genuine.
  const isUnknownOnly=r.states.length===1&&r.states[0]==='unknown'&&(r.count===null||r.count===undefined);
  if(!isUnknownOnly)return bad();
 }
 return p;
};
// Backend case_cutover.admission_fields contract; any other property (e.g. an amount) is rejected.
const ADMISSION_KEYS:ReadonlySet<string>=new Set(['execution_system','execution_system_label','execution_readonly_reason','case_visibility']);
const cloneJson=(v:unknown):unknown=>{
 if(v===null||typeof v==='string'||typeof v==='boolean')return v;
 if(typeof v==='number'&&Number.isFinite(v))return v;
 if(Array.isArray(v))return v.map(cloneJson);
 const r=rec(v);if(!r)return bad();
 return Object.fromEntries(Object.entries(r).map(([k,x])=>[k,cloneJson(x)]));
};

// A count is displayed only if it is a non-negative integer, agrees with its state, and zero is backed by an
// explicit empty state. Everything else is an em dash: unknown is never 0.
function measure(value:unknown,state:DataState):{text:string;known:boolean}{
 if(value===null||value===undefined)return {text:OVERVIEW_LABELS.dash,known:false};
 if(!isCount(value))return bad();
 const first=state.states[0];
 if(state.states[0]==='forbidden'||UNCOUNTED.has(first))return bad();  // a number beside a no-count state is contradictory
 if(EMPTY.has(first)?value!==0:(value===0||('count' in state&&state.count!==null&&state.count!==value)))return bad();
 return {text:String(value),known:true};
}

function fact(raw:unknown,render:(v:unknown)=>string|null,force?:'unknown'):FactCell{
 const f=need(raw);
 const reason=reqStr(f.reason);
 const state=f.state===null||f.state===undefined?null:stateOf(f.state);
 const value=f.value;
 if(force==='unknown'||value===null||value===undefined){
  // Absent value: dash plus the supplied reason. A state, if given, labels why.
  return {text:OVERVIEW_LABELS.dash,known:false,reason,stateLabel:state?labelOf(state):null};
 }
 if(state&&state.states.some(s=>s==='forbidden'||UNCOUNTED.has(s)))return bad(); // value beside a no-value state
 const text=render(value);if(text===null)return bad();
 return {text,known:true,reason,stateLabel:state?labelOf(state):null};
}
const renderLabel=(v:unknown)=>typeof v==='string'&&v.trim()?v.trim():null;
const renderBool=(v:unknown)=>v===true?OVERVIEW_LABELS.yes:v===false?OVERVIEW_LABELS.no:null;

function parseCase(raw:unknown):{row:CaseRow;detail:CaseDetail}{
 const c=need(raw);
 const id=reqStr(c.project_id);
 const label=c.label===null||c.label===undefined?{text:OVERVIEW_LABELS.dash,known:false,reason:null,stateLabel:null}
  :{text:reqStr(c.label),known:true,reason:null,stateLabel:null};
 const unfinishedCell=fact(c.unfinished,renderBool);
 if(unfinishedCell.known&&unfinishedCell.text===OVERVIEW_LABELS.yes)unfinishedCell.text=OVERVIEW_LABELS.unfinished;
 else if(!unfinishedCell.known)unfinishedCell.text=OVERVIEW_LABELS.dash;
 const ep=need(c.entry_point);
 if(ep.kind!=='case'||ep.read_only!==true)bad();
 const d=need(c.details);
 const rowKeys=d.row_keys;
 if(!Array.isArray(rowKeys)||!rowKeys.every(k=>typeof k==='string'&&k))bad();
 // No receipt authority (plan D3): the only accepted mapping state is receipt_missing, shown as 對應未驗證.
 if(d.mapping_state!=='receipt_missing')bad();
 const am=need(d.amounts);
 // G-AMT: amounts are never rendered. A body carrying a value (or any non-withheld state) is rejected whole.
 if(am.value!==null||am.state!=='withheld')bad();
 const row:CaseRow={
  id,label,unfinished:unfinishedCell,
  actionable:fact(c.actionable,renderBool),
  responsible:fact(c.responsible,renderLabel),
  // Stage mapping has no receipt and due date has no verified formal field (VCC-117 D3, VCC-123): never rendered.
  currentStage:fact(c.current_stage,renderLabel,'unknown'),
  effectiveDueDate:fact(c.effective_due_date,renderLabel,'unknown'),
  blocker:fact(c.blocker,renderBool),
  pendingDecision:fact(c.pending_decision,renderBool),
  entry:{label:OVERVIEW_LABELS.openCase,route:safeRoute(ep.route)},
 };
 let admission:Record<string,unknown>|null=null;
 if(d.admission!==null&&d.admission!==undefined){
  const a=need(d.admission);admission={};
  for(const [k,x] of Object.entries(a)){
   if(!ADMISSION_KEYS.has(k))bad();
   if(x!==null&&typeof x!=='string')bad();
   admission[k]=x;
  }
 }
 const detail:CaseDetail={
  id,rowKeys:rowKeys as string[],pmId:optStr(d.pm_id),executionStatus:optStr(d.execution_status),admission,
  mappingLabel:OVERVIEW_LABELS.unverifiedMapping,
  amounts:{text:OVERVIEW_LABELS.withheld,reason:reqStr(am.reason)},
  formula:optStr(d.formula),
 };
 return {row,detail};
}

function parseCard(raw:unknown):CardView{
 const c=need(raw);
 const id=reqStr(c.id);
 const label=OVERVIEW_LABELS.cards[id]??bad();     // own copy; the body's label text is not trusted
 const unit=reqStr(c.unit);
 const unitLabel=OVERVIEW_LABELS.units[unit]??bad();
 const state=stateOf(c.state);
 const m=measure(c.value,state);
 const dd=need(c.drilldown);
 // Drilldown descriptors are passed through unchanged (deep copy), only shape-checked.
 const drilldown:Drilldown={route:reqStr(dd.route),filters:need(cloneJson(need(dd.filters))),group_by:reqStr(dd.group_by)};
 const asOf=optStr(c.as_of);
 return {id,label,unitLabel,valueText:m.text,known:m.known,stateLabel:labelOf(state),reason:reqStr(c.reason),
  asOfLabel:`${OVERVIEW_LABELS.asOf} ${asOf??OVERVIEW_LABELS.dash}`,drilldown};
}

function parseSnapshot(raw:unknown){
 const s=need(raw);
 const state=stateOf(s.state);
 if(state.states[0]==='forbidden'){
  // Forbidden exposes no case, label, card or count, even if the body carries some.
  return {state,filters:{} as Record<string,string>,cases:[] as CaseRow[],details:new Map<string,CaseDetail>(),cards:[] as CardView[],bucketNote:null,
   unresolved:{countText:OVERVIEW_LABELS.dash,known:false,stateLabel:labelOf(state),reason:DATA_STATE_LABELS.forbidden,rows:[] as UnresolvedRowView[]}};
 }
 const filtersRaw=need(cloneJson(need(s.filters)));
 const filters:Record<string,string>={};
 for(const [k,v] of Object.entries(filtersRaw)){if(typeof v!=='string')bad();filters[k]=v as string}
 if(!Array.isArray(s.cases)||!Array.isArray(s.cards))bad();
 const details=new Map<string,CaseDetail>();const cases:CaseRow[]=[];
 for(const x of s.cases as unknown[]){
  const p=parseCase(x);
  if(details.has(p.row.id))bad();                 // one row per stable case; duplicates are contradictory
  details.set(p.row.id,p.detail);cases.push(p.row);
 }
 const cards=(s.cards as unknown[]).map(parseCard);
 // A blocking read state (loading, failed, unlocated, unknown) establishes no count; no card may carry one.
 if(UNCOUNTED.has(state.states[0])&&(cards.some(c=>c.known)))bad();
 if(new Set(cards.map(c=>c.id)).size!==cards.length)bad();
 const u=need(s.unresolved);
 const ustate=stateOf(u.state);
 const um=measure(u.value,ustate);
 if(!Array.isArray(u.rows))bad();
 const rows:UnresolvedRowView[]=(u.rows as unknown[]).map(r=>{
  const d=need(need(r).details);
  if(d.mapping_state!=='receipt_missing')bad();
  const rowKey=reqStr(d.row_key);
  return {id:`unresolved:${rowKey}`,label:OVERVIEW_LABELS.unresolvedRow,mappingLabel:OVERVIEW_LABELS.unverifiedMapping,rowKey};
 });
 if(new Set(rows.map(r=>r.id)).size!==rows.length)bad();
 // The unresolved count is its own measure; it must agree with the supplied rows when known.
 if(um.known&&Number(um.text)!==rows.length)bad();
 if(UNCOUNTED.has(state.states[0])&&um.known)bad();
 // An explicit empty population cannot coexist with case or unresolved rows.
 if(EMPTY.has(state.states[0])&&(cases.length||rows.length))bad();
 if(EMPTY.has(ustate.states[0])&&rows.length)bad();
 // The cards measure the same population: an empty snapshot cannot carry a positive count (zero and dash cards are fine).
 if(EMPTY.has(state.states[0])&&cards.some(c=>c.known&&c.valueText!=='0'))bad();
 return {state,filters,cases,details,cards,
  bucketNote:optStr(s.bucket_policy),
  unresolved:{countText:um.text,known:um.known,stateLabel:labelOf(ustate),reason:reqStr(u.reason),rows}};
}

function parseWeekly(raw:unknown){
 const w=need(raw);
 const state=stateOf(w.state);
 // No weekly event source exists: a value or rows would be an unsupported shape, so fail closed.
 if(w.value!==null&&w.value!==undefined)bad();
 if(w.rows!==null&&w.rows!==undefined)bad();
 return {stateLabel:labelOf(state),reason:reqStr(w.reason)};
}

function parseHealth(raw:unknown){
 const h=need(raw);
 if(h.route!=='sources')bad();
 const page=stateOf(h.state);
 const part=(key:'failure'|'partial'|'unmatched'):HealthRow=>{
  const p=need(h[key]);
  // State labels only; any count, name or source list the body might add is never read.
  return {key,label:OVERVIEW_LABELS.healthRows[key],stateLabel:labelOf(stateOf(p.state)),reason:reqStr(p.reason)};
 };
 const forbidden=page.states[0]==='forbidden';
 return {stateLabel:labelOf(page),rows:forbidden?[]:[part('failure'),part('partial'),part('unmatched')],
  link:forbidden?null:{label:OVERVIEW_LABELS.healthLink,route:'sources' as const}};
}

const unknownSection=()=>({stateLabel:DATA_STATE_LABELS.unknown,reason:OVERVIEW_LABELS.invalidBody});
const unknownState=():DataState=>({states:['unknown'],count:null});

function cellKey(c:FactCell){return c.known?c.text:''}
const sortKeyOf=(r:CaseRow,k:string)=>k==='label'?cellKey(r.label):k==='responsible'?cellKey(r.responsible):cellKey(r.unfinished);

export function buildManagerOverviewView(input:ManagerOverviewInput):ManagerOverviewView{
 const body=rec(input.body);
 const wanted=str(input.selectedId)||null;
 const reqFilters:Record<string,string>={};
 for(const [k,v] of Object.entries(input.filters??{}))if(typeof v==='string'&&v)reqFilters[k]=v;
 const period:OverviewPeriod=input.period&&str(input.period.start)&&str(input.period.end)?{start:str(input.period.start),end:str(input.period.end)}:null;
 const sortIn=input.sort;
 const sort=sortIn&&(OVERVIEW_SORT_KEYS as readonly string[]).includes(sortIn.key)&&(sortIn.dir==='asc'||sortIn.dir==='desc')?{key:sortIn.key,dir:sortIn.dir}:null;
 const sortDropped=!!sortIn&&!sort;

 const attempt=<T,>(raw:unknown,fn:(r:unknown)=>T):T|null=>{try{return fn(raw)}catch(e){if(e instanceof Invalid)return null;throw e}};
 const snap=body?attempt(body.snapshot,parseSnapshot):null;
 // A forbidden snapshot withholds the weekly dataset as well; weekly never filters cases either way.
 const weeklyParsed=body?attempt(body.weekly_activity,parseWeekly):null;
 const weeklySection=weeklyParsed??unknownSection();
 const healthParsed=body?attempt(body.source_health,parseHealth):null;
 const asOfRaw=body?body.as_of:undefined;
 const asOf=typeof asOfRaw==='string'&&asOfRaw.trim()?asOfRaw.trim():null;

 const forbidden=!!snap&&snap.state.states[0]==='forbidden';
 const state=snap?snap.state:unknownState();
 const scope=snap?Object.entries(snap.filters).map(([key,value])=>({key,label:OVERVIEW_LABELS.filterKeys[key]??key,value})):[];
 const mismatch=!!snap&&!forbidden&&JSON.stringify(Object.entries(reqFilters).sort())!==JSON.stringify(Object.entries(snap.filters).sort());

 let cases=snap?[...snap.cases]:[];
 if(sort){
  const sgn=sort.dir==='asc'?1:-1;
  // Stable sort; unknown cells sort last in either direction.
  cases=cases.map((r,i)=>({r,i})).sort((a,b)=>{
   const ka=sortKeyOf(a.r,sort.key),kb=sortKeyOf(b.r,sort.key);
   if(!ka!==!kb)return ka?-1:1;
   return (ka<kb?-sgn:ka>kb?sgn:0)||a.i-b.i;
  }).map(x=>x.r);
 }
 const first=state.states[0];
 const casesEmptyLabel=snap&&!cases.length?(first==='complete_empty'?OVERVIEW_LABELS.emptyCases:first==='filtered_empty'?OVERVIEW_LABELS.filteredEmptyCases:null):null;

 const detail=snap&&wanted?snap.details.get(wanted)??null:null;
 const unresolvedSel=snap&&wanted?snap.unresolved.rows.find(r=>r.id===wanted)??null:null;
 const kept=detail||unresolvedSel?wanted:null;

 const unresolved=snap?snap.unresolved:{countText:OVERVIEW_LABELS.dash,known:false,stateLabel:DATA_STATE_LABELS.unknown,reason:OVERVIEW_LABELS.invalidBody,rows:[]};
 return {
  header:{title:OVERVIEW_LABELS.title,asOfLabel:`${OVERVIEW_LABELS.asOf} ${asOf??OVERVIEW_LABELS.dash}`,scope,
   scopeLabel:scope.length?scope.map(s=>`${s.label}：${s.value}`).join('、'):OVERVIEW_LABELS.filterNone,
   filterMismatch:mismatch?OVERVIEW_LABELS.filterMismatch:null},
  snapshot:{state,stateLabel:labelOf(state),reason:snap?null:OVERVIEW_LABELS.invalidBody,
   cases,casesEmptyLabel,cards:snap?snap.cards:[],bucketNote:snap?snap.bucketNote:null,unresolved},
  weekly:{available:false,...weeklySection,period:forbidden?null:period},
  sourceHealth:healthParsed?{stateLabel:healthParsed.stateLabel,rows:healthParsed.rows,link:healthParsed.link}
   :{stateLabel:DATA_STATE_LABELS.unknown,rows:[],link:null},
  sort,sortDropped,
  drawer:{open:!!kept,case:detail,unresolved:unresolvedSel?{rowKey:unresolvedSel.rowKey,mappingLabel:unresolvedSel.mappingLabel}:null},
  selectedId:kept,selectionDropped:!!wanted&&!kept,
 };
}
