import {useEffect,useState,type MutableRefObject,type ReactNode} from 'react';
import {Badge,Button,Skeleton} from './design';
import type {Ctx} from './appCommon';
import type {Project} from './types';
import type {AssignmentMutation,NodeAssignmentDetail,NodeAssignmentError} from './nodeAssignmentApi';
import {filterFlowTasks,overdueTask,type FlowNode} from './flowModel';
import {taskFilters,withTaskFilter} from './projectRoutes';
import {FlowAction,TaskPersonPicker} from './FlowActions';
import {AssignmentTaskInspector} from './AssignmentTaskInspector';
import {isProductionSeedTask,productionPlanFacts} from './productionPlan';
import {ProductionPlanFacts} from './FlowEvidence';
export function FlowTasks({c,p,nodes,selected,details,all,onScope,busy,reason,error,mutate,loading,incomplete,evidence,reopened,children}:{c:Ctx;p:Project;nodes:FlowNode[];selected:string;details:Record<string,NodeAssignmentDetail>;all:boolean;onScope:(all:boolean)=>void;busy:boolean;reason:string;error:NodeAssignmentError|null;mutate:(m:AssignmentMutation)=>Promise<boolean>;loading:boolean;incomplete:boolean;evidence:ReactNode;reopened?:MutableRefObject<string>;children?:ReactNode}){
 const filters=taskFilters(c.route);
 const [assigning,setAssigning]=useState('');
 const rows=nodes.flatMap(n=>n.taskRows).filter(row=>row.source!=='SOP 任務');
 const filtered=filterFlowTasks(rows,{...filters,node:all ? undefined : selected,userId:c.s.user?.id || '',today:c.w.as_of});
 const sopTask=c.route.task_source==='sop_local';
 const localTask=sopTask || p.nodes.some(n=>n.tasks.some(t=>t.id===c.route.task));
 const selectedRow=sopTask ? undefined : rows.find(r=>r.id===c.route.task && r.task);
 const seed=filtered.find(row=>row.nodeKey===selected && row.task && isProductionSeedTask(row.task,selected));
 const taskPlan=selectedRow?.task ? productionPlanFacts(selectedRow.task,selectedRow.nodeKey,nodes.find(n=>n.key===selectedRow.nodeKey)?.production) : null;
 useEffect(()=>{
  if(c.route.task || loading || !reopened?.current)return;
  const row=[...document.querySelectorAll<HTMLElement>('[data-assignment-task]')].find(li=>li.dataset.assignmentTask===reopened.current)?.querySelector<HTMLElement>('.pf-task-open');
  if(!row)return;
  if(!document.activeElement || document.activeElement===document.body)row.focus();
  reopened.current='';
 },[c.route.task,loading,filtered.length]);
 return <section id="flow-tasks" className="pf-tasks" aria-label="流程任務列表" tabIndex={-1}>
  <header><h3>任務</h3><div className="pf-actions" aria-label="任務範圍">{[false,true].map(value=><Button key={String(value)} aria-pressed={all===value} onClick={()=>onScope(value)}>{value ? '全部任務' : '此節點'}</Button>)}</div></header>
  <div className="pf-filters" aria-label="任務篩選">{([['mine','我的'],['unassigned','未指派'],['overdue','逾期']] as const).map(([key,label])=><Button key={key} aria-pressed={filters[key]} onClick={()=>c.go(withTaskFilter(c.route,key,!filters[key]),true)}>{label}</Button>)}<span role="status">{incomplete ? `${filtered.length} 項已載入，來源未完整` : `${filtered.length} 項符合`}</span></div>
  {incomplete && <p role="status">任務來源暫不可用，請重試明細後再確認完整清單。</p>}
  {loading && <div aria-label="任務載入中" aria-busy="true"><Skeleton lines={3} height="3.5rem"/></div>}
  <ul className="pf-task-list">{filtered.map(row=>{const plan=row.task ? productionPlanFacts(row.task,row.nodeKey,nodes.find(n=>n.key===row.nodeKey)?.production) : null;return <li key={row.id} data-assignment-task={row.id}>
   <div className="pf-task-line"><button className="pf-task-open" onClick={()=>c.go({...c.route,tab:c.route.tab==='overview' ? 'overview' : 'flow',section:all ? 'all-tasks' : undefined,node:row.task ? row.nodeKey : nodes.find(n=>n.key===row.nodeKey)?.legacy?.id,task:row.id,task_source:undefined})}><strong>{plan ? '依計畫數量完成' : row.title}</strong><span>{row.owner} · {row.status} · {row.deadline?.slice(0,10) || '未排期限'}{overdueTask(row.deadline,row.done,c.w.as_of) && <Badge tone="critical">逾期</Badge>}</span><small>{plan && '生產計畫 · '}{nodes.find(n=>n.key===row.nodeKey)?.label} · {row.source}</small></button>
    {row.task && <FlowAction allowed={!busy && row.task.can.assign} reason={busy ? reason : '需有此任務的指派權限。'} onClick={()=>{setAssigning(assigning===row.id ? '' : row.id)}}>{row.ownerId ? '改派' : '指派'}</FlowAction>}
   </div>
   {assigning===row.id && details[row.nodeKey] && <TaskPersonPicker key={row.id} taskId={row.id} detail={details[row.nodeKey]} busy={busy} error={error} mutate={mutate} onClose={()=>setAssigning('')}/>}
   {row.id===seed?.id ? evidence : plan && <ProductionPlanFacts plan={plan}/>}
  </li>})}</ul>
  {!loading && !incomplete && !filtered.length && <p className="pf-empty">{rows.length ? '沒有符合篩選條件的任務。' : '尚無任務'}</p>}
  {!seed && evidence}
  {children}
  {selectedRow?.task && <AssignmentTaskInspector key={selectedRow.id} assignment={selectedRow.task} people={details[selectedRow.nodeKey]?.assignable_people} plan={taskPlan} nodeLabel={nodes.find(n=>n.key===selectedRow.nodeKey)?.label || ''} busy={busy} reason={reason} mutate={m=>mutate(m)} nodeKey={selectedRow.nodeKey} onClose={()=>c.go({...c.route,task:undefined})}/>}
  {c.route.task && !localTask && !selectedRow && !loading && nodes.some(n=>n.assignment) && <p role="alert">找不到此 Lark 任務，可能已移除或不在可見範圍。</p>}
 </section>;
}
