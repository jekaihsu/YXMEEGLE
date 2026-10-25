import type {AssignmentTask, NodePermissions} from './nodeAssignmentApi';
import type {FlowNode} from './flowModel';
import type {SopOverview, SopTask} from './sopTaskApi';
import type {Project,Task} from './types';

export type WorkbenchTask = {id:string; nodeKey:string} & (
 | {source:'lark'; task:AssignmentTask}
 | {source:'local-sop'; task:SopTask}
 | {source:'legacy'; task:Task}
);
export type ActionState = {visible:boolean; enabled:boolean; disabledReason:string};
export const NODE_ACTIONS = [
 ['assign','指派負責人'], ['complete','完成節點'], ['approve','核准節點'],
 ['reject','退回節點'], ['legacy_complete','直接標記完成'], ['claim','認領節點'], ['create_task','新增任務'],
] as const;
export type WorkbenchAction = typeof NODE_ACTIONS[number][0];
export type ActionRegistry = Record<WorkbenchAction, ActionState>;
export type LocalNode = {key:string; id:string; revision:number; status:string; ownerId:string|null; completedAt:string|null; reason:string|null; can:NodePermissions; disabledReason:string|null;completeDisabledReason?:string|null};
export type NodeWorkbench = {node:FlowNode; source:'lark'|'local-sop'|'legacy'; tasks:WorkbenchTask[]; actions:ActionRegistry; local?:LocalNode};

export function actionRegistry({can,busy=false,reason='',local=false,legacy=false}:{can:NodePermissions;busy?:boolean;reason?:string;local?:boolean;legacy?:boolean}):ActionRegistry {
 const entries=NODE_ACTIONS.map(([id])=>{
  const visible = id==='legacy_complete' ? legacy || can[id]===true : local ? ['assign','complete','reject','create_task'].includes(id) : true;
  const enabled=can[id]===true && !busy && !reason;
  return [id,{visible,enabled,disabledReason:enabled ? '' : reason || (busy ? '正在儲存，請稍候' : '目前狀態或權限不允許此操作')}];
 });
 return Object.fromEntries(entries) as ActionRegistry;
}
export function localCase(project:{case_type?:string;code?:string}) {return project.case_type==='intake' || !project.code?.trim()}
export function buildNodeWorkbench({node,sop,local,busy=false,reason='',can={}}:{node:FlowNode;sop?:SopOverview;local?:LocalNode;busy?:boolean;reason?:string;can?:NodePermissions}):NodeWorkbench {
 const source=node.assignment ? 'lark' : local || sop?.tasks.some(t=>t.nodes.some(n=>n.node_key===node.key)) ? 'local-sop' : 'legacy';
 const remote:WorkbenchTask[]=node.taskRows.flatMap(row=>row.task ? [{id:row.id,nodeKey:node.key,source:'lark' as const,task:row.task}] : []);
 const legacy:WorkbenchTask[]=node.legacy?.tasks.filter(t=>t.status!=='superseded').map(task=>({id:task.id,nodeKey:node.key,source:'legacy',task})) || [];
 const checklist:WorkbenchTask[]=(sop?.tasks || []).filter(t=>t.nodes.some(n=>n.node_key===node.key)).map(task=>({id:task.id,nodeKey:node.key,source:'local-sop',task}));
 const actions=actionRegistry({can:local?.can || can,busy,reason:reason || local?.disabledReason || '',local:!!local,legacy:sop?.enrollment?.policy==='legacy'});
 if(local && !actions.complete.enabled && local.completeDisabledReason)actions.complete.disabledReason=local.completeDisabledReason;
 return {node,source,tasks:[...remote,...legacy,...checklist],local,actions};
}
export type TaskDraft = {title:string;assignee:string;due:string;notes:string;status:string;reason:string};
export type EditorField = 'title'|'assignee'|'due'|'notes'|'status';
export type TaskEditorModel = {draft:TaskDraft; fields:Record<EditorField,{enabled:boolean;reason:string}>;people:{id:string;name:string}[];statuses:{id:string;label:string}[];maxTitle:number;maxNotes:number;dueReason:boolean};
export function editorFields(permissions:Record<EditorField,boolean>,reason='需有此任務的編輯權限'):TaskEditorModel['fields'] {
 return Object.fromEntries(Object.entries(permissions).map(([key,enabled])=>[key,{enabled,reason:enabled?'':reason}])) as TaskEditorModel['fields'];
}
export function draftChanged(a:TaskDraft,b:TaskDraft) {return (['title','assignee','due','notes','status'] as const).some(key=>a[key]!==b[key])}

export function withLocalChecklist(nodes:FlowNode[],sop?:SopOverview,people:{id:string;name:string}[]=[]) :FlowNode[] {
 if(!sop)return nodes;
 return nodes.map(node=>{
  if(node.assignment)return node;
  const local=sop.localNodes?.find(n=>n.key===node.key),counts=Object.entries(sop.nodeCounts).find(([key])=>key===node.key)?.[1];
  if(!local)return node;
  const tasks=counts ? {done:counts.done,total:counts.total} : node.tasks;
  const state=local.status==='completed'?'已完成':local.status==='in_progress'?'進行中':node.state;
  return {...node,state,tasks,owners:local.ownerId ? [{open_id:local.ownerId,name:people.find(p=>p.id===local.ownerId)?.name || node.owners.find(p=>p.open_id===local.ownerId)?.name || '姓名待核對'}] : [],progress:state==='已完成'?{basis:'nodes',percent:100,label:'節點已完成'}:counts&&counts.total?{basis:'tasks',percent:Math.round(counts.done/counts.total*100),label:'SOP 任務完成度'}:{basis:'unknown',percent:null,label:'進度未知'}};
 });
}

export function checklistProject(sop:SopOverview):Project|undefined {
 const header=sop.caseHeader;
 if(!header || !sop.localNodes?.length)return undefined;
 return {id:header.id,code:header.code||'',name:header.name||'案件名稱待核對',client:'',pm_id:'',status:'pending',priority:'',due_date:'',original_due_date:'',created_at:'',started_at:'',description:'',contract_amount:null,estimated_points:null,source_url:'',source_kind:'local',revision:0,case_type:'intake',sop_only:true,
  nodes:sop.localNodes.map(n=>({id:n.id,key:n.key,name:n.key,owner_id:n.ownerId||'',collaborator_ids:[],status:n.status,start_date:null,due_date:null,original_due_date:null,started_at:null,completed_at:n.completedAt,tasks:[]})),files:[],comments:[],daily_reports:[]};
}
