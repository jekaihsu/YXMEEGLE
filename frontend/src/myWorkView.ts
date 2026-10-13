// My Work view-model (VCC-126). Pure and framework-free: no React, fetch or routing.
// Input is parsed defensively because /api/my-work does not exist yet; a missing or
// malformed field reads as unknown and is never replaced by an invented value.
import {dataStateCount,describeDataState,parseDataState} from './dataState.ts';
import type {DataState,DataStateName} from './dataState.ts';

export const MY_WORK_MODES=['todo','awaiting_my_confirmation'] as const;
export type MyWorkMode=typeof MY_WORK_MODES[number];
export const ACTION_KINDS=['task','case','work_item','document','delivery','confirmation'] as const;
export type ActionKind=typeof ACTION_KINDS[number];
export type OperationOutcome='none'|'succeeded'|'failed'|'unknown';

export const MY_WORK_LABELS={
 unknown:'unknown',
 attention:'需注意',
 pending:'待處理',
 normal:'進行中',
 awaiting:'等待我確認（尚未核准）',
 handoffNone:'無交接／確認',
 handoffPending:'交接待確認（尚未核准）',
 outcomeUnknown:'操作結果未知，請先確認結果，不可重新提交',
 modes:{todo:'待辦',awaiting_my_confirmation:'等待我確認'} as Record<MyWorkMode,string>,
 actions:{task:'開啟任務',case:'開啟案件',work_item:'開啟工作項',document:'開啟文件',delivery:'前往交付流程',confirmation:'前往確認流程'} as Record<ActionKind,string>,
 empty:{unassigned:'尚未被指派工作',no_pending:'目前沒有待辦工作'},
} as const;

// ---- local input row type (not a backend contract) -------------------------
export type MyWorkEntryPoint={kind:string;exists?:boolean;authorized?:boolean;route?:string};
export type MyWorkInputRow={
 id?:string;title?:string;
 case_title?:string;work_item_title?:string;
 parent?:{verified?:boolean;case_title?:string;work_item_title?:string};
 assignee_name?:string;
 workflow_state?:string;
 next_deliverable?:string;
 effective_due?:{value?:string;verified_formal?:boolean};
 pending_reason?:string;
 handoff_state?:string;
 queue?:string;
 attention?:boolean;
 ended?:boolean;
 forbidden?:boolean;
 required_input?:string;required_output?:string;
 evidence?:{id?:string;title?:string}[];
 operation_outcome?:string;
 entry_points?:MyWorkEntryPoint[];
};

export type MyWorkAction={kind:ActionKind;label:string;route:string};
export type MyWorkRow={
 id:string;title:string;caseTitle:string;workItemTitle:string;assignee:string;
 workflowLabel:string;statusLabel:string;nextDeliverable:string;
 dueLabel:string;pendingReason:string;handoffLabel:string;
 awaitingMyConfirmation:boolean;needsAttention:boolean;finishedKnown:boolean;
 evidencePresent:boolean;outcomeNote:string|null;actions:MyWorkAction[];
};
export type MyWorkDetail=MyWorkRow&{
 requiredInput:string;requiredOutput:string;evidence:{id:string;title:string}[];
 parent:{verified:boolean;caseTitle:string;workItemTitle:string};
};

export type MyWorkFilters={search:string;mode:MyWorkMode;selectedId:string|null};
export type WeeklyPeriod={start:string|null;end:string|null};
export type MyWorkInput={
 rows?:unknown;
 // 'ready' = clean successful read; otherwise a C-STATE value; undefined = not loaded yet.
 readState?:unknown;
 assignment?:'assigned'|'unassigned'|'unknown';
 canSeeAwaitingConfirmation?:boolean;
 filters?:Partial<{search:unknown;mode:unknown;selectedId:unknown}>;
 weeklyActivity?:{period?:unknown;items?:unknown};
};
export type MyWorkView={
 mode:MyWorkMode;
 modes:{mode:MyWorkMode;label:string}[];
 showModeToggle:boolean;
 // null = clean complete read with rows; every other page state is a C-STATE value.
 pageState:DataState|null;
 pageStateLabel:string|null;
 count:number|null;
 emptyReason:'unassigned'|'no_pending'|null;
 rows:MyWorkRow[];
 drawer:{open:boolean;task:MyWorkDetail|null};
 filters:MyWorkFilters;
 selectionDropped:boolean;
 weekly:{period:WeeklyPeriod;items:{id:string;title:string;date:string}[]};
};

// ---- defensive parsing -----------------------------------------------------
const rec=(v:unknown):Record<string,unknown>|null=>v&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:null;
const str=(v:unknown):string=>typeof v==='string'?v.trim():'';
const text=(v:unknown):string=>str(v)||MY_WORK_LABELS.unknown;
const isMode=(v:unknown):v is MyWorkMode=>typeof v==='string'&&(MY_WORK_MODES as readonly string[]).includes(v);
const isKind=(v:unknown):v is ActionKind=>typeof v==='string'&&(ACTION_KINDS as readonly string[]).includes(v);
// Navigation only: same-origin absolute paths, never a scheme or protocol-relative URL.
const safeRoute=(v:unknown):string|null=>{const s=str(v);return s.startsWith('/')&&!s.startsWith('//')&&!/[\\\s]/.test(s)?s:null};

function parseOutcome(v:unknown):OperationOutcome{
 if(v===undefined||v===null||v==='none')return 'none';
 return v==='succeeded'||v==='failed'?v:'unknown';
}

function parseActions(raw:unknown,outcome:OperationOutcome):MyWorkAction[]{
 if(!Array.isArray(raw))return [];
 const seen=new Set<string>();const out:MyWorkAction[]=[];
 for(const entry of raw){
  const e=rec(entry);if(!e)continue;
  const route=safeRoute(e.route);
  // Both flags must be literally true: an unverified entry point is not offered.
  if(!isKind(e.kind)||e.exists!==true||e.authorized!==true||!route)continue;
  // An unknown outcome must not invite another submission.
  if(outcome==='unknown'&&(e.kind==='delivery'||e.kind==='confirmation'))continue;
  if(seen.has(e.kind))continue;seen.add(e.kind);
  out.push({kind:e.kind,label:MY_WORK_LABELS.actions[e.kind],route});
 }
 return out;
}

type Parsed={row:MyWorkRow;detail:MyWorkDetail}|'forbidden'|'malformed';

function parseRow(raw:unknown):Parsed{
 const r=rec(raw);if(!r)return 'malformed';
 if(r.forbidden===true)return 'forbidden';
 const id=str(r.id);if(!id)return 'malformed';
 const awaiting=r.queue==='awaiting_my_confirmation';
 const attention=r.attention===true;
 const finishedKnown=typeof r.ended==='boolean';
 const pendingReason=str(r.pending_reason);
 const due=rec(r.effective_due);
 // Only a verified formal field is a due date; every other date stays unknown.
 const dueLabel=due&&due.verified_formal===true&&str(due.value)?str(due.value):MY_WORK_LABELS.unknown;
 const outcome=parseOutcome(r.operation_outcome);
 const handoffText=str(r.handoff_state);
 const handoffLabel=awaiting?MY_WORK_LABELS.awaiting:handoffText||MY_WORK_LABELS.handoffNone;
 const parent=rec(r.parent);
 const verified=!!parent&&parent.verified===true;
 const parentCase=verified?text(parent?.case_title):MY_WORK_LABELS.unknown;
 const parentItem=verified?text(parent?.work_item_title):MY_WORK_LABELS.unknown;
 // Evidence presence is shown as a fact only; it never feeds any completion state.
 const evidence=(Array.isArray(r.evidence)?r.evidence:[]).map(rec).filter((e):e is Record<string,unknown>=>!!e&&!!str(e.id)).map(e=>({id:str(e.id),title:text(e.title)}));
 const row:MyWorkRow={
  id,title:text(r.title),caseTitle:text(r.case_title),workItemTitle:text(r.work_item_title),assignee:text(r.assignee_name),
  workflowLabel:text(r.workflow_state),
  statusLabel:attention?MY_WORK_LABELS.attention:awaiting||pendingReason?MY_WORK_LABELS.pending:MY_WORK_LABELS.normal,
  nextDeliverable:text(r.next_deliverable),dueLabel,pendingReason:pendingReason||MY_WORK_LABELS.unknown,handoffLabel,
  awaitingMyConfirmation:awaiting,needsAttention:attention,finishedKnown,evidencePresent:evidence.length>0,
  outcomeNote:outcome==='unknown'?MY_WORK_LABELS.outcomeUnknown:null,
  actions:parseActions(r.entry_points,outcome),
 };
 const detail:MyWorkDetail={...row,requiredInput:text(r.required_input),requiredOutput:text(r.required_output),evidence,parent:{verified,caseTitle:parentCase,workItemTitle:parentItem}};
 // ended===true is the only thing that removes a task from the unfinished table.
 return r.ended===true?'malformed':{row,detail};
}

// attention first, then pending/awaiting, then the rest; ties by task id. Retrieval time is never a key.
const rank=(r:MyWorkRow)=>r.needsAttention?0:r.awaitingMyConfirmation||r.pendingReason!==MY_WORK_LABELS.unknown?1:2;
const byId=(a:string,b:string)=>a<b?-1:a>b?1:0;
export const compareMyWorkRows=(a:MyWorkRow,b:MyWorkRow)=>rank(a)-rank(b)||byId(a.id,b.id);

// ---- return context (filters + selection survive navigation) ---------------
export const DEFAULT_FILTERS:MyWorkFilters={search:'',mode:'todo',selectedId:null};
export const encodeReturnContext=(f:Partial<MyWorkFilters>):string=>JSON.stringify({v:1,search:str(f.search),mode:isMode(f.mode)?f.mode:'todo',selectedId:str(f.selectedId)||null});
export function decodeReturnContext(encoded:unknown):MyWorkFilters{
 if(typeof encoded!=='string')return {...DEFAULT_FILTERS};
 let parsed:unknown;try{parsed=JSON.parse(encoded)}catch{return {...DEFAULT_FILTERS}}
 const p=rec(parsed);if(!p||p.v!==1)return {...DEFAULT_FILTERS};
 return {search:str(p.search),mode:isMode(p.mode)?p.mode:'todo',selectedId:str(p.selectedId)||null};
}

const day=(v:string)=>v.slice(0,10);
function parseWeekly(raw:MyWorkInput['weeklyActivity']){
 const w=rec(raw);const p=rec(w?.period);
 const period:WeeklyPeriod={start:str(p?.start)||null,end:str(p?.end)||null};
 const items=(Array.isArray(w?.items)?w.items:[]).map(rec).filter((e):e is Record<string,unknown>=>!!e&&!!str(e.id)).map(e=>({id:str(e.id),title:text(e.title),date:str(e.date)}))
  .filter(e=>(!period.start||day(e.date)>=day(period.start))&&(!period.end||day(e.date)<=day(period.end)));
 return {period,items};
}

const BLOCKING:ReadonlySet<DataStateName>=new Set(['loading','unlocated','forbidden','read_failed','unknown']);

export function buildMyWorkView(input:MyWorkInput):MyWorkView{
 const canAwait=input.canSeeAwaitingConfirmation===true;
 const f=input.filters??{};
 const requested:MyWorkMode=isMode(f.mode)?f.mode:'todo';
 const mode:MyWorkMode=canAwait?requested:'todo';
 const search=str(f.search);
 const wanted=str(f.selectedId)||null;
 const weekly=parseWeekly(input.weeklyActivity);
 const base:Omit<MyWorkView,'pageState'|'pageStateLabel'|'count'|'emptyReason'|'rows'|'drawer'|'filters'|'selectionDropped'>={
  mode,modes:(canAwait?MY_WORK_MODES:['todo' as MyWorkMode]).map(m=>({mode:m,label:MY_WORK_LABELS.modes[m]})),showModeToggle:canAwait,weekly,
 };
 const finish=(pageState:DataState|null,rows:MyWorkRow[],emptyReason:MyWorkView['emptyReason'],selectedId:string|null,details:Map<string,MyWorkDetail>):MyWorkView=>{
  const task=selectedId?details.get(selectedId)??null:null;
  const kept=task?selectedId:null;
  const parsedState=pageState&&parseDataState(pageState);
  return {...base,pageState:parsedState,pageStateLabel:parsedState?describeDataState(parsedState):null,count:parsedState?dataStateCount(parsedState):rows.length,emptyReason,rows,
   drawer:{open:!!task,task},filters:{search,mode,selectedId:kept},selectionDropped:!!wanted&&!task,weekly};
 };
 const read=input.readState;
 const readState:DataState|'ready'=read===undefined?{states:['loading'],count:null}:read==='ready'?'ready':parseDataState(read);
 // Forbidden/loading/failed/unlocated/unknown show no rows, no count and keep no selection.
 if(readState!=='ready'&&readState.states.some(s=>BLOCKING.has(s))){
  return finish(readState,[],null,null,new Map());
 }
 const flags=new Set<DataStateName>(readState==='ready'?[]:readState.states);
 // Blocking states returned above, so only partial/stale remain in `flags`.
 if(!Array.isArray(input.rows)){
  return finish({states:['unknown'],count:null},[],null,null,new Map());
 }
 const details=new Map<string,MyWorkDetail>();
 for(const raw of input.rows){
  const p=parseRow(raw);
  if(p==='forbidden')continue;
  if(p==='malformed'){ if(!(rec(raw)?.ended===true))flags.add('partial'); continue; }
  if(details.has(p.row.id)){flags.add('partial');continue}
  if(!p.row.finishedKnown)flags.add('partial');
  details.set(p.row.id,p.detail);
 }
 // The default set is every unfinished assigned task; the weekly period never touches it.
 const inMode=[...details.values()].filter(d=>d.awaitingMyConfirmation===(mode==='awaiting_my_confirmation'));
 const needle=search.toLowerCase();
 const rows:MyWorkRow[]=inMode.filter(d=>!needle||[d.id,d.title,d.caseTitle,d.workItemTitle].some(s=>s.toLowerCase().includes(needle))).sort(compareMyWorkRows);
 const visible=new Map(rows.map(r=>[r.id,details.get(r.id) as MyWorkDetail]));
 const sel=wanted&&visible.has(wanted)?wanted:null;
 const partial=flags.has('partial'),stale=flags.has('stale');
 const flagStates:('partial'|'stale')[]=[...(partial?['partial' as const]:[]),...(stale?['stale' as const]:[])];
 if(rows.length===0){
  // Partial emptiness is not a verified "nothing pending".
  if(partial)return finish({states:flagStates,count:null},rows,null,sel,visible);
  const filtered=!!needle&&inMode.length>0;
  if(!filtered&&input.assignment!=='assigned'&&input.assignment!=='unassigned')return finish({states:['unknown'],count:null},rows,null,sel,visible);
  // C-STATE allows stale only with partial, so a stale snapshot with no rows reads as stale with a known zero.
  const state:DataState=stale?{states:['stale'],count:0}:{states:[filtered?'filtered_empty':'complete_empty'],count:0};
  return finish(state,rows,filtered?null:input.assignment==='unassigned'?'unassigned':'no_pending',sel,visible);
 }
 // A clean read with rows has no page-level state to show; partial/stale carry their own.
 return finish(flagStates.length?{states:flagStates,count:partial?null:rows.length}:null,rows,null,sel,visible);
}
