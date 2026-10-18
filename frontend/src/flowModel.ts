import {NODE_ASSIGNMENT_ORDER, nodeStatusLabel, type AssignmentNode, type AssignmentPerson, type AssignmentTask, type NodeAssignmentList} from './nodeAssignmentApi';
import type {ProductionKey, ProductionStage, ProjectProgress} from './projectProgressApi';
import {joinProgressStages} from './projectProgressView';
import type {Node, Project, User} from './types';

export function projectFlowRoute(route: {tab?: string}) {
 const tab = route.tab || 'flow';
 return {tab: ['overview','progress','flow','tasks'].includes(tab) ? 'flow' : tab,
  focus: tab === 'overview' ? 'top' : tab === 'progress' ? 'evidence' : tab === 'tasks' ? 'tasks' : 'node', allTasks: tab === 'tasks'};
}
export type FlowProgress = {basis: 'tasks'|'evidence'|'nodes'; percent: number; label: string}|{basis: 'unknown'; percent: null; label: string};
export type FlowTask = {id:string;nodeKey:string;title:string;ownerId:string;owner:string;status:string;deadline:string|null;done:boolean;} & ({source:'Lark 任務';task:AssignmentTask}|{source:'本地流程';task:undefined});
export type FlowNode = {
 key: string; label: string; state: string; owners: AssignmentPerson[]; departments: string[];
 tasks: {done: number; total: number}; progress: FlowProgress; deadline: string|null; finalDeadline:string|null; overdue: boolean;
 quantity: {planned: string|null; actual: string|null; unit: string|null; reason: string};
 gaps: string[]; taskRows:FlowTask[]; production?: ProductionStage; assignment?: AssignmentNode; legacy?: Node;
};
const nodeWarnings:Record<string,string>={duplicate_assignment_key:'節點指派重複，請主管核對保留的指派。',unapproved_completion:'來源標示已完成，但尚未經核准。請節點主管核對成果與審批。',lark_status_drift:'來源狀態與任務推算不同，請更新並核對指派。',previous_node_not_done:'前置節點尚未完成，請負責人確認交接或核准略過。'};
export const productionKey = (key: string): ProductionKey|undefined => key === 'field' || key === 'control' || key === 'mapping' || key === 'report' ? key : undefined;
const labels: Record<string,string> = {sales:'業務',pm:'PM',confirmation:'確認單',field:'外業',control:'控制',mapping:'圖資',report:'報告',pricing:'計價',settlement:'結算'};
export const cancelledTask = (status: string) => ['取消','cancelled','canceled','superseded'].includes(status);
export const doneTask = (status: string) => ['已完成','completed'].includes(status);
export const overdueTask = (deadline: string|null, done: boolean, today: string) => !!deadline && deadline.slice(0,10) < today.slice(0,10) && !done;
export function buildFlowModel({project, assignments, progress, today, users=[]}: {project: Project; users?:Pick<User,'id'|'name'>[]; assignments?: NodeAssignmentList; progress?: ProjectProgress; today: string}) {
 const stages=joinProgressStages(progress?.stages || [],assignments?.nodes || []);
 const nodes = NODE_ASSIGNMENT_ORDER.map(key => {
  const stage = stages.find(s => s.key === (key === 'pricing' ? 'billing' : key));
  const assignment = stage?.sop || assignments?.nodes.find(n => n.key === key);
  const legacy = assignments ? undefined : project.nodes.find(n => n.key === key);
  const category = productionKey(key), production = category ? progress?.production[category] : undefined;
  const detailed = assignments?.node_details?.[key]?.tasks.filter(t => !cancelledTask(t.status));
  const local = legacy?.tasks.filter(t => !cancelledTask(t.status)) || [];
  const tasks = detailed ? {done: detailed.filter(t => doneTask(t.status)).length, total: detailed.length} : assignment?.tasks || {done: local.filter(t => doneTask(t.status)).length, total: local.length};
  const taskRows:FlowTask[] = assignment ? (detailed || []).map<FlowTask>(t=>({id:t.id,nodeKey:key,title:t.title,ownerId:t.assignee?.open_id || '',owner:t.assignee?.name || '尚未指派',status:t.status,deadline:t.deadline,done:doneTask(t.status),source:'Lark 任務',task:t})) : local.map<FlowTask>(t=>({id:t.id,nodeKey:key,title:t.title,ownerId:t.owner_id,owner:users.find(u=>u.id===t.owner_id)?.name || '尚未指派',status:t.status,deadline:t.due_date,done:doneTask(t.status),source:'本地流程',task:undefined}));
  taskRows.sort((a,b)=>Number(overdueTask(b.deadline,b.done,today))-Number(overdueTask(a.deadline,a.done,today)) || Number(!a.deadline)-Number(!b.deadline) || (a.deadline || '').localeCompare(b.deadline || '') || a.id.localeCompare(b.id));
  const state = assignment ? nodeStatusLabel(assignment.derived_status) : legacy ? legacy.status === 'approved_skipped' ? '略過' : nodeStatusLabel(legacy.status) : stage ? ({done:'已完成',active:'進行中',waiting:'未開始',unknown:'狀態待確認'})[stage.state] : '狀態待確認';
  const itemProgress = production?.progress || assignment?.evidence?.progress;
  const itemPercent = itemProgress?.percent != null && (itemProgress.known_items ?? itemProgress.items_total) > 0 && (itemProgress.unknown_items ?? 0) === 0 ? Number(itemProgress.percent) : null;
  const nodeProgress: FlowProgress = tasks.total > 0 ? {basis:'tasks',percent:Math.round(tasks.done / tasks.total * 100),label:assignments ? 'Lark 任務完成度' : '本地流程任務完成度'}
   : itemPercent !== null && Number.isFinite(itemPercent) && itemPercent >= 0 && itemPercent <= 100 ? {basis:'evidence',percent:itemPercent,label:'工項點數完成度'} : {basis:'unknown',percent:null,label:'進度未知'};
  const deadline = assignment ? assignment.next_due === undefined ? assignment.deadline : assignment.next_due : legacy?.due_date || null;
  const owner = legacy?.owner_id;
  const n: FlowNode = {key,label:assignment?.label || labels[key],state,owners:assignment?.owners || (owner ? [{open_id:owner,name:users.find(u=>u.id===owner)?.name || '姓名待核對'}] : []),departments:assignment?.departments || [],tasks,progress:nodeProgress,deadline,finalDeadline:assignment?.deadline || legacy?.due_date || null,
   overdue:overdueTask(deadline,['已完成','略過'].includes(state),today),
   quantity:{planned:production?.planned?.qty ?? assignment?.evidence?.planned_qty ?? null,
    actual:production ? production.actual.known ? production.actual.value : null : assignment?.evidence?.actual_known ? assignment.evidence.actual_value : null,
    unit:production?.actual.known ? production.actual.unit_note : null,
    reason:production?.actual.reason || assignment?.evidence?.reason || '實際完成量來源未連結'},
   gaps:[...(assignment?.warnings.map(w=>nodeWarnings[w] || '來源有待核對的節點警示，請主管核對指派資料。') || []),...(category && production && !production.actual.known ? [production.actual.reason || '實際完成量來源未連結'] : [])],taskRows,production,assignment,legacy};
  return n;
 });
 const tasks = nodes.reduce((sum,n) => ({done:sum.done+n.tasks.done,total:sum.total+n.tasks.total}),{done:0,total:0});
 const actualNodes = assignments ? nodes.filter(n => n.assignment) : nodes.filter(n => n.legacy);
 const overall: FlowProgress = tasks.total ? {basis:'tasks',percent:Math.round(tasks.done/tasks.total*100),label:assignments ? 'Lark 任務完成度' : '本地流程任務完成度'}
  : actualNodes.length ? {basis:'nodes',percent:Math.round(actualNodes.filter(n => ['已完成','略過'].includes(n.state)).length / actualNodes.length * 100),label:assignments ? 'Lark 節點交接完成度' : '本地節點交接完成度'} : {basis:'unknown',percent:null,label:'尚無流程資料'};
 return {nodes,overall,tasks};
}
export type TaskFilter = {node?: string; mine: boolean; unassigned: boolean; overdue: boolean; userId: string; today: string};
export function filterFlowTasks<T extends {nodeKey: string; ownerId: string; deadline: string|null; done: boolean}>(tasks: T[], filter: TaskFilter) {
 return tasks.filter(t => (!filter.node || t.nodeKey === filter.node) && (!filter.mine || t.ownerId === filter.userId) && (!filter.unassigned || !t.ownerId) && (!filter.overdue || overdueTask(t.deadline,t.done,filter.today)));
}
export function nodeDispatchProposal({project,node,parentTaskId}: {project: Project; node: Pick<FlowNode,'key'|'label'|'departments'|'deadline'>; parentTaskId: string}) {
 return {project_ref: typeof project.project_ref === 'string' ? project.project_ref : project.id,
  case_ref: typeof project.confirmation_id === 'string' ? project.confirmation_id : '',title:`${project.name} · ${node.label}`,content:'',phase:project.case_type === 'intake' ? '接案前' : '正式',kind:'execution',department:node.departments[0] || '',parent_task_ref:parentTaskId,deadline:node.deadline || ''};
}
