import {useState} from 'react';
import {Badge,Button,Skeleton} from './design';
import type {Ctx} from './appCommon';
import type {Project} from './types';
import type {AssignmentMutation,NodeAssignmentDetail,NodeAssignmentError} from './nodeAssignmentApi';
import {filterFlowTasks,overdueTask,type FlowNode} from './flowModel';
import {FlowAction,TaskPersonPicker} from './FlowActions';
import {TaskInspector} from './ProjectDetail';
export function FlowTasks({c,p,nodes,selected,details,all,onScope,busy,reason,error,mutate,loading,incomplete}:{c:Ctx;p:Project;nodes:FlowNode[];selected:string;details:Record<string,NodeAssignmentDetail>;all:boolean;onScope:(all:boolean)=>void;busy:boolean;reason:string;error:NodeAssignmentError|null;mutate:(m:AssignmentMutation)=>Promise<boolean>;loading:boolean;incomplete:boolean}){
 const [filters,setFilters]=useState({mine:false,unassigned:false,overdue:false});
 const [assigning,setAssigning]=useState('');
 const rows=nodes.flatMap(n=>n.taskRows);
 const filtered=filterFlowTasks(rows,{...filters,node:all ? undefined : selected,userId:c.s.user?.id || '',today:c.w.as_of});
 const selectedRow=rows.find(r=>r.id===c.route.task && r.task);
 return <section id="flow-tasks" className="pf-tasks" aria-label="流程任務列表" tabIndex={-1}>
  <header><h3>任務</h3><div className="pf-actions" aria-label="任務範圍">{[false,true].map(value=><Button key={String(value)} aria-pressed={all===value} onClick={()=>onScope(value)}>{value ? '全部任務' : '此節點'}</Button>)}</div></header>
  <div className="pf-filters" aria-label="任務篩選">{([['mine','我的'],['unassigned','未指派'],['overdue','逾期']] as const).map(([key,label])=><Button key={key} aria-pressed={filters[key]} onClick={()=>setFilters(f=>({...f,[key]:!f[key]}))}>{label}</Button>)}<span role="status">{incomplete ? `${filtered.length} 項已載入，來源未完整` : `${filtered.length} 項符合`}</span></div>
  {incomplete && <p role="status">任務來源暫不可用，請重試明細後再確認完整清單。</p>}
  {loading && <div aria-label="任務載入中" aria-busy="true"><Skeleton lines={3} height="3.5rem"/></div>}
  <ul className="pf-task-list">{filtered.map(row=><li key={row.id} data-assignment-task={row.id}>
   <div className="pf-task-line"><button className="pf-task-open" onClick={()=>c.go({...c.route,tab:'flow',section:all ? 'all-tasks' : undefined,node:row.task ? row.nodeKey : nodes.find(n=>n.key===row.nodeKey)?.legacy?.id,task:row.id})}><strong>{row.title}</strong><span>{row.owner} · {row.status} · {row.deadline?.slice(0,10) || '未排期限'}{overdueTask(row.deadline,row.done,c.w.as_of) && <Badge tone="critical">逾期</Badge>}</span><small>{nodes.find(n=>n.key===row.nodeKey)?.label} · {row.source}</small></button>
    {row.task && <FlowAction allowed={!busy && row.task.can.assign} reason={busy ? reason : '需有此任務的指派權限。'} onClick={()=>{setAssigning(assigning===row.id ? '' : row.id)}}>{row.ownerId ? '改派' : '指派'}</FlowAction>}
   </div>
   {assigning===row.id && details[row.nodeKey] && <TaskPersonPicker key={row.id} taskId={row.id} detail={details[row.nodeKey]} busy={busy} error={error} mutate={mutate} onClose={()=>setAssigning('')}/>}
  </li>)}</ul>
  {!loading && !incomplete && !filtered.length && <p className="pf-empty">{rows.length ? '沒有符合篩選條件的任務。' : '尚無可見任務。新增具體工作後即可指派與追蹤。'}</p>}
  {selectedRow?.task && <TaskInspector key={selectedRow.id} c={c} assignment={selectedRow.task} nodeLabel={nodes.find(n=>n.key===selectedRow.nodeKey)?.label || ''} busy={busy} reason={reason} mutate={m=>mutate(m)} nodeKey={selectedRow.nodeKey} onClose={()=>c.go({...c.route,task:undefined})}/>}
  {c.route.task && !selectedRow && !loading && nodes.some(n=>n.assignment) && <p role="alert">找不到此 Lark 任務，可能已移除或不在可見範圍。</p>}
 </section>;
}
