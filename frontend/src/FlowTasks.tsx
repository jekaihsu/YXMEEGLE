import {useEffect,useRef,useState,type MutableRefObject,type ReactNode} from 'react';
import {ChevronDown,ChevronRight,TriangleAlert} from 'lucide-react';
import {Badge,Button,Skeleton} from './design';
import type {Ctx} from './appCommon';
import type {Project} from './types';
import type {NodeAssignmentDetail} from './nodeAssignmentApi';
import {overdueTask} from './flowModel';
import {taskFilters,withTaskFilter} from './projectRoutes';
import {FlowAction} from './FlowActions';
import {AssignDrawer} from './AssignDrawer';
import {AssignmentTaskInspector} from './AssignmentTaskInspector';
import {isProductionSeedTask,productionPlanFacts} from './productionPlan';
import {ProductionPlanFacts} from './FlowEvidence';
import {STAGE_FILTERS,STAGE_FILTER_LABELS,activeFilters,blockedKnown,groupTasks,nodeStatusText,type StageContext,type TaskGroup,type TaskView} from './stageModel';
import {prefetchNodeAssignmentDetail,type useNodeAssignments} from './useNodeAssignments';
import {assignRequests} from './assignRequests';

type Props={c:Ctx;p:Project;ctx:StageContext;details:Record<string,NodeAssignmentDetail>;detailErrors:Record<string,string>;assignments:ReturnType<typeof useNodeAssignments>;busy:boolean;reason:string;loading:boolean;incomplete:boolean;retryDetails:()=>void;expanded:string[];setExpanded:(keys:string[])=>void;evidence:ReactNode;reopened?:MutableRefObject<string>;children?:ReactNode};

function Executor({row}:{row:TaskView}){
 return row.flags.unassigned ? <span className="st-unassigned"><TriangleAlert size={14} aria-hidden="true"/>尚未指派</span> : <span>{row.owner}</span>;
}
export function FlowTasks({c,p,ctx,details,detailErrors,assignments,busy,reason,loading,incomplete,retryDetails,expanded,setExpanded,evidence,reopened,children}:Props){
 const filters=taskFilters(c.route),applied=activeFilters(filters),userId=c.s.user?.id||'';
 const [assigning,setAssigning]=useState<{nodeKey:string;taskId:string}|null>(null);
 const trigger=useRef<HTMLElement|null>(null);
 const groups=groupTasks({ctx,filters,userId,today:c.w.as_of,loaded:key=>!!details[key]||!ctx.nodes.find(n=>n.key===key)?.assignment});
 const selected=groups.selected,selectedId=ctx.selectedId;
 const sopTask=c.route.task_source==='sop_local';
 const localTask=sopTask||p.nodes.some(n=>n.tasks.some(t=>t.id===c.route.task));
 const everything=ctx.nodes.flatMap(n=>n.taskRows).filter(row=>row.source!=='SOP 任務');
 const targetRow=sopTask?undefined:everything.find(r=>r.id===c.route.task&&r.task);
 const seed=selected?.matching.find(row=>row.task&&isProductionSeedTask(row.task,selectedId));
 const taskPlan=targetRow?.task?productionPlanFacts(targetRow.task,targetRow.nodeKey,ctx.nodes.find(n=>n.key===targetRow.nodeKey)?.production):null;
 const open=(nodeKey:string,taskId:string)=>{trigger.current=document.activeElement as HTMLElement|null;setAssigning({nodeKey,taskId})};
 useEffect(()=>assignRequests.subscribe((nodeKey,taskId)=>{if(nodeKey===selectedId||details[nodeKey])open(nodeKey,taskId)}),[selectedId,details]);
 useEffect(()=>{
  if(c.route.task||loading||!reopened?.current)return;
  const row=[...document.querySelectorAll<HTMLElement>('[data-assignment-task]')].find(li=>li.dataset.assignmentTask===reopened.current)?.querySelector<HTMLElement>('.pf-task-open');
  if(!document.activeElement||document.activeElement===document.body)(row||document.getElementById('flow-tasks'))?.focus();
  reopened.current='';
 },[c.route.task,loading,selected?.matching.length]);
 const filterRoute=(key:typeof STAGE_FILTERS[number])=>c.go(withTaskFilter(c.route,key,!filters[key]),true);
 const clear=()=>c.go({...c.route,task_filters:undefined},true);
 const assignButton=(row:TaskView)=>row.task&&<FlowAction allowed={!busy&&row.task.can.assign} reason={busy?reason:'你可查看此任務，但目前無指派權限。'} onClick={()=>open(row.nodeKey,row.id)}>{row.ownerId?'改派':'指派'}</FlowAction>;
 const rowView=(row:TaskView,group:TaskGroup)=>{
  const plan=row.task?productionPlanFacts(row.task,row.nodeKey,group.node.production):null;
  return <li key={row.id} data-assignment-task={row.id} className="st-row">
   <div className="pf-task-line"><button className="pf-task-open" onClick={()=>c.go({...c.route,tab:c.route.tab==='overview'?'overview':'flow',node:row.task?row.nodeKey:group.node.legacy?.id,task:row.id,task_source:undefined})}><strong>{plan?'依計畫數量完成':row.title}</strong>
    <span className="st-meta"><span>任務狀態：{row.statusText}</span><span>執行人：<Executor row={row}/></span><span>{row.deadline?.slice(0,10)||'未排期限'}</span>{row.flags.blocker.state==='blocked'&&<Badge tone="critical" icon={<TriangleAlert size={12} aria-hidden="true"/>}>受阻：{row.flags.blocker.reasons.join('、')}</Badge>}{overdueTask(row.deadline,row.done,c.w.as_of)&&<Badge tone="critical">逾期</Badge>}</span>
    <small>{plan&&'生產計畫 · '}{group.node.label} · {row.source}</small></button>
    {assignButton(row)}</div>
   {row.id===seed?.id?evidence:plan&&<ProductionPlanFacts plan={plan}/>}
  </li>;
 };
 const matchCount=selected?.matching.length??0;
 const pinned=selected&&targetRow&&!selected.matching.some(r=>r.id===targetRow.id)&&selected.rows.find(r=>r.id===targetRow.id);
 const shown=selected?[...selected.matching,...(pinned?[pinned]:[])]:[];
 const toggle=(key:string)=>setExpanded(expanded.includes(key)?expanded.filter(k=>k!==key):[...expanded,key]);
 const drawerNode=assigning?ctx.nodes.find(n=>n.key===assigning.nodeKey):undefined;
 const drawerDetail=assigning?details[assigning.nodeKey]:undefined;
 const drawerTask=drawerDetail?.tasks.find(t=>t.id===assigning?.taskId);
 return <section id="flow-tasks" className="pf-tasks st-tasks" aria-label="流程任務列表" tabIndex={-1}>
  <header><h3>{selected?`${selected.node.label}節點任務`:'節點任務'}</h3><span className="st-count" role="status">{incomplete?`${matchCount} 項已載入，來源未完整`:selected&&selected.loaded?`符合條件 ${matchCount} 項 · 節點共 ${selected.total} 項`:'載入任務中'}</span></header>
  <div className="pf-filters" role="group" aria-label="任務篩選"><Button aria-pressed={applied.length===0} onClick={clear}>全部</Button>{STAGE_FILTERS.map(key=><Button key={key} aria-pressed={filters[key]} onClick={()=>filterRoute(key)}>{STAGE_FILTER_LABELS[key]}</Button>)}</div>
  {applied.length>0&&<p className="st-applied">已套用條件（需同時符合）：{applied.map(k=>STAGE_FILTER_LABELS[k]).join(' ＋ ')}<Button variant="plain" onClick={clear}>清除篩選</Button></p>}
  {filters.blocked&&selected&&!blockedKnown(selected.rows)&&<p className="st-note" role="status">此來源未提供任務阻礙資訊，無法判定哪些任務受阻。</p>}
  {incomplete&&<p role="alert">任務來源暫不可用，請重試明細後再確認完整清單。<Button onClick={retryDetails}>重試任務明細</Button></p>}
  {loading&&<div aria-label="任務載入中" aria-busy="true"><Skeleton lines={3} height="3.5rem"/></div>}
  <ul className="pf-task-list">{shown.map(row=>rowView(row,selected!))}</ul>
  {!loading&&!incomplete&&selected&&selected.loaded&&!shown.length&&<p className="pf-empty">{selected.rows.length?'沒有符合條件的任務':'此節點尚無可顯示任務'}{selected.rows.length>0&&<Button variant="plain" onClick={clear}>清除篩選</Button>}</p>}
  {pinned&&<p className="st-note" role="status">這項任務不符合目前的篩選條件，因連結指向它而保留顯示。</p>}
  {!seed&&evidence}
  {children}
  {groups.others.length>0&&<div className="st-others"><h3>其他階段任務</h3>
   {groups.others.map(group=>{
    const key=group.node.key,isOpen=expanded.includes(key),err=detailErrors[key],current=ctx.currentIds.includes(key);
    return <section key={key} className="st-group" data-node={key}>
     <h4><button type="button" aria-expanded={isOpen} aria-controls={`st-group-${key}`} onClick={()=>toggle(key)}>{isOpen?<ChevronDown size={16} aria-hidden="true"/>:<ChevronRight size={16} aria-hidden="true"/>}<span>{group.node.label}</span><span className="st-group-meta">節點狀態：{nodeStatusText(group.node.state)} · {group.done} / {group.total} 已完成{current&&' · 目前階段'}</span></button></h4>
     {isOpen&&<div id={`st-group-${key}`}>
      {err?<p role="alert">{group.node.label}任務明細讀取失敗。{err}<Button onClick={retryDetails}>重試</Button></p>:!group.loaded?<div aria-busy="true"><Skeleton lines={2} height="3rem"/></div>
       :<><p className="st-note">符合條件 {group.matching.length} 項 · 節點共 {group.total} 項{ctx.currentIds.includes(key)?'':'；此為其他階段，僅供閱讀，不代表可跨階段操作'}</p><ul className="pf-task-list">{group.matching.map(row=>rowView(row,group))}</ul>{!group.matching.length&&<p className="pf-empty">{group.rows.length?'沒有符合條件的任務':'此節點尚無可顯示任務'}</p>}</>}
     </div>}
    </section>;
   })}</div>}
  {targetRow?.task&&<AssignmentTaskInspector key={targetRow.id} assignment={targetRow.task} people={details[targetRow.nodeKey]?.assignable_people} plan={taskPlan} nodeLabel={ctx.nodes.find(n=>n.key===targetRow.nodeKey)?.label||''} busy={busy} reason={reason} mutate={m=>assignments.mutate(m)} nodeKey={targetRow.nodeKey} onClose={()=>c.go({...c.route,task:undefined})}/>}
  {c.route.task&&!localTask&&!targetRow&&!loading&&ctx.nodes.some(n=>n.assignment)&&<p role="alert">找不到此 Lark 任務，可能已移除、無權限或不在可見範圍。<Button variant="plain" onClick={()=>c.go({...c.route,task:undefined})}>返回節點任務</Button></p>}
  {assigning&&drawerNode&&<AssignDrawer key={`${assigning.nodeKey}:${assigning.taskId}`} task={drawerTask} nodeKey={assigning.nodeKey} nodeLabel={drawerNode.label} caseLabel={`${p.code} ${p.name}`} people={drawerDetail?.assignable_people||[]}
   unavailableReason={assignments.state.kind==='error'?'節點來源更新失敗，請重新整理後再試。':assignments.state.kind==='ready'&&assignments.state.data.stale?'資料已過期，請重新整理後再試。':!drawerDetail?.writes_enabled?drawerDetail?.writes_disabled_reason||'節點修改尚未開放。':''}
   mutate={assignments.mutate} retry={assignments.retryMutation} refresh={()=>void assignments.reload()}
   verify={async()=>{const detail=await prefetchNodeAssignmentDetail(p.id,assigning.nodeKey,undefined,true);void assignments.reload();return detail.tasks.find(t=>t.id===assigning.taskId)}}
   onClose={()=>{const target=assigning;setAssigning(null);requestAnimationFrame(()=>{const t=trigger.current;if(t?.isConnected)t.focus();else document.querySelector<HTMLElement>(`[data-assignment-task="${target.taskId}"] button`)?.focus()})}}/>}
 </section>;
}
