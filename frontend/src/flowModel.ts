import {NODE_NAMES, STATUS} from './workflowLabels';
import {FINISHED_NODE_STATES, isProductionNode, NODE_ASSIGNMENT_ORDER, nodeStatusLabel, type AssignmentNode, type AssignmentPerson, type AssignmentTask, type NodeAssignmentList} from './nodeAssignmentApi';
import type {ProductionKey, ProductionStage, ProjectProgress} from './projectProgressApi';
import {joinProgressStages} from './projectProgressView';
import type {Node, Project, User} from './types';

export function projectFlowRoute(route: {tab?: string}) {
 const tab = route.tab || 'flow';
 return {tab: ['overview','progress','flow','tasks'].includes(tab) ? 'flow' : tab,
  focus: tab === 'overview' ? 'top' : tab === 'progress' ? 'evidence' : tab === 'tasks' ? 'tasks' : 'node', allTasks: tab === 'tasks'};
}
export type FlowProgress = {basis: 'tasks'|'evidence'|'nodes'; percent: number; label: string}|{basis: 'unknown'|'skipped'; percent: null; label: string};
export type FlowTask = {id:string;nodeKey:string;title:string;ownerId:string;owner:string;status:string;deadline:string|null;done:boolean;} & ({source:'Lark 任務';task:AssignmentTask}|{source:'本地流程';task:undefined});
export type FlowNode = {
 key: string; label: string; state: string; owners: AssignmentPerson[]; departments: string[];
 tasks: {done: number; total: number}; progress: FlowProgress; deadline: string|null; finalDeadline:string|null; overdue: boolean;
 quantity: {planned: string|null; actual: string|null; unit: string|null; reason: string};
 gaps: string[]; taskRows:FlowTask[]; production?: ProductionStage; assignment?: AssignmentNode; legacy?: Node;
};
const nodeWarnings:Record<string,string>={duplicate_assignment_key:'節點指派重複，請主管核對保留的指派。',unapproved_completion:'來源標示已完成，但尚未經核准。請節點主管核對成果與審批。',lark_status_drift:'來源狀態與任務推算不同，請更新並核對指派。',previous_node_not_done:'前置節點尚未完成，請負責人確認交接或核准略過。'};
export const productionKey = (key: string): ProductionKey|undefined => isProductionNode(key) ? key : undefined;
export const cancelledTask = (status: string) => ['取消','cancelled','canceled','superseded'].includes(status);
export const doneTask = (status: string) => ['已完成','completed'].includes(status);
export const overdueTask = (deadline: string|null, done: boolean, today: string) => !!deadline && deadline.slice(0,10) < today.slice(0,10) && !done;
type FlowInput = {project: Project; users?:Pick<User,'id'|'name'>[]; assignments?:NodeAssignmentList; progress?:ProjectProgress; today:string};

export function selectedFlowNode(project:Project, requested:string|undefined, list?:NodeAssignmentList) {
 const key=project.nodes.find(n=>n.id===requested)?.key || requested;
 return NODE_ASSIGNMENT_ORDER.find(n=>n===key) || list?.summary.current_node || project.nodes.find(n=>n.status==='in_progress')?.key || 'sales';
}
function workflowState(assignment:AssignmentNode|undefined, legacy:Node|undefined, stage:ReturnType<typeof joinProgressStages>[number]|undefined) {
 if(assignment)return nodeStatusLabel(assignment.derived_status);
 if(legacy)return legacy.status==='approved_skipped' ? '略過' : nodeStatusLabel(legacy.status);
 return stage ? ({done:'已完成',active:'進行中',waiting:'未開始',unknown:'狀態待確認'})[stage.state] : '狀態待確認';
}
export function nodeFlowProgress(state:string,tasks:{done:number;total:number},local:boolean):FlowProgress {
 if(state==='略過')return {basis:'skipped',percent:null,label:'略過'};
 if(state==='已完成')return {basis:'nodes',percent:100,label:'節點已完成'};
 if(tasks.total)return {basis:'tasks',percent:Math.round(tasks.done/tasks.total*100),label:local ? '本地流程任務完成度' : 'Lark 任務完成度'};
 return {basis:'unknown',percent:null,label:'進度未知'};
}
function localTaskRows(node:Node|undefined,users:Pick<User,'id'|'name'>[]):FlowTask[] {
 if(!node)return [];
 return node.tasks.filter(t=>!cancelledTask(t.status)).map(t=>({
  id:t.id,nodeKey:node.key,title:t.title,ownerId:t.owner_id,
  owner:users.find(u=>u.id===t.owner_id)?.name || '尚未指派',status:STATUS[t.status] || t.status,
  deadline:t.due_date,done:doneTask(t.status),source:'本地流程',task:undefined
 }));
}
function assignmentTaskRows(key:string,tasks:AssignmentTask[]):FlowTask[] {
 return tasks.map(t=>({id:t.id,nodeKey:key,title:t.title,ownerId:t.assignee?.open_id || '',owner:t.assignee?.name || '尚未指派',status:t.status,deadline:t.deadline,done:doneTask(t.status),source:'Lark 任務',task:t}));
}
function taskOrder(today:string) {
 return (a:FlowTask,b:FlowTask)=>Number(overdueTask(b.deadline,b.done,today))-Number(overdueTask(a.deadline,a.done,today))
  || Number(!a.deadline)-Number(!b.deadline) || (a.deadline || '').localeCompare(b.deadline || '') || a.id.localeCompare(b.id);
}
function nodeQuantity(production:ProductionStage|undefined,assignment:AssignmentNode|undefined):FlowNode['quantity'] {
 return {
  planned:production?.planned?.qty ?? assignment?.evidence?.planned_qty ?? null,
  actual:production ? production.actual.known ? production.actual.value : null : assignment?.evidence?.actual_known ? assignment.evidence.actual_value : null,
  unit:production?.actual.known ? production.actual.unit_note : null,
  reason:production?.actual.reason || assignment?.evidence?.reason || '實際完成量來源未連結'
 };
}
function overallProgress(nodes:FlowNode[]):FlowProgress {
 const counted=nodes.filter(n=>(n.assignment || n.legacy) && n.state!=='略過');
 if(!counted.length)return {basis:'unknown',percent:null,label:'尚無流程資料'};
 if(counted.some(n=>n.progress.percent===null))return {basis:'unknown',percent:null,label:'部分節點進度未知（略過不計）'};
 const percent=Math.round(counted.reduce((sum,n)=>sum+(n.progress.percent || 0),0)/counted.length);
 return {basis:'nodes',percent,label:'節點完成度（略過不計）'};
}
export function needsViewerAction(node:FlowNode,list:NodeAssignmentList,userId:string) {
 if(FINISHED_NODE_STATES.includes(node.state))return false;
 const owns=node.owners.some(p=>p.open_id===userId), ownTask=node.taskRows.some(t=>t.ownerId===userId && !t.done);
 if(node.state==='未開始' && !owns && !ownTask)return false;
 if(node.state==='待審核' && (list.can[node.key]?.approve || list.can[node.key]?.reject))return true;
 return ownTask || node.taskRows.some(t=>!t.ownerId && !t.done && t.task?.can.assign) || owns && (node.overdue || node.state==='未開始');
}
export function buildFlowModel({project,assignments,progress,today,users=[]}:FlowInput) {
 const stages=joinProgressStages(progress?.stages || [],assignments?.nodes || []);
 const nodes=NODE_ASSIGNMENT_ORDER.map(key=>{
  const stage=stages.find(s=>s.key===(key==='pricing' ? 'billing' : key));
  const assignment=stage?.sop || assignments?.nodes.find(n=>n.key===key);
  const legacy=assignments ? undefined : project.nodes.find(n=>n.key===key);
  const category=productionKey(key), production=category ? progress?.production[category] : undefined;
  const detailed=assignments?.node_details?.[key]?.tasks.filter(t=>!cancelledTask(t.status));
  const taskRows=(assignment ? assignmentTaskRows(key,detailed || []) : localTaskRows(legacy,users)).sort(taskOrder(today));
  const tasks=detailed || !assignment ? {done:taskRows.filter(t=>t.done).length,total:taskRows.length} : assignment.tasks;
  const state=workflowState(assignment,legacy,stage);
  const deadline=assignment ? assignment.next_due===undefined ? assignment.deadline : assignment.next_due : legacy?.due_date || null;
  const owner=legacy?.owner_id;
  const quantity=nodeQuantity(production,assignment);
  return {
   key,label:NODE_NAMES[key],state,
   owners:assignment?.owners || (owner ? [{open_id:owner,name:users.find(u=>u.id===owner)?.name || '姓名待核對'}] : []),
   departments:assignment?.departments || [],tasks,progress:nodeFlowProgress(state,tasks,!assignments),deadline,
   finalDeadline:assignment?.deadline || legacy?.due_date || null,overdue:overdueTask(deadline,FINISHED_NODE_STATES.includes(state),today),quantity,
   gaps:[...(assignment?.warnings.map(w=>nodeWarnings[w] || '來源有待核對的節點警示，請主管核對指派資料。') || []),
    ...(category && production && !production.actual.known ? [quantity.reason] : [])],taskRows,production,assignment,legacy
  } satisfies FlowNode;
 });
 const tasks=nodes.reduce((sum,n)=>({done:sum.done+n.tasks.done,total:sum.total+n.tasks.total}),{done:0,total:0});
 return {nodes,overall:overallProgress(nodes),tasks};
}
export type TaskFilter = {node?: string; mine: boolean; unassigned: boolean; overdue: boolean; userId: string; today: string};
export function filterFlowTasks<T extends {nodeKey: string; ownerId: string; deadline: string|null; done: boolean}>(tasks: T[], filter: TaskFilter) {
 return tasks.filter(t => (!filter.node || t.nodeKey === filter.node) && (!filter.mine || t.ownerId === filter.userId) && (!filter.unassigned || !t.ownerId) && (!filter.overdue || overdueTask(t.deadline,t.done,filter.today)));
}
export function nodeDispatchProposal({project,node,parentTaskId}: {project: Project; node: Pick<FlowNode,'key'|'label'|'departments'|'deadline'>; parentTaskId: string}) {
 return {project_ref: typeof project.project_ref === 'string' ? project.project_ref : project.id,
  case_ref: typeof project.confirmation_id === 'string' ? project.confirmation_id : '',title:`${project.name} · ${node.label}`,content:'',phase:project.case_type === 'intake' ? '接案前' : '正式',kind:'execution',department:node.departments[0] || '',parent_task_ref:parentTaskId,deadline:node.deadline || ''};
}
