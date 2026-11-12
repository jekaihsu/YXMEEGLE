import {FINISHED_NODE_STATES,type NodeAssignmentList} from './nodeAssignmentApi';
import {cancelledTask,overdueTask,type FlowNode,type FlowTask} from './flowModel';
import {uniqueReasons} from './sopActionReasons';

export const STATUS_LEVEL_NOTE='案件狀態描述整體案件；節點狀態描述此階段；任務狀態描述單項工作';
export const UNKNOWN_STATUS='狀態待確認';
const CASE_STATUS:Record<string,string>={pending:'尚未開始',in_progress:'進行中',completed:'已完成',paused:'暫停中',engineering_complete:'工程完成、財務待結',source_conflict:'來源待核對',internal:'內部案',active:'進行中',ongoing:'進行中'};
export type CaseStatusSource={progress_status?:string;execution_status?:string;status?:string};
export const caseProgressStatus=(p:CaseStatusSource)=>p.progress_status??p.execution_status??p.status;
export const sourceStatusPending=(p:CaseStatusSource)=>(p.execution_status??p.status)==='paused'&&p.progress_status!==undefined&&p.progress_status!=='paused';
export const caseStatusLabel=(value:string|CaseStatusSource|undefined)=>{const status=typeof value==='object'?caseProgressStatus(value):value;return (status&&CASE_STATUS[status])||UNKNOWN_STATUS;};
// One dictionary for Lark, local-flow and SOP tasks: the same lifecycle state reads the same everywhere (R12, R38).
const TASK_STATUS:Record<string,string>={pending:'待處理',in_progress:'進行中',completed:'已完成',paused:'暫停中',rework:'退回修正',blocked:'受阻',superseded:'舊版留存',canceled:'取消',cancelled:'取消',待處理:'待處理',尚未開始:'待處理',進行中:'進行中',已完成:'已完成',取消:'取消',待修正:'退回修正',退回修正:'退回修正',暫停中:'暫停中',受阻:'受阻'};
export const taskStatusText=(status:string)=>TASK_STATUS[status]||UNKNOWN_STATUS;
export const nodeStatusText=(state:string)=>state||UNKNOWN_STATUS;

export type Blocker={state:'blocked';reasons:string[]}|{state:'clear'}|{state:'unknown'};
export type TaskFlags={unassigned:boolean;blocker:Blocker;overdue:boolean;pending:boolean};
export type TaskView=FlowTask&{flags:TaskFlags;statusText:string};

export function blockerOf(row:FlowTask,node:FlowNode):Blocker {
 if(row.source==='SOP 任務')return row.sopTask.state==='blocked'?{state:'blocked',reasons:['SOP 任務標示受阻']}:{state:'clear'};
 if(row.source==='Lark 任務')return {state:'unknown'};
 const local=node.legacy?.tasks.find(t=>t.id===row.id);
 if(!local)return {state:'unknown'};
 const reasons=uniqueReasons([...(local.execution_blockers||[]),...(local.status==='pending'?(local.activation_blockers||[]):[]),...(local.status==='paused'?['任務暫停中']:[])]);
 return reasons.length?{state:'blocked',reasons}:{state:'clear'};
}
export function taskView(row:FlowTask,node:FlowNode,today:string):TaskView {
 const cancelled=cancelledTask(row.status);
 return {...row,statusText:taskStatusText(row.status),flags:{unassigned:!row.ownerId,blocker:blockerOf(row,node),overdue:overdueTask(row.deadline,row.done,today),pending:!row.done&&!cancelled}};
}

export const STAGE_FILTERS=['pending','unassigned','blocked','mine','overdue'] as const;
export type StageFilterKey=typeof STAGE_FILTERS[number];
export const STAGE_FILTER_LABELS:Record<StageFilterKey,string>={pending:'未完成',unassigned:'未指派',blocked:'受阻',mine:'我的任務',overdue:'逾期'};
export type StageFilters=Record<StageFilterKey,boolean>;
export const activeFilters=(filters:StageFilters)=>STAGE_FILTERS.filter(k=>filters[k]);
export function matchesFilters(task:TaskView,filters:StageFilters,userId:string) {
 return (!filters.pending||task.flags.pending)&&(!filters.unassigned||task.flags.unassigned)&&(!filters.blocked||task.flags.blocker.state==='blocked')&&(!filters.mine||(!!userId&&task.ownerId===userId))&&(!filters.overdue||task.flags.overdue);
}
export const blockedKnown=(tasks:TaskView[])=>tasks.some(t=>t.flags.blocker.state!=='unknown');

export type NodeStats={label:string;percent:number|null;done:number;total:number;known:boolean};
export function nodeStats(node:FlowNode):NodeStats {
 const {done,total}=node.tasks;
 if(!Number.isFinite(done)||!Number.isFinite(total)||total<0||done>total)return {label:'數據待確認',percent:null,done,total,known:false};
 if(total===0)return {label:'無適用任務',percent:null,done,total,known:true};
 const percent=Math.round(done/total*100);
 return {label:`${done} / ${total} 已完成`,percent,done,total,known:true};
}

export type StageContext={
 nodes:FlowNode[];currentIds:string[];selectedId:string;selectedReason:'url'|'current'|'fallback'|'none';
 currentSelected:boolean;otherCurrent:string[];workflow:'ready'|'missing';currentKnown:boolean;finished:boolean;
};
export function resolveStages({nodes,list,requested}:{nodes:FlowNode[];list?:NodeAssignmentList;requested?:string}):StageContext {
 const real=nodes.filter(n=>n.assignment||n.legacy);
 if(!real.length)return {nodes,currentIds:[],selectedId:'',selectedReason:'none',currentSelected:false,otherCurrent:[],workflow:'missing',currentKnown:false,finished:false};
 const finished=real.every(n=>FINISHED_NODE_STATES.includes(n.state));
 const server=list?.summary.current_node;
 const fromServer=server&&real.some(n=>n.key===server)?[server]:[];
 const fromState=fromServer.length||finished?fromServer:real.filter(n=>['進行中','待審核','待處理'].includes(n.state)).slice(0,1).map(n=>n.key);
 const currentIds=real.filter(n=>fromState.includes(n.key)).map(n=>n.key);
 const fromUrl=requested&&real.some(n=>n.key===requested)?requested:'';
 const selectedId=fromUrl||currentIds[0]||real[0].key;
 return {nodes,currentIds,selectedId,selectedReason:fromUrl?'url':currentIds[0]?'current':'fallback',currentSelected:currentIds.includes(selectedId),otherCurrent:currentIds.slice(1),workflow:'ready',currentKnown:currentIds.length>0||finished,finished};
}

export type TaskGroup={node:FlowNode;rows:TaskView[];matching:TaskView[];total:number;done:number;loaded:boolean};
export function groupTasks({ctx,filters,userId,today,loaded}:{ctx:StageContext;filters:StageFilters;userId:string;today:string;loaded:(key:string)=>boolean}):{selected:TaskGroup|undefined;others:TaskGroup[]} {
 const group=(node:FlowNode):TaskGroup=>{
  const rows=node.taskRows.filter(r=>!cancelledTask(r.status)).map(r=>taskView(r,node,today));
  return {node,rows,matching:rows.filter(t=>matchesFilters(t,filters,userId)),total:node.tasks.total,done:node.tasks.done,loaded:loaded(node.key)};
 };
 const all=ctx.nodes.filter(n=>n.assignment||n.legacy).map(group);
 return {selected:all.find(g=>g.node.key===ctx.selectedId),others:all.filter(g=>g.node.key!==ctx.selectedId&&(g.total>0||g.rows.length>0))};
}

export type StageBlock={kind:'source'|'paused'|'meegle'|'ownership'|'execution';reason:string};
const BLOCK_TITLES:Record<StageBlock['kind'],string>={source:'來源案件狀態待核對',paused:'案件暫停中',meegle:'僅供參考',ownership:'尚未核定執行歸屬',execution:'案件執行受限'};


export function sharedBlockerReasons(rows:TaskView[]):string[] {
 const pending=rows.filter(row=>row.flags.pending);
 if(!pending.length)return [];
 const first=pending[0].flags.blocker;
 return first.state==='blocked'?first.reasons.filter(reason=>pending.every(row=>row.flags.blocker.state==='blocked'&&row.flags.blocker.reasons.includes(reason))):[];
}

export type NextStep=
 |{kind:'action';title:string;reason:string;stage:string;scope:'stage';taskId?:string;nodeKey:string;button:string;needs:'assign'|'approve'|'edit_status'|'view'}
 |{kind:'view';title:string;reason:string;nodeKey:string;taskId?:string;button:string}
 |{kind:'none';title:string;reasons:string[]}
 |{kind:'unknown';title:string;reasons:string[]};
type StepInput={caseStatus?:string;ctx:StageContext;list?:NodeAssignmentList;today:string;fresh:boolean;block?:StageBlock;crossStageAllowed?:(from:string,to:string)=>string|null};
export function stageNextStep({caseStatus,ctx,list,today,fresh,block,crossStageAllowed}:StepInput):NextStep {
 if(caseStatus==='completed')return {kind:'none',title:'已完成',reasons:[]};
 if(ctx.workflow==='missing')return {kind:'unknown',title:'流程尚未設定',reasons:['此案件目前沒有可顯示的流程節點，不會自動建立或啟動流程。']};
 if(!ctx.currentKnown)return {kind:'unknown',title:'目前階段待確認',reasons:['來源未提供目前階段，無法推薦下一步。請重新整理後再試。']};
 if(ctx.finished)return {kind:'none',title:'已完成',reasons:[]};
 const reasons:string[]=[];
 if(block)return {kind:'none',title:BLOCK_TITLES[block.kind],reasons:block.reason===BLOCK_TITLES[block.kind]?[]:[block.reason]};
 if(!fresh)reasons.push('等待來源核對，暫無可執行的動作。');
 const candidates=(keys:string[])=>keys.flatMap(key=>{
  const node=ctx.nodes.find(n=>n.key===key);if(!node)return [];
  const rows=node.taskRows.filter(r=>!cancelledTask(r.status)&&!r.done).map(r=>taskView(r,node,today));
  return [{node,rows}];
 });
 const rank=(a:TaskView,b:TaskView)=>Number(!a.deadline)-Number(!b.deadline)||(a.deadline||'').localeCompare(b.deadline||'')||a.id.localeCompare(b.id);
 const pick=(keys:string[],stage:string):NextStep|undefined=>{
  for(const {node,rows} of candidates(keys)){
   const can=list?.can[node.key]||{};
   const label=(task:TaskView)=>`「${task.title}」`;
   const approve=node.state==='待審核'&&fresh&&(can.approve||can.reject);
   if(approve)return {kind:'action',title:`確認${node.label}節點的送審成果`,reason:`${node.label}節點正在等待核准，你有核准權限。`,stage,scope:'stage',nodeKey:node.key,button:'前往審核',needs:'approve'};
   const blocked=rows.filter(t=>t.flags.blocker.state==='blocked').sort(rank)[0];
   const free=rows.filter(t=>t.flags.blocker.state!=='blocked');
   const canAssign=(t:TaskView)=>t.source==='SOP 任務'?t.sopTask.allowedActions.includes('edit'):!!t.task?.can.assign;
   const unassigned=free.filter(t=>t.flags.unassigned&&canAssign(t)).sort(rank)[0];
   if(unassigned&&fresh)return {kind:'action',title:`${label(unassigned)}尚未指派，你可指派執行人`,reason:`${node.label} · ${unassigned.deadline?`期限 ${unassigned.deadline.slice(0,10)}`:'期限未排定'}`,stage,scope:'stage',nodeKey:node.key,taskId:unassigned.id,button:'指派執行人',needs:'assign'};
   const runnable=(t:TaskView)=>t.source==='SOP 任務'?t.sopTask.allowedActions.some(a=>['start','complete','resume'].includes(a)):t.task?t.task.can.edit_status:node.legacy?.tasks.find(x=>x.id===t.id)?.can_execute===true;
   const exec=free.filter(t=>runnable(t)&&!t.flags.unassigned).sort((a,b)=>Number(b.flags.overdue)-Number(a.flags.overdue)||rank(a,b))[0];
   if(exec&&fresh)return {kind:'action',title:`${exec.flags.overdue?'處理逾期任務':'接續'}${label(exec)}`,reason:`${node.label} · ${exec.deadline?`期限 ${exec.deadline.slice(0,10)}`:'期限未排定'}`,stage,scope:'stage',nodeKey:node.key,taskId:exec.id,button:'開啟任務',needs:'edit_status'};
   if(blocked)return {kind:'view',title:`受阻：${label(blocked)}`,reason:blocked.flags.blocker.state==='blocked'?blocked.flags.blocker.reasons[0]:'',nodeKey:node.key,taskId:blocked.id,button:'查看受阻原因'};
  }
 };
 const stageKeys=ctx.currentIds;
 const here=pick(stageKeys,stageKeys[0]);
 if(here)return here;
 reasons.push('目前階段沒有你可執行且流程已開放的任務。');
 if(crossStageAllowed){
  for(const next of ctx.nodes.filter(n=>!stageKeys.includes(n.key))){
   const allowed=stageKeys.map(from=>crossStageAllowed(from,next.key)).find(Boolean);
   if(!allowed)continue;
   const there=pick([next.key],next.key);
   if(there&&there.kind==='action')return {...there,reason:`目前階段無可執行項；依流程允許先處理${next.label}（${allowed}）。`};
  }
 }
 const current=ctx.nodes.find(n=>n.key===ctx.currentIds[0]);
 return {kind:'none',title:current?.state==='待審核'?'等待核准':!current?.owners.length?'等待指派':`等待${current.owners.map(o=>o.name).join('、')}處理`,reasons};
}

// Causal priority: explicit source/lifecycle gates, execution ownership, generic case
// summaries, task prerequisites, then scheduling. Unknown reasons retain server order.
export function primaryBlockerReasons(reasons:string[]):string[] {
 const rank=(reason:string)=> /來源案件狀態待核對|來源標示結案|案件暫停中/.test(reason)?0
  : /接案尚未轉正式案件/.test(reason)?1
  : /執行歸屬|Meegle|暫不可執行/.test(reason)?2
  : /案件已暫停、結案或來源待核對/.test(reason)?3
  : /尚未排定開始日期|尚未到排程日期|排程日期無效/.test(reason)?5:4;
 return uniqueReasons(reasons).sort((a,b)=>rank(a)-rank(b));
}
