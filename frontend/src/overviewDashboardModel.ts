import {cancelledTask, type FlowNode} from './flowModel';
import {fieldworkSnapshot, type OverviewAction, type OverviewIssue, type OverviewTarget} from './projectOverviewModel';
import type {ProductionStage} from './projectProgressApi';
import type {ProjectFile} from './types';

export function overviewTasks(nodes:FlowNode[], available:boolean) {
 const all=nodes.flatMap(node=>node.taskRows);
 const open=(status:string)=>['待處理','進行中','待修正','暫停','pending','in_progress','rework','paused'].includes(status);
 const rows=all.filter(task=>!task.done && open(task.status));
 const complete=available && nodes.every(node=>node.taskRows.length===node.tasks.total) && all.every(task=>task.done || cancelledTask(task.status) || open(task.status));
 return {rows,complete,assigned:rows.filter(task=>!!task.ownerId).length,unassigned:rows.filter(task=>!task.ownerId).length};
}
export type OverviewKpi={id:string;label:string;value:string;detail:string;compact:boolean;alert:boolean;target:OverviewTarget};
export function overviewKpis({field,nodes,issues,available,stale=false,assignmentsStale=false}:{field?:ProductionStage;nodes:FlowNode[];issues:OverviewIssue[];available:boolean;stale?:boolean;assignmentsStale?:boolean}):OverviewKpi[] {
 const snapshot=fieldworkSnapshot(field,[],stale),tasks=overviewTasks(nodes,available && !assignmentsStale);
 return [
  {id:'field',label:'外業進度',value:'尚無可信完成量',detail:snapshot.reason,compact:true,alert:false,target:{tab:'items',node:'field'}},
  {id:'items',label:'合約工項',value:snapshot.count===null || field?.planned===null ? '未知' : `${snapshot.count} 筆`,detail:'外業關聯工項',compact:false,alert:false,target:{tab:'items',node:'field'}},
  {id:'planned',label:'計畫數量',value:'依各工項顯示',detail:'不同單位不加總',compact:true,alert:false,target:{tab:'items',node:'field'}},
  {id:'actual',label:'實際完成數量',value:'未知',detail:'尚缺可核實的完成量',compact:false,alert:false,target:{tab:'items',node:'field'}},
  {id:'tasks',label:'待處理任務',value:tasks.complete ? String(tasks.assigned) : '待核對',detail:tasks.complete ? `尚未指派 ${tasks.unassigned}` : '任務來源尚未完整核實',compact:false,alert:false,target:{tab:'flow',section:'all-tasks'}},
  {id:'issues',label:'異常事項',value:available && !!field && !stale ? String(issues.length) : '待核對',detail:available && !!field && !stale ? issues.length ? '需要確認' : '目前無需立即處理' : '來源待更新核對',compact:false,alert:available && !!field && !stale && issues.length>0,target:issues[0]?.target || {tab:'data',section:'sources'}},
 ];
}
export type OverviewTodo={id:string;title:string;reason:string;owner:string;ownerId:string;deadline:string|null;target:OverviewTarget;primary:boolean};
const targetKey=(target:OverviewTarget)=>JSON.stringify([target.tab,target.node || '',target.task || '',target.section || '']);
export function overviewTodos(action:OverviewAction,issues:OverviewIssue[],nodes:FlowNode[]) {
 const actionable=nodes.filter(node=>!['已完成','略過','暫停','狀態待確認'].includes(node.state) && !node.assignment?.warnings.includes('previous_node_not_done'));
 const tasks=overviewTasks(actionable,true).rows.filter(task=>{const local=actionable.find(node=>node.key===task.nodeKey)?.legacy?.tasks.find(row=>row.id===task.id);return !local?.execution_blockers?.length && !local?.activation_blockers?.length && !['暫停','paused'].includes(task.status)}).slice().sort((a,b)=>(a.deadline || '9999').localeCompare(b.deadline || '9999') || a.id.localeCompare(b.id));
 const selected=tasks.find(task=>task.id===action.target.task && task.nodeKey===action.target.node);
 const candidates:OverviewTodo[]=[
  {id:'next-action',title:action.title,reason:action.reason,owner:action.owner,ownerId:selected?.ownerId || '',deadline:selected?.deadline || null,target:action.target,primary:true},
  ...issues.map(issue=>({...issue,ownerId:'',deadline:null,primary:false})),
  ...tasks.map(task=>({id:`task:${task.nodeKey}:${task.id}`,title:task.title,reason:task.source,owner:task.owner,ownerId:task.ownerId,deadline:task.deadline,target:{tab:'flow',node:task.nodeKey,task:task.id} satisfies OverviewTarget,primary:false})),
 ];
 const seen=new Set<string>();
 return candidates.filter(row=>{const key=targetKey(row.target);if(seen.has(key))return false;seen.add(key);return true});
}
const documentLabels:Record<string,string>={field_raw:'測量資料',drawing:'圖資',report:'報告',quote_confirmation:'報價／確認單',photo:'照片',evidence:'交付佐證',other:'其他'};
export function overviewDocuments(files:ProjectFile[],catalog:{id:string;name?:string;label?:string}[]=[]) {
 const groups=new Map<string,{id:string;label:string;count:number}>();
 for(const file of files){
  if(file.withdrawn)continue;
  const id=typeof file.category_id==='string' ? file.category_id : 'unclassified';
  const label=documentLabels[id] || catalog.find(category=>category.id===id)?.name || catalog.find(category=>category.id===id)?.label || '分類待核對';
  const group=groups.get(id);if(group)group.count++;else groups.set(id,{id,label,count:1});
 }
 return [...groups.values()];
}
