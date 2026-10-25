import {overdueTask,type FlowNode,type FlowTask} from './flowModel';
import type {NodeAssignmentList} from './nodeAssignmentApi';
import type {ProductionStage} from './projectProgressApi';
import type {Project,User} from './types';
export type OverviewTarget={tab:'overview'|'flow'|'items'|'data'|'files'|'people';node?:string;task?:string;section?:string;approval?:string;task_source?:string};
export type OverviewAction={kind:'blocking'|'overdue'|'review'|'soon'|'work';title:string;reason:string;owner:string;allowed:boolean;button:string;target:OverviewTarget};
type ActionInput={nodes:FlowNode[];list?:NodeAssignmentList;user?:User|null;today:string;execution:{allowed:boolean;reason:string};localLead:boolean;assignmentsUnavailable:boolean;blockingApproval?:{id:string;title:string;node:string;owner:string}};
const finished=(node:FlowNode)=>['已完成','略過'].includes(node.state);
const owner=(node:FlowNode|undefined)=>node?.owners.map(p=>p.name).join('、') || node?.assignment?.assigned_by?.name || '尚未指派';
function taskAction(node:FlowNode,task:FlowTask,input:ActionInput,kind:OverviewAction['kind']):OverviewAction{
 const local=node.legacy?.tasks.find(t=>t.id===task.id);
 const allowed=input.execution.allowed && !input.assignmentsUnavailable && (task.task ? input.list?.writes_enabled===true && !input.list.stale && task.task.can.edit_status : local?.can_execute===true && (input.user?.id===task.ownerId || local.assigned_to_viewer===true));
 return {kind,title:kind==='overdue' ? `處理逾期任務「${task.title}」` : kind==='soon' ? `準備到期任務「${task.title}」` : `接續「${task.title}」`,reason:`${node.label} · ${task.deadline ? `期限 ${task.deadline.slice(0,10)}` : '期限未排定'}`,owner:task.owner,allowed,button:allowed ? '開啟任務' : '查看詳情',target:{tab:'flow',node:node.key,task:task.id}};
}
export function selectNextAction(input:ActionInput):OverviewAction{
 const {nodes,list,today}=input,writable=list?.writes_enabled===true && !list.stale && !input.assignmentsUnavailable;
 if(!input.execution.allowed)return {kind:'blocking',title:'先確認案件執行歸屬',reason:input.execution.reason,owner:'案件主管',allowed:false,button:'查看詳情',target:{tab:'data',section:'basic'}};
 if(input.blockingApproval){const approval=input.blockingApproval;return {kind:'blocking',title:'先確認阻擋中的審批',reason:`${approval.title} · 關聯節點暫停中，需核對審批結果。`,owner:approval.owner,allowed:false,button:'查看詳情',target:{tab:'data',section:'approvals',node:approval.node,approval:approval.id}}}
 const active=nodes.filter(n=>(n.assignment || n.legacy) && !finished(n)),current=list?.summary.current_node || active.find(n=>['進行中','待審核','暫停'].includes(n.state))?.key || active[0]?.key;
 const unowned=active.find(n=>!n.owners.length && (n.key===current || ['進行中','待審核','暫停'].includes(n.state)));
 if(unowned){const allowed=!!(list ? writable && (list.can[unowned.key]?.assign || list.can[unowned.key]?.claim) : input.localLead);return {kind:'blocking',title:`先確認${unowned.label}節點的負責人`,reason:'節點尚未指派負責人，需要核對執行與交接窗口。',owner:owner(unowned),allowed,button:allowed ? '前往確認負責人' : '查看詳情',target:{tab:'flow',node:unowned.key}}}
 const tasks=nodes.filter(n=>!finished(n) && !['暫停','paused','狀態待確認'].includes(n.state) && !n.assignment?.warnings.includes('previous_node_not_done')).flatMap(node=>node.taskRows.filter(task=>!task.done && ['待處理','進行中','pending','in_progress','rework','待修正'].includes(task.status) && !(node.legacy?.tasks.find(t=>t.id===task.id)?.execution_blockers?.length) && !(node.legacy?.tasks.find(t=>t.id===task.id)?.activation_blockers?.length)).map(task=>({node,task}))).sort((a,b)=>(a.task.deadline || '9999').localeCompare(b.task.deadline || '9999') || a.task.id.localeCompare(b.task.id));
 const overdue=tasks.find(({task})=>overdueTask(task.deadline,task.done,today));if(overdue)return taskAction(overdue.node,overdue.task,input,'overdue');
 const review=nodes.find(n=>n.state==='待審核');if(review){const allowed=!!(writable && (list?.can[review.key]?.approve || list?.can[review.key]?.reject));return {kind:'review',title:`確認${review.label}節點的送審成果`,reason:'節點正在等待主管審核，需核對成果後再決定。',owner:review.assignment?.approver?.name || review.assignment?.assigned_by?.name || '節點主管',allowed,button:allowed ? '前往審核' : '查看詳情',target:{tab:'flow',node:review.key}}}
 const soonDate=new Date(`${today.slice(0,10)}T00:00:00+08:00`);soonDate.setUTCDate(soonDate.getUTCDate()+3);const soon=tasks.find(({task})=>!!task.deadline && task.deadline.slice(0,10)<=new Date(soonDate.getTime()+8*3600000).toISOString().slice(0,10));if(soon)return taskAction(soon.node,soon.task,input,'soon');
 if(tasks[0])return taskAction(tasks[0].node,tasks[0].task,input,'work');
 const next=nodes.find(n=>(n.assignment || n.legacy) && !finished(n)) || nodes[0];
 return {kind:'work',title:input.assignmentsUnavailable ? '流程來源暫不可用，需要核對' : next && !finished(next) ? `核對${next.label}節點的下一步` : '查看案件流程與交付狀態',reason:input.assignmentsUnavailable ? '目前無法判定下一項工作，請查看來源或稍後重試。' : '目前沒有可確認的下一項任務，請由節點負責人核對來源。',owner:next ? owner(next) : '尚未提供',allowed:false,button:'查看詳情',target:{tab:'flow',node:next?.key}};
}
export type OverviewIssue={id:string;severity:number;title:string;reason:string;owner:string;target:OverviewTarget};
export function needsAttention(nodes:FlowNode[],field?:ProductionStage):OverviewIssue[]{
 const issues:OverviewIssue[]=[];
 for(const node of nodes){
  if(node.state==='已完成' && (node.tasks.done===0 || node.tasks.done<node.tasks.total))issues.push({id:`reconcile:${node.key}`,severity:0,title:`${node.label}狀態待核對`,reason:`節點顯示已完成，但節點任務 ${node.tasks.done}/${node.tasks.total}。請核對兩者來源，不代表工程量未完成。`,owner:owner(node),target:{tab:'flow',node:node.key}});
  if((node.assignment || node.legacy) && node.state!=='略過' && !node.owners.length)issues.push({id:`owner:${node.key}`,severity:2,title:`${node.label}節點負責人尚未指派`,reason:'交接與任務窗口需要核對。',owner:owner(node),target:{tab:'flow',node:node.key}});
 }
 if(field && field.items_total>0 && (!field.actual.known || field.items.some(i=>['ambiguous','unlinked'].includes(i.link_basis))))issues.push({id:'field:unlinked',severity:1,title:'實際完成量尚未連結',reason:field.actual.reason || '工項與回報關聯待核對，無法判定可信的實際完成比例。',owner:owner(nodes.find(n=>n.key==='field') || nodes[0]),target:{tab:'items',node:'field'}});
 return issues.sort((a,b)=>a.severity-b.severity || a.id.localeCompare(b.id));
}
export function fieldworkSnapshot(field:ProductionStage|undefined,reports:Project['daily_reports']=[],stale=false){
 const valid=reports.filter(r=>r.department.includes('外業') && ['source_case_or_link','provisional_case_code','manual_review'].includes(r.match_basis || '') && /^\d{4}-\d{2}-\d{2}$/.test(r.date) && Number.isFinite(Date.parse(r.date)) && new Date(r.date).toISOString().slice(0,10)===r.date).map(r=>r.date).sort().at(-1) || null;
 // The current API has no verified common unit/scope for the planned denominator. Points and work orders cannot establish a physical completion rate.
 return {percent:null,count:field?.items_total ?? null,latestDate:field?.work_orders?.latest_date || valid,reason:!field ? '工程證據尚未提供，暫時無法確認完成量。' : stale ? '來源為上次成功資料，待更新核對。' : !field.actual.known ? field.actual.reason || '日報尚未連結至工項，無法計算實際完成比例。' : field.items_truncated ? '工項資料尚未齊備，無法計算整體完成比例。' : field.items.some(i=>i.link_basis!=='native') ? '工項關聯仍需核對，無法計算可信完成比例。' : '已取得回報量，尚缺同單位與範圍的已驗證計畫分母。'};
}
