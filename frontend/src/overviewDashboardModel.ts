import {flowTaskTarget,cancelledTask, type FlowNode} from './flowModel';
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
 const cells:OverviewKpi[]=[];
 if(snapshot.latestDate)cells.push({id:'latest_report',label:'最近已連結回報',value:snapshot.latestDate,detail:stale ? '上次成功資料，待更新' : '已連結外業日報',compact:true,alert:false,target:{tab:'items',node:'field',section:'reports'}});
 if(snapshot.count!==null && field?.planned!==null)cells.push({id:'items',label:'外業關聯工項',value:`${snapshot.count} 筆`,detail:'外業關聯工項',compact:false,alert:false,target:{tab:'items',node:'field'}});
 if(tasks.complete)cells.push({id:'tasks',label:'已指派待辦',value:String(tasks.assigned),detail:`尚未指派 ${tasks.unassigned}`,compact:false,alert:false,target:{tab:'flow',section:'all-tasks'}});
 if(available && !!field && !stale && !assignmentsStale)cells.push({id:'issues',label:'待核對事項',value:String(issues.length),detail:'節點與外業資料檢查',compact:false,alert:issues.length>0,target:issues[0]?.target || {tab:'data',section:'sources'}});
 return cells;
}
export function overviewMissingSummary(cells:OverviewKpi[]) {
 const missing=['外業完成量',...[{id:'latest_report',label:'回報日期'},{id:'items',label:'工項筆數'},{id:'tasks',label:'任務統計'},{id:'issues',label:'異常統計'}].filter(metric=>!cells.some(cell=>cell.id===metric.id)).map(metric=>metric.label)];
 return `待核實：${missing.join('、')}。`;
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
  ...tasks.map(task=>({id:`task:${task.nodeKey}:${task.id}`,title:task.title,reason:task.source,owner:task.owner,ownerId:task.ownerId,deadline:task.deadline,target:flowTaskTarget(task) satisfies OverviewTarget,primary:false})),
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
