import type {AssignmentTask} from './nodeAssignmentApi';
import type {SopTask} from './sopTaskApi';
import {flowTaskTarget,cancelledTask, type FlowNode, type FlowTask} from './flowModel';
import {fieldworkSnapshot, type OverviewAction, type OverviewIssue, type OverviewTarget} from './projectOverviewModel';
import type {ProductionStage} from './projectProgressApi';
import type {ProjectFile} from './types';

export function overviewTasks(nodes:FlowNode[], available:boolean) {
 const all=nodes.flatMap(node=>node.taskRows).filter(task=>task.source!=='本地流程');
 const seen=new Set<string>();
 const open=(status:string)=>['待處理','進行中','待修正','受阻','暫停','blocked','pending','in_progress','rework','paused'].includes(status);
 const rows=all.filter(task=>{const key=`${task.source}:${task.id}`;if(task.done || !open(task.status) || seen.has(key))return false;seen.add(key);return true});
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

type TodoBase={id:string;title:string;reason:string;owner:string;ownerId:string;deadline:string|null;target:OverviewTarget;primary:boolean};
export type OverviewTodo=TodoBase & (
 | {kind:'recommendation';source:'recommendation'}
 | {kind:'sopTask';source:'sop_local';task:SopTask;revision:SopTask['revision'];permissions:SopTask['allowedActions'];node:FlowNode}
 | {kind:'larkTask';source:'lark';task:AssignmentTask;revision:AssignmentTask['revision'];permissions:AssignmentTask['can'];node:FlowNode}
);
const targetKey=(target:OverviewTarget)=>JSON.stringify([target.tab,target.node || '',target.task || '',target.section || '',target.task_source || '']);
export function overviewTodos(action:OverviewAction,issues:OverviewIssue[],nodes:FlowNode[]):OverviewTodo[] {
 const tasks=overviewTasks(nodes,true).rows.slice().sort((a,b)=>(a.deadline || '9999').localeCompare(b.deadline || '9999') || a.id.localeCompare(b.id));
 const taskRows:OverviewTodo[]=tasks.flatMap<OverviewTodo>((task:FlowTask)=>{
  const node=nodes.find(node=>node.key===task.nodeKey);
  if(!node || task.source==='本地流程')return [];
  const base={id:`task:${task.source}:${task.id}`,title:task.title,reason:task.source,owner:task.owner,ownerId:task.ownerId,deadline:task.deadline,target:flowTaskTarget(task) satisfies OverviewTarget,primary:false,node};
  if(task.source==='SOP 任務')return [{...base,kind:'sopTask',source:'sop_local',task:task.sopTask,revision:task.sopTask.revision,permissions:task.sopTask.allowedActions} satisfies OverviewTodo];
  return [{...base,kind:'larkTask',source:'lark',task:task.task,revision:task.task.revision,permissions:task.task.can} satisfies OverviewTodo];
 });
 const selected=taskRows.find(row=>targetKey(row.target)===targetKey(action.target));
 if(selected)selected.primary=true;
 const candidates:OverviewTodo[]=[
  ...(selected?[selected]:[{kind:'recommendation',source:'recommendation',id:'next-action',title:action.title,reason:action.reason,owner:action.owner,ownerId:'',deadline:null,target:action.target,primary:true} satisfies OverviewTodo]),
  ...issues.map(issue=>({...issue,kind:'recommendation',source:'recommendation',ownerId:'',deadline:null,primary:false} satisfies OverviewTodo)),
  ...taskRows,
 ];
 // Real task destinations take precedence over recommendations to the same editor.
 const realTargets=new Set(taskRows.map(row=>targetKey(row.target))),seen=new Set<string>();
 return candidates.filter(row=>{const key=targetKey(row.target);if(seen.has(key) || row.kind==='recommendation'&&realTargets.has(key))return false;seen.add(key);return true});
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
