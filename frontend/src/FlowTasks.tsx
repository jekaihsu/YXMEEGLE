import {useEffect,useState,type MutableRefObject,type ReactNode} from 'react';
import {TriangleAlert} from 'lucide-react';
import {Badge,Button,Skeleton} from './design';
import {isProjectLead,nameOf,type Ctx} from './appCommon';
import type {Project} from './types';
import type {NodeAssignmentDetail} from './nodeAssignmentApi';
import {flowTaskTarget} from './flowModel';
import {taskFilters,withTaskFilter} from './projectRoutes';
import {DetailsMenu} from './design/DetailsMenu';
import {executionAllowed,executionReason} from './ProjectExecution';
import {FlowAction} from './FlowActions';
import {AssignDrawer} from './AssignDrawer';
import {AssignmentTaskInspector} from './AssignmentTaskInspector';
import {isProductionSeedTask,productionPlanFacts} from './productionPlan';
import {ProductionPlanFacts} from './FlowEvidence';
import {sharedBlockerReasons,STAGE_FILTERS,STAGE_FILTER_LABELS,activeFilters,blockedKnown,groupTasks,type StageContext,type TaskGroup,type TaskView} from './stageModel';
import {prefetchNodeAssignmentDetail,type useNodeAssignments} from './useNodeAssignments';
import {assignRequests} from './assignRequests';

type Props={c:Ctx;p:Project;ctx:StageContext;details:Record<string,NodeAssignmentDetail>;assignments:ReturnType<typeof useNodeAssignments>;busy:boolean;reason:string;loading:boolean;incomplete:boolean;retryDetails:()=>void;evidence:ReactNode;emptyActions?:ReactNode;caseReasonShown?:boolean;reopened?:MutableRefObject<string>;children?:ReactNode};

function Executor({row}:{row:TaskView}){
 return row.flags.unassigned ? <span className="st-unassigned"><TriangleAlert size={14} aria-hidden="true"/>尚未指派</span> : <span>{row.owner}</span>;
}
export function FlowTasks({c,p,ctx,details,assignments,busy,reason,loading,incomplete,retryDetails,evidence,emptyActions,caseReasonShown,reopened,children}:Props){
 const filters=taskFilters(c.route),applied=activeFilters(filters),userId=c.s.user?.id||'';
 const hasFilters=(ctx.nodes.find(n=>n.key===ctx.selectedId)?.taskRows.length||0)>4||applied.length>0;
 const [assigning,setAssigning]=useState<{nodeKey:string;taskId:string}|null>(null);
 const [restore,setRestore]=useState('');
 const groups=groupTasks({ctx,filters,userId,today:c.w.as_of,loaded:key=>!!details[key]||!ctx.nodes.find(n=>n.key===key)?.assignment});
 const selected=groups.selected,selectedId=ctx.selectedId;
 const sopTask=c.route.task_source==='sop_local';
 const localTask=sopTask||p.nodes.some(n=>n.tasks.some(t=>t.id===c.route.task));
 const everything=ctx.nodes.flatMap(n=>n.taskRows).filter(row=>row.source!=='SOP 任務');
 const targetRow=sopTask?undefined:everything.find(r=>r.id===c.route.task&&r.task);
 const seed=selected?.matching.find(row=>row.task&&isProductionSeedTask(row.task,selectedId));
 const taskPlan=targetRow?.task?productionPlanFacts(targetRow.task,targetRow.nodeKey,ctx.nodes.find(n=>n.key===targetRow.nodeKey)?.production):null;
 const open=(nodeKey:string,taskId:string)=>setAssigning({nodeKey,taskId});
 useEffect(()=>{if(!restore||assigning)return;const row=document.querySelector(`[data-assignment-task="${restore}"]`);const el=row?.querySelector<HTMLElement>('.pf-task-line button:not(.pf-task-open)')||row?.querySelector<HTMLElement>('.pf-task-open');if(el){el.focus();setRestore('')}});
 useEffect(()=>assignRequests.subscribe((nodeKey,taskId)=>{if(nodeKey===selectedId||details[nodeKey])open(nodeKey,taskId)}),[selectedId,details]);
 useEffect(()=>{
  if(c.route.task||loading||!reopened?.current)return;
  const row=[...document.querySelectorAll<HTMLElement>('[data-assignment-task]')].find(li=>li.dataset.assignmentTask===reopened.current)?.querySelector<HTMLElement>('.pf-task-open');
  if(!document.activeElement||document.activeElement===document.body)(row||document.getElementById('flow-tasks'))?.focus();
  reopened.current='';
 },[c.route.task,loading,selected?.matching.length]);
 const filterRoute=(key:typeof STAGE_FILTERS[number])=>c.go(withTaskFilter(c.route,key,!filters[key]),true);
 const clear=()=>c.go({...c.route,task_filters:undefined},true);
 const assignButton=(row:TaskView)=>!row.ownerId&&row.task?.can.assign&&<FlowAction allowed={!busy&&row.task.can.assign} reason={busy?reason:'你可查看此任務，但目前無指派權限。'} onClick={()=>open(row.nodeKey,row.id)}>指派</FlowAction>;
 const caseReason=!executionAllowed(p,c.w)?executionReason(p):p.status==='paused'?'案件暫停中':'';
 const sharedReasons=sharedBlockerReasons(selected?.rows||[]);
 const rowView=(row:TaskView,group:TaskGroup)=>{
  const rowReasons=row.flags.blocker.state==='blocked'?row.flags.blocker.reasons.filter(r=>!sharedReasons.includes(r)&&(!caseReason||(!r.includes(caseReason)&&!caseReason.includes(r)))):[];
  const plan=row.task?productionPlanFacts(row.task,row.nodeKey,group.node.production):null;
  return <li key={row.id} data-assignment-task={row.id} className="st-row">
   <div className="pf-task-line"><button className="pf-task-open" onClick={()=>c.go({...c.route,...(row.source==='SOP 任務'?flowTaskTarget(row):{node:row.task?row.nodeKey:group.node.legacy?.id,task:row.id,task_source:undefined}),tab:c.route.tab==='overview'?'overview':'flow'})}><strong>{row.title}</strong>
    <span className="st-meta"><Badge>{row.statusText}</Badge><Executor row={row}/><span>{row.deadline?.slice(0,10)||'未排期限'}</span>{row.flags.overdue&&<Badge>逾期</Badge>}</span>
    {rowReasons.length>0&&<small className="st-task-blocker">{rowReasons[0]}</small>}</button>
    {assignButton(row)}{!row.ownerId&&row.source==='SOP 任務'&&row.sopTask.allowedActions.includes('edit')&&<Button onClick={()=>c.go({...c.route,...flowTaskTarget(row),tab:c.route.tab==='overview'?'overview':'flow'})}>指派</Button>}</div>
   {row.id===seed?.id?evidence:plan&&<ProductionPlanFacts plan={plan}/>}
  </li>;
 };
 const pinned=selected&&targetRow&&!selected.matching.some(r=>r.id===targetRow.id)&&selected.rows.find(r=>r.id===targetRow.id);
 const shown=selected?[...selected.matching,...(pinned?[pinned]:[])]:[];
 const drawerNode=assigning?ctx.nodes.find(n=>n.key===assigning.nodeKey):undefined;
 const drawerDetail=assigning?details[assigning.nodeKey]:undefined;
 const drawerTask=drawerDetail?.tasks.find(t=>t.id===assigning?.taskId);
 return <section id="flow-tasks" className="pf-tasks st-tasks" aria-label="流程任務列表" tabIndex={-1}>
  <header><h3>本階段任務</h3>{!!selected?.total&&<span className="st-count" role="status">{incomplete?`${selected.rows.length} 項已載入，來源未完整`:`已完成 ${selected.done} / ${selected.total} 項`}</span>}</header>
  {!emptyActions&&!(caseReasonShown&&!executionAllowed(p,c.w))&&c.route.tab!=='overview'&&(!executionAllowed(p,c.w)||p.status==='paused')&&<p className="st-note" role="status">{p.status==='paused'?`案件暫停中，等待${p.pm_id?nameOf(c.w,p.pm_id):'PM'}處理。`:executionReason(p)}</p>}
  {sharedReasons.filter(r=>!caseReason||(!r.includes(caseReason)&&!caseReason.includes(r))).map(reason=><p key={reason} className="st-note" role="status">{reason}</p>)}
  {selected&&selected.loaded&&!incomplete&&selected.rows.length!==selected.total&&<p className="st-note" role="status">列表載入 {selected.rows.length} 項，與節點總數 {selected.total} 項不一致，請重新整理後再確認。</p>}
  {hasFilters&&<div className="pf-filters" role="group" aria-label="任務篩選"><Button aria-pressed={applied.length===0} onClick={clear}>全部</Button><Button aria-pressed={filters.mine} onClick={()=>filterRoute('mine')}>我的任務</Button><DetailsMenu className="st-filter-menu" label="篩選"><div>{STAGE_FILTERS.filter(k=>k!=='mine').map(key=><Button key={key} aria-pressed={filters[key]} onClick={()=>filterRoute(key)}>{STAGE_FILTER_LABELS[key]}</Button>)}</div></DetailsMenu></div>}
  {applied.length>0&&<p className="st-applied">已套用條件（需同時符合）：{applied.map(k=>STAGE_FILTER_LABELS[k]).join(' ＋ ')}<Button variant="plain" onClick={clear}>清除篩選</Button></p>}
  {filters.blocked&&selected&&!blockedKnown(selected.rows)&&<p className="st-note" role="status">此來源未提供任務阻礙資訊，無法判定哪些任務受阻。</p>}
  {incomplete&&<p role="alert">任務來源暫不可用，請重試明細後再確認完整清單。<Button onClick={retryDetails}>重試任務明細</Button></p>}
  {loading&&<div aria-label="任務載入中" aria-busy="true"><Skeleton lines={3} height="3.5rem"/></div>}
  <ul className="pf-task-list">{shown.map(row=>rowView(row,selected!))}</ul>
  {!loading&&!incomplete&&selected&&selected.loaded&&!shown.length&&<div className="pf-empty">{selected.rows.length?'沒有符合條件的任務':`此階段尚無任務${!isProjectLead(c.s,p)&&p.pm_id?' · PM：'+nameOf(c.w,p.pm_id):''}`}{selected.rows.length>0&&<Button variant="plain" onClick={clear}>清除篩選</Button>}{!selected.rows.length&&emptyActions}</div>}
  {targetRow&&!ctx.currentIds.includes(targetRow.nodeKey)&&ctx.currentIds.length>0&&<p className="st-note" role="status">此任務屬於「{ctx.nodes.find(n=>n.key===targetRow.nodeKey)?.label}」階段，不是目前階段「{ctx.nodes.find(n=>n.key===ctx.currentIds[0])?.label}」；開啟連結不會變更活動階段。</p>}
  {pinned&&<p className="st-note" role="status">這項任務不符合目前的篩選條件，因連結指向它而保留顯示。</p>}
  {!seed&&evidence}
  {children}
  {targetRow?.task&&<AssignmentTaskInspector key={targetRow.id} assignment={targetRow.task} people={details[targetRow.nodeKey]?.assignable_people} plan={taskPlan} nodeLabel={ctx.nodes.find(n=>n.key===targetRow.nodeKey)?.label||''} busy={busy} reason={reason} mutate={m=>assignments.mutate(m)} nodeKey={targetRow.nodeKey} onClose={()=>c.go({...c.route,task:undefined})}/>}
  {c.route.task&&!localTask&&!targetRow&&!loading&&ctx.nodes.some(n=>n.assignment)&&<p role="alert">找不到此 Lark 任務，可能已移除、無權限或不在可見範圍。<Button variant="plain" onClick={()=>c.go({...c.route,task:undefined})}>返回節點任務</Button></p>}
  {assigning&&drawerNode&&<AssignDrawer key={`${assigning.nodeKey}:${assigning.taskId}`} task={drawerTask} nodeKey={assigning.nodeKey} nodeLabel={drawerNode.label} caseLabel={`${p.code} ${p.name}`} people={drawerDetail?.assignable_people||[]}
   unavailableReason={assignments.state.kind==='error'?'節點來源更新失敗，請重新整理後再試。':assignments.state.kind==='ready'&&assignments.state.data.stale?'資料已過期，請重新整理後再試。':!drawerDetail?.writes_enabled?drawerDetail?.writes_disabled_reason||'節點修改尚未開放。':''}
   mutate={assignments.mutate} retry={assignments.retryMutation} refresh={()=>void assignments.reload()}
   verify={async()=>{const detail=await prefetchNodeAssignmentDetail(p.id,assigning.nodeKey,undefined,true);void assignments.reload();return detail.tasks.find(t=>t.id===assigning.taskId)}}
   onClose={()=>{setRestore(assigning.taskId);setAssigning(null)}}/>}
 </section>;
}
