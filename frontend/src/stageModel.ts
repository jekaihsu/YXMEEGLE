import {FINISHED_NODE_STATES,type NodeAssignmentList} from './nodeAssignmentApi';
import {cancelledTask,overdueTask,type FlowNode,type FlowTask} from './flowModel';

export const STATUS_LEVEL_NOTE='案件狀態描述整體案件；節點狀態描述此階段；任務狀態描述單項工作';
export const UNKNOWN_STATUS='狀態待確認';
const CASE_STATUS:Record<string,string>={pending:'尚未開始',in_progress:'進行中',completed:'已完成',paused:'暫停中',engineering_complete:'工程完成、財務待結',source_conflict:'來源待核對',internal:'內部案',active:'進行中',ongoing:'進行中'};
export const caseStatusLabel=(status:string|undefined)=>(status&&CASE_STATUS[status])||UNKNOWN_STATUS;
const TASK_STATUS:Record<string,string>={pending:'待處理',in_progress:'進行中',completed:'已完成',paused:'暫停中',rework:'退回修正',superseded:'舊版留存',canceled:'取消',cancelled:'取消',待處理:'待處理',進行中:'進行中',已完成:'已完成',取消:'取消',待修正:'退回修正'};
export const taskStatusText=(status:string)=>TASK_STATUS[status]||UNKNOWN_STATUS;
export const nodeStatusText=(state:string)=>state||UNKNOWN_STATUS;

export type Blocker={state:'blocked';reasons:string[]}|{state:'clear'}|{state:'unknown'};
export type TaskFlags={unassigned:boolean;blocker:Blocker;overdue:boolean;pending:boolean};
export type TaskView=FlowTask&{flags:TaskFlags;statusText:string};

export function blockerOf(row:FlowTask,node:FlowNode):Blocker {
 if(row.source==='Lark 任務'||row.source==='SOP 任務')return {state:'unknown'};
 const local=node.legacy?.tasks.find(t=>t.id===row.id);
 if(!local)return {state:'unknown'};
 const reasons=[...(local.execution_blockers||[]),...(local.activation_blockers||[]),...(local.status==='paused'?['任務暫停中']:[])];
 return reasons.length?{state:'blocked',reasons}:{state:'clear'};
}
export function taskView(row:FlowTask,node:FlowNode,today:string):TaskView {
 const cancelled=cancelledTask(row.status);
 return {...row,statusText:taskStatusText(row.status),flags:{unassigned:!row.ownerId,blocker:blockerOf(row,node),overdue:overdueTask(row.deadline,row.done,today),pending:!row.done&&!cancelled}};
}

export const STAGE_FILTERS=['pending','unassigned','blocked','mine'] as const;
export type StageFilterKey=typeof STAGE_FILTERS[number];
export const STAGE_FILTER_LABELS:Record<StageFilterKey,string>={pending:'待處理',unassigned:'未指派',blocked:'受阻',mine:'我的任務'};
export type StageFilters=Record<StageFilterKey,boolean>;
export const activeFilters=(filters:StageFilters)=>STAGE_FILTERS.filter(k=>filters[k]);
export function matchesFilters(task:TaskView,filters:StageFilters,userId:string) {
 return (!filters.pending||task.flags.pending)&&(!filters.unassigned||task.flags.unassigned)&&(!filters.blocked||task.flags.blocker.state==='blocked')&&(!filters.mine||(!!userId&&task.ownerId===userId));
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
  const rows=node.taskRows.filter(r=>r.source!=='SOP 任務'&&!cancelledTask(r.status)).map(r=>taskView(r,node,today));
  return {node,rows,matching:rows.filter(t=>matchesFilters(t,filters,userId)),total:node.tasks.total,done:node.tasks.done,loaded:loaded(node.key)};
 };
 const all=ctx.nodes.filter(n=>n.assignment||n.legacy).map(group);
 return {selected:all.find(g=>g.node.key===ctx.selectedId),others:all.filter(g=>g.node.key!==ctx.selectedId&&(g.total>0||g.rows.length>0))};
}

export type NextStep=
 |{kind:'action';title:string;reason:string;stage:string;scope:'stage';taskId?:string;nodeKey:string;button:string;needs:'assign'|'approve'|'edit_status'|'view'}
 |{kind:'view';title:string;reason:string;nodeKey:string;taskId?:string;button:string}
 |{kind:'none';title:string;reasons:string[]}
 |{kind:'unknown';title:string;reasons:string[]};
type StepInput={ctx:StageContext;list?:NodeAssignmentList;userId:string;today:string;fresh:boolean;crossStageAllowed?:(from:string,to:string)=>string|null};
export function stageNextStep({ctx,list,userId,today,fresh,crossStageAllowed}:StepInput):NextStep {
 if(ctx.workflow==='missing')return {kind:'unknown',title:'流程尚未設定',reasons:['此案件目前沒有可顯示的流程節點，不會自動建立或啟動流程。']};
 if(!ctx.currentKnown)return {kind:'unknown',title:'目前階段待確認',reasons:['來源未提供目前階段，無法推薦下一步。請重新整理後再試。']};
 if(ctx.finished)return {kind:'none',title:'目前沒有你可執行的動作',reasons:['所有節點皆已完成或略過。']};
 const reasons:string[]=[];
 if(!fresh)reasons.push('資料可能已過期或寫入尚未開放，請先重新整理。');
 const candidates=(keys:string[])=>keys.flatMap(key=>{
  const node=ctx.nodes.find(n=>n.key===key);if(!node)return [];
  const rows=node.taskRows.filter(r=>r.source!=='SOP 任務'&&!cancelledTask(r.status)&&!r.done).map(r=>taskView(r,node,today));
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
   const unassigned=free.filter(t=>t.flags.unassigned&&t.task?.can.assign).sort(rank)[0];
   if(unassigned&&fresh)return {kind:'action',title:`${label(unassigned)}尚未指派，你可指派執行人`,reason:`${node.label} · ${unassigned.deadline?`期限 ${unassigned.deadline.slice(0,10)}`:'期限未排定'}`,stage,scope:'stage',nodeKey:node.key,taskId:unassigned.id,button:'指派執行人',needs:'assign'};
   const exec=free.filter(t=>t.task?.can.edit_status&&!t.flags.unassigned).sort((a,b)=>Number(b.flags.overdue)-Number(a.flags.overdue)||rank(a,b))[0];
   if(exec&&fresh)return {kind:'action',title:`${exec.flags.overdue?'處理逾期任務':'接續'}${label(exec)}`,reason:`${node.label} · ${exec.deadline?`期限 ${exec.deadline.slice(0,10)}`:'期限未排定'}`,stage,scope:'stage',nodeKey:node.key,taskId:exec.id,button:'開啟任務',needs:'edit_status'};
   if(blocked)return {kind:'view',title:`${label(blocked)}受阻，先查看前置條件`,reason:blocked.flags.blocker.state==='blocked'?blocked.flags.blocker.reasons.join('、'):'',nodeKey:node.key,taskId:blocked.id,button:'查看前置任務'};
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
 return {kind:'none',title:'目前沒有你可執行的動作',reasons};
}

export function blockerSummary(ctx:StageContext,tasksByNode:(key:string)=>TaskView[]):string[] {
 const out:string[]=[];
 for(const key of ctx.currentIds){
  const node=ctx.nodes.find(n=>n.key===key);if(!node)continue;
  if(!node.owners.length)out.push(`${node.label}節點尚未指派負責人`);
  if(node.state==='待審核')out.push(`${node.label}節點等待核准`);
  const rows=tasksByNode(key);
  const blocked=rows.filter(t=>t.flags.blocker.state==='blocked').length;
  if(blocked)out.push(`${blocked} 項任務受阻`);
  const unassigned=rows.filter(t=>t.flags.pending&&t.flags.unassigned).length;
  if(unassigned)out.push(`${unassigned} 項任務尚未指派`);
  const late=rows.filter(t=>t.flags.overdue).length;
  if(late)out.push(`${late} 項任務已逾期`);
  for(const warning of node.gaps)out.push(warning);
 }
 return out;
}
