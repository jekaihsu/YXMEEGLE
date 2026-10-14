// Work Item Detail view-model (VCC-132). Pure and framework-free: no React, fetch or routing.
// Input is the JSON body of backend build_work_item_detail (reviewed e0015ba, p2-132b
// backend/work_item_detail.py). The body is untrusted: any section that is not exactly the
// reviewed shape fails closed to unknown, and no value is partially trusted. The caller has
// already narrowed the workspace (identity -> require_access -> filter_visible_cases ->
// allowlists -> case_redaction); this module only renders what is present, never counts,
// names or hints at anything absent, and never re-widens.
import {DATA_STATE_LABELS,parseDataState} from './dataState.ts';
import type {DataState,DataStateName} from './dataState.ts';

export const WORK_ITEM_TABS=['work_content','work_orders','nodes','deliverables','history'] as const;
export type WorkItemTab=typeof WORK_ITEM_TABS[number];

export const WORK_ITEM_LABELS={
 unknown:'—',
 receiptMissing:'對應未驗證',
 evidenceOnly:'僅作證據，不代表完成',
 withheld:'未核准顯示',
 withheldReason:'G-AMT：金額顯示尚未核准',
 reasonUnspecified:'原因未說明',
 tabs:{work_content:'工作內容',work_orders:'工單',nodes:'工作流程節點／SOP',deliverables:'交付物',history:'歷程'} as Record<WorkItemTab,string>,
 crumb:{confirmation:'確認單',contractLine:'合約項目',workItem:'工作項'},
 confirmationUnresolved:'確認單：未定位',
 sourceHealth:'前往來源健康',
 dailyReports:'案件日報',
 dailyReportsNote:'日報與工作項的對應尚未驗證，僅提供連結',
 dailyReportsLink:'開啟案件日報',
 operationUnknown:'操作結果未知，請先確認結果，不可重新提交',
 round:(n:number)=>`第 ${n} 輪`,
 roundBefore:(n:number)=>`開啟第 ${n} 輪前的狀態`,
 scope:{node:'節點',work_item:'工作項'} as Record<string,string>,
} as const;

// Known backend reason codes -> display copy. Unknown reason strings are never echoed.
const REASONS:Record<string,string>={
 work_item_name_unlocated:'工作項名稱找不到來源',
 no_work_item_execution_state:'沒有工作項執行狀態',
 quantity_field_unlocated:'數量欄位找不到來源',
 unit_field_unlocated:'單位欄位找不到來源',
 requested_date_field_unlocated:'申請日期欄位找不到來源',
 estimated_date_field_unlocated:'預估日期欄位找不到來源',
 source_updated_time_unlocated:'來源更新時間找不到來源',
 'VCC-123 formal deadline provenance unresolved':'VCC-123：正式期限來源尚未確認',
 'Calculation contract not approved; same item, unit and period required':'計算規則尚未核准；須同一項目、單位與期間才能比較',
 'G-RCODE: R01/R02/R09/R10 work-order models unverified':'G-RCODE：R01/R02/R09/R10 工單模型尚未驗證',
 'G-AMT approval absent':'G-AMT：金額顯示尚未核准',
 native_parent_edge_absent:'找不到原生上層關聯',
 native_confirmation_edge_unresolved:'找不到原生確認單關聯',
 visible_work_item_source_missing:'工作項來源遺失',
 section_read_failed:'此區段讀取失敗',
 evidence_is_not_workflow_completion:'證據不等於流程完成',
 'work-item daily-report edge unverified':'工作項與日報的關聯尚未驗證',
 malformed_body:'回應格式不符，無法採信',
 malformed_section:'區段格式不符，無法採信',
 duplicate_instance_identity:'節點實例識別重複，無法採信',
};
const reasonText=(v:unknown):string=>typeof v==='string'&&Object.hasOwn(REASONS,v)?REASONS[v]:WORK_ITEM_LABELS.reasonUnspecified;

// ---- local mirror of route/UI context (P2-NAV drilldownContext.ts @ a529080; not imported) --
// P2-INT maps the route context onto this: tab, selected row key, sort direction, history expansion.
export type WorkItemUi={tab?:unknown;selectedKey?:unknown;sortDir?:unknown;historyExpanded?:unknown};
export type WorkItemInput={body:unknown;ui?:WorkItemUi};

export type Cell={state:'known'|'unknown'|'withheld';text:string;reason?:string};
export type SectionState={states:DataStateName[]|['forbidden'];label:string};
export type Link={label:string;target:{view:'sources'}|{view:'project';projectId:string;tab:'daily'}};
export type DrawerField={label:string;value:string};
export type DrawerModel={kind:'work_item'|'parent'|'node'|'deliverable';key:string;fields:DrawerField[]};

export type BreadcrumbPath={confirmations:{text:string;verification:string}[];confirmationUnresolved:boolean;contractLine:string;workItem:string;verification:string};
export type NodeRow={key:string;nodeName:Cell;taskTitle:Cell;status:Cell;completedAt:Cell;input:Cell;output:Cell;required:Cell;
 responsible:Cell;round:Cell;verification:string;operationNote:string|null;reworkRounds:{label:string;status:Cell;output:Cell;completedAt:Cell}[]};
export type DeliverableRow={key:string;name:Cell;date:Cell;direction:Cell;version:Cell;scope:string;evidenceOnly:true;note:string};
export type Section<R>={state:SectionState;rows:R[];emptyRow:string|null;reason:string|null};

export type WorkItemView={
 pageState:DataState;pageStateLabel:string;
 // false when only the page state may render (unknown, forbidden, failed, ...).
 hasContent:boolean;unknownReason:string|null;
 asOfLabel:string;
 header:{name:Cell;category:Cell;sourceIdentity:string;executionState:Cell}|null;
 breadcrumbs:BreadcrumbPath[];
 tabs:{key:WorkItemTab;label:string;active:boolean}[];activeTab:WorkItemTab;
 workContent:{state:SectionState;quantity:Cell;unit:Cell;amounts:Cell};
 planActual:{state:SectionState;available:false;label:string;reason:string};
 workOrders:{state:SectionState;verification:string;rows:[];emptyRow:string;reason:string;sourceHealthLink:Link|null};
 parents:Section<{key:string;title:Cell;itemNumber:Cell;verification:string;sourceMissing:boolean;
  confirmations:{text:string;verification:string}[];confirmationUnresolved:boolean}>;
 nodes:Section<NodeRow>;
 deliverables:Section<DeliverableRow>&{sortDir:'asc'|'desc'};
 history:{state:SectionState;rounds:{key:string;nodeName:Cell;label:string;status:Cell;output:Cell;completedAt:Cell}[];
  completedExpanded:boolean;completed:{key:string;nodeName:Cell;taskTitle:Cell;completedAt:Cell}[]|null};
 side:{responsible:string[];responsibleCell:Cell;operationScope:Cell;
  dates:{effectiveDue:Cell;pendingDue:Cell;estimatedDue:Cell;sourceUpdatedAt:Cell};warnings:string[]};
 // Link only: no state count, no rows (the edge is unverified).
 caseDailyReports:{label:string;note:string;link:Link|null};
 drawer:{open:boolean;model:DrawerModel|null};
 selectionDropped:boolean;
 ui:{tab:WorkItemTab;selectedKey:string|null;sortDir:'asc'|'desc';historyExpanded:boolean};
};

// ---- defensive parsing -----------------------------------------------------
type R=Record<string,unknown>;
const rec=(v:unknown):R|null=>v&&typeof v==='object'&&!Array.isArray(v)?v as R:null;
const str=(v:unknown):string=>typeof v==='string'?v.trim():'';
const unknownCell=(reason?:unknown):Cell=>({state:'unknown',text:WORK_ITEM_LABELS.unknown,reason:reasonText(reason)});
const textCell=(v:unknown,reason='malformed_section'):Cell=>str(v)?{state:'known',text:str(v)}:unknownCell(reason);
const isRound=(v:unknown):v is number=>typeof v==='number'&&Number.isInteger(v)&&v>=0;
const isKey=(v:unknown):v is string=>{const p=str(v).split('/');return typeof v==='string'&&p.length===3&&p.every(Boolean)};
const stateLabel=(s:DataState):string=>s.states.map(n=>DATA_STATE_LABELS[n]).join('・');
// Labels only: a body-supplied count is never shown.
const sectionState=(raw:unknown):SectionState=>{const s=parseDataState(raw);return {states:s.states as DataStateName[],label:stateLabel(s)}};
const isForbidden=(s:SectionState)=>s.states[0]==='forbidden';
const failed=(name:DataStateName,reason:string):Section<never>=>({state:sectionState({states:[name]}),rows:[],emptyRow:DATA_STATE_LABELS[name],reason:reasonText(reason)});
const sectionOf=<T,>(raw:unknown,parse:(rows:unknown[])=>T[]|null):Section<T>=>{
 const s=rec(raw);if(!s)return failed('unknown','malformed_section') as Section<T>;
 const state=sectionState(s.read_state);
 if(isForbidden(state))return {state,rows:[],emptyRow:null,reason:null};
 if(state.states[0]==='unknown')return {...failed('unknown','malformed_section'),state} as Section<T>;
 if(!Array.isArray(s.rows))return failed('unknown','malformed_section') as Section<T>;
 const rows=parse(s.rows);
 if(!rows)return failed('unknown','malformed_section') as Section<T>;
 // Rows present but the section says it cannot read them (failed/unlocated/unknown): trust the state, drop rows.
 if(rows.length&&['read_failed','unlocated','loading'].includes(state.states[0]))return {state,rows:[],emptyRow:state.label,reason:reasonText(s.reason)};
 return {state,rows,emptyRow:rows.length?null:state.label,reason:s.reason===undefined?null:reasonText(s.reason)};
};

const VERIFICATION=WORK_ITEM_LABELS.receiptMissing; // plan D3: no receipt authority, never upgraded from body strings

function parseConfirmations(raw:unknown):{text:string;verification:string}[]|null{
 if(raw===undefined)return [];
 if(!Array.isArray(raw))return null;
 const out=[];
 for(const c of raw){const r=rec(c);if(!r||!str(r.id))return null;out.push({text:str(r.code)||WORK_ITEM_LABELS.unknown,verification:VERIFICATION})}
 return out;
}

function parseParents(rows:unknown[]){
 const out=[];
 for(const raw of rows){
  const r=rec(raw);if(!r||!str(r.id))return null;
  const confirmations=parseConfirmations(r.confirmations);if(!confirmations)return null;
  out.push({key:`parent:${str(r.id)}`,title:textCell(r.title,'malformed_section'),itemNumber:textCell(r.item_number),verification:VERIFICATION,
   sourceMissing:r.source_missing===true,confirmations,confirmationUnresolved:!confirmations.length||rec(r.unresolved)!==null});
 }
 return out;
}

const NODE_TEXT=(v:unknown)=>typeof v==='string'||v===undefined||v===null;
function parseNodes(rows:unknown[]){
 const out:NodeRow[]=[];const seen=new Set<string>();
 for(const raw of rows){
  const r=rec(raw);const id=r&&rec(r.instance_identity);const node=r&&rec(r.node);const task=r&&rec(r.task);
  if(!r||!id||!node||!task||!str(id.project_id)||!str(id.node_id)||!str(id.task_id)||!str(node.id)||!str(task.id))return null;
  if(id.sop_round!==null&&id.sop_round!==undefined&&!isRound(id.sop_round))return null;
  if(!NODE_TEXT(node.name)||!NODE_TEXT(task.title)||!NODE_TEXT(task.status))return null;
  const key=`node:${str(id.project_id)}/${str(id.node_id)}/${str(id.task_id)}/${isRound(id.sop_round)?id.sop_round:'-'}`;
  if(seen.has(key))return null;seen.add(key);
  const history=r.history===undefined?[]:r.history;if(!Array.isArray(history))return null;
  const rounds=[];
  for(const h of history){
   const hr=rec(h);const before=hr&&rec(hr.before);
   if(!hr||!before||!isRound(hr.opened_round))return null;
   rounds.push({label:WORK_ITEM_LABELS.roundBefore(hr.opened_round),status:textCell(before.status),output:textCell(before.output),completedAt:textCell(before.completed_at)});
  }
  const owner=rec(r.responsible_person);
  const ops=Array.isArray(r.operations)?r.operations.map(rec):[];
  out.push({key,nodeName:textCell(node.name),taskTitle:textCell(task.title),status:textCell(task.status),completedAt:textCell(task.completed_at),
   input:textCell(task.input),output:textCell(task.output),
   required:typeof task.required==='boolean'?{state:'known',text:task.required?'必要':'非必要'}:unknownCell(),
   responsible:owner&&str(owner.name)?{state:'known',text:str(owner.name)}:unknownCell(),
   round:isRound(id.sop_round)?{state:'known',text:WORK_ITEM_LABELS.round(id.sop_round)}:unknownCell(),
   verification:VERIFICATION,operationNote:ops.some(o=>o&&o.status==='outcome_unknown')?WORK_ITEM_LABELS.operationUnknown:null,reworkRounds:rounds});
 }
 return out;
}

const time=(s:string)=>{const t=Date.parse(s);return Number.isNaN(t)?null:t};
const byId=(a:string,b:string)=>a<b?-1:a>b?1:0;
function parseDeliverables(rows:unknown[]){
 const out:DeliverableRow[]=[];const seen=new Set<string>();
 for(const raw of rows){
  const r=rec(raw);
  // Evidence must arrive explicitly evidence-only on a known attachment; anything else is untrusted.
  if(!r||!str(r.id)||r.evidence_only!==true||r.kind!=='attachment'||typeof r.relation_scope!=='string'||!(r.relation_scope in WORK_ITEM_LABELS.scope))return null;
  const key=`deliverable:${r.relation_scope}:${str(r.id)}`;if(seen.has(key))return null;seen.add(key);
  out.push({key,name:textCell(r.name),date:textCell(r.created_at),direction:textCell(r.direction),
   version:typeof r.version==='number'||str(r.version)?{state:'known',text:String(r.version).trim()}:unknownCell(),
   scope:WORK_ITEM_LABELS.scope[r.relation_scope],evidenceOnly:true,note:WORK_ITEM_LABELS.evidenceOnly});
 }
 return out;
}
// date descending (or ascending) then stable id; undated rows last in both directions.
function sortDeliverables(rows:DeliverableRow[],dir:'asc'|'desc'){
 const sign=dir==='desc'?-1:1;
 return [...rows].sort((a,b)=>{
  const ta=a.date.state==='known'?time(a.date.text):null,tb=b.date.state==='known'?time(b.date.text):null;
  if(ta===null||tb===null){if(ta!==tb)return ta===null?1:-1}else if(ta!==tb)return sign*(ta-tb);
  return byId(a.key,b.key);
 });
}

const sourceHealthLink=(raw:unknown):Link|null=>{const r=rec(raw);return r&&r.view==='sources'?{label:WORK_ITEM_LABELS.sourceHealth,target:{view:'sources'}}:null};
const projectLink=(raw:unknown):Link|null=>{
 const r=rec(raw);
 return r&&r.view==='project'&&r.tab==='daily'&&str(r.project_id)?{label:WORK_ITEM_LABELS.dailyReportsLink,target:{view:'project',projectId:str(r.project_id),tab:'daily'}}:null;
};

function onlyState(name:DataStateName,reason:string|null,raw?:DataState):Pick<WorkItemView,'pageState'|'pageStateLabel'|'unknownReason'>{
 const pageState=raw??parseDataState({states:[name]});
 return {pageState,pageStateLabel:stateLabel(pageState),unknownReason:reason?reasonText(reason):null};
}

const EMPTY_SECTION=(name:DataStateName):Section<never>=>failed(name,'malformed_section');

export function buildWorkItemDetailView(input:WorkItemInput):WorkItemView{
 const u=input.ui??{};
 const tab:WorkItemTab=(WORK_ITEM_TABS as readonly unknown[]).includes(u.tab)?u.tab as WorkItemTab:'work_content';
 const sortDir:'asc'|'desc'=u.sortDir==='asc'?'asc':'desc';
 const ui={tab,selectedKey:str(u.selectedKey)||null,sortDir,historyExpanded:u.historyExpanded===true};
 const tabs=WORK_ITEM_TABS.map(key=>({key,label:WORK_ITEM_LABELS.tabs[key],active:key===tab}));
 const base=(over:Pick<WorkItemView,'pageState'|'pageStateLabel'|'unknownReason'>):WorkItemView=>({
  ...over,hasContent:false,asOfLabel:WORK_ITEM_LABELS.unknown,header:null,breadcrumbs:[],tabs,activeTab:tab,
  workContent:{state:sectionState({states:['unknown']}),quantity:unknownCell(),unit:unknownCell(),amounts:withheld()},
  planActual:planActual(null),
  workOrders:{state:sectionState({states:['unlocated']}),verification:VERIFICATION,rows:[],emptyRow:DATA_STATE_LABELS.unlocated,reason:REASONS['G-RCODE: R01/R02/R09/R10 work-order models unverified'],sourceHealthLink:null},
  parents:EMPTY_SECTION('unknown'),nodes:EMPTY_SECTION('unknown'),deliverables:{...EMPTY_SECTION('unknown'),sortDir},
  history:{state:sectionState({states:['unknown']}),rounds:[],completedExpanded:ui.historyExpanded,completed:null},
  side:{responsible:[],responsibleCell:unknownCell(),operationScope:unknownCell(),dates:{effectiveDue:unknownCell(),pendingDue:unknownCell(),estimatedDue:unknownCell(),sourceUpdatedAt:unknownCell()},warnings:[]},
  caseDailyReports:{label:WORK_ITEM_LABELS.dailyReports,note:WORK_ITEM_LABELS.dailyReportsNote,link:null},
  drawer:{open:false,model:null},selectionDropped:ui.selectedKey!==null,ui:{...ui,selectedKey:null},
 });

 const body=rec(input.body);
 if(!body)return base(onlyState('unknown','malformed_body'));
 const page=parseDataState(body.read_state);
 // Content renders only for partial/stale (the backend never proves a complete population).
 if(!page.states.every(s=>s==='partial'||s==='stale'))return base(onlyState('unknown',null,page));
 const header=rec(body.header);
 if(!header||!isKey(header.id)||!rec(header.source_identity))return base(onlyState('unknown','malformed_body'));
 const sid=rec(header.source_identity)!;
 const [bt,tb,rid]=String(header.id).split('/');
 // The identity object must restate exactly the key; otherwise two identities disagree.
 if(sid.base_token!==bt||sid.table_id!==tb||sid.record_id!==rid)return base(onlyState('unknown','malformed_body'));

 const parents=sectionOf(body.parents,parseParents);
 const nodes=sectionOf(body.nodes,parseNodes);
 const dl=sectionOf(body.deliverables,parseDeliverables);
 const deliverables={...dl,rows:sortDeliverables(dl.rows,sortDir),sortDir};

 // header
 const nameRec=rec(header.name);
 const names=nameRec&&nameRec.state==='existing'&&Array.isArray(nameRec.values)?nameRec.values.map(str).filter(Boolean):[];
 const name:Cell=names.length?{state:'known',text:[...new Set(names)].join('、')}:unknownCell(nameRec?.reason??'work_item_name_unlocated');
 const exec=rec(header.execution_state);
 const statuses=exec&&exec.state==='existing'&&Array.isArray(exec.tasks)?exec.tasks.map(t=>str(rec(t)?.status)).filter(Boolean):[];
 const executionState:Cell=statuses.length?{state:'known',text:[...new Set(statuses)].join('、')}:unknownCell(exec?.reason??'no_work_item_execution_state');
 const itemName=name.text;

 const breadcrumbs:BreadcrumbPath[]=parents.rows.map(p=>({confirmations:p.confirmations,confirmationUnresolved:p.confirmationUnresolved,
  contractLine:p.title.text,workItem:itemName,verification:VERIFICATION}));

 // work content / side: quantity, unit, dates are unproven fields -> always unknown (body values are ignored).
 const wc=rec(body.work_content);
 const side=rec(body.side);
 const people=Array.isArray(side?.responsible_people)?side!.responsible_people as unknown[]:[];
 const seenPeople=new Set<string>();const responsible:string[]=[];
 for(const p of people){const r=rec(p);const n=str(r?.name);const id=str(r?.id);if(n&&id&&!seenPeople.has(id)){seenPeople.add(id);responsible.push(n)}}
 const warnings=Array.isArray(side?.missing_edge_warnings)?(side!.missing_edge_warnings as unknown[]).map(reasonText):[];
 const dateCell=(k:string)=>unknownCell(rec(side?.[k])?.reason);

 const wo=rec(body.work_orders);
 const woState=wo?sectionState(wo.read_state):sectionState({states:['unknown']});
 const cdr=rec(body.case_daily_reports);

 // history tab derives from node rows only (round_history), never from evidence.
 const rounds=nodes.rows.flatMap(n=>n.reworkRounds.map((r,i)=>({key:`${n.key}#${i}`,nodeName:n.nodeName,label:r.label,status:r.status,output:r.output,completedAt:r.completedAt})));
 const completed=nodes.rows.filter(n=>n.completedAt.state==='known').map(n=>({key:n.key,nodeName:n.nodeName,taskTitle:n.taskTitle,completedAt:n.completedAt}));

 // selection-only drawer: technical IDs live here and nowhere else.
 const drawerFor=(key:string|null):DrawerModel|null=>{
  if(!key)return null;
  if(key==='work_item')return {kind:'work_item',key,fields:[{label:'來源識別',value:String(header.id)},{label:'Base',value:bt},{label:'Table',value:tb},{label:'Record',value:rid}]};
  const pa=parents.rows.find(p=>p.key===key);
  if(pa)return {kind:'parent',key,fields:[{label:'關聯',value:pa.verification},{label:'合約項目識別',value:key.slice(7)}]};
  const nd=nodes.rows.find(n=>n.key===key);
  if(nd){const [pid,nid,tid,rnd]=key.slice(5).split('/');return {kind:'node',key,fields:[{label:'專案識別',value:pid},{label:'節點識別',value:nid},{label:'任務識別',value:tid},{label:'SOP 輪次',value:rnd==='-'?WORK_ITEM_LABELS.unknown:rnd},{label:'關聯',value:nd.verification}]}}
  const dv=deliverables.rows.find(d=>d.key===key);
  if(dv)return {kind:'deliverable',key,fields:[{label:'交付物識別',value:key.split(':').slice(2).join(':')},{label:'版本',value:dv.version.text},{label:'證據',value:dv.note}]};
  return null;
 };
 const model=drawerFor(ui.selectedKey);

 return {
  pageState:page,pageStateLabel:stateLabel(page),hasContent:true,unknownReason:null,
  asOfLabel:str(body.as_of)?`資料讀取時間 ${str(body.as_of)}（非來源更新時間）`:WORK_ITEM_LABELS.unknown,
  header:{name,category:textCell(header.category,'malformed_section'),sourceIdentity:'來源識別（詳見明細）',executionState},
  breadcrumbs,tabs,activeTab:tab,
  workContent:{state:sectionState(wc?.read_state??{states:['unknown']}),quantity:unknownCell(rec(wc?.quantity)?.reason),unit:unknownCell(rec(wc?.unit)?.reason),amounts:withheld()},
  planActual:planActual(rec(body.plan_actual)),
  workOrders:{state:isForbidden(woState)?woState:{...woState,states:['unlocated'],label:DATA_STATE_LABELS.unlocated},verification:VERIFICATION,rows:[],
   emptyRow:DATA_STATE_LABELS.unlocated,reason:reasonText(wo?.reason),sourceHealthLink:sourceHealthLink(wo?.source_health_link)},
  parents,nodes,deliverables,
  history:{state:nodes.state,rounds,completedExpanded:ui.historyExpanded,completed:ui.historyExpanded?completed:null},
  side:{responsible,responsibleCell:responsible.length?{state:'known',text:responsible.join('、')}:unknownCell(),
   operationScope:unknownCell(),dates:{effectiveDue:dateCell('effective_due'),pendingDue:dateCell('pending_due'),estimatedDue:dateCell('estimated_due'),sourceUpdatedAt:dateCell('source_updated_at')},warnings},
  caseDailyReports:{label:WORK_ITEM_LABELS.dailyReports,note:WORK_ITEM_LABELS.dailyReportsNote,link:projectLink(cdr?.link)},
  drawer:{open:model!==null,model},selectionDropped:ui.selectedKey!==null&&model===null,
  ui:{...ui,selectedKey:model?ui.selectedKey:null},
 };
}

// Amount values are never output, whatever the body carries (gate G-AMT, no approval).
function withheld():Cell{return {state:'withheld',text:WORK_ITEM_LABELS.withheld,reason:WORK_ITEM_LABELS.withheldReason}}
// Plan/actual stays unavailable until the calculation contract is approved: body figures are ignored.
function planActual(raw:R|null):WorkItemView['planActual']{
 return {state:sectionState({states:['unlocated']}),available:false,label:'無法比較',
  reason:reasonText(raw?.reason??'Calculation contract not approved; same item, unit and period required')};
}
