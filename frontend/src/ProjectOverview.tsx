import {useCaseFlowModel} from './useCaseFlowModel';
import {caseProgressStatus,sourceStatusPending} from './stageModel';
import {lifecycleGate} from './sourceLifecycle';
import type {ReactNode} from 'react';
import type {useSopTasks} from './useSopTasks';
import {localCase} from './nodeWorkbenchModel';
import {CalendarDays, Clock3, Flag} from 'lucide-react';
import {flowTaskTarget} from './flowModel';
import {type OverviewTarget} from './projectOverviewModel';
import {executionAllowed,executionReason} from './ProjectExecution';
import type {useNodeAssignments} from './useNodeAssignments';
import {Avatar} from './AppShell';
import {CaseSummary} from './CaseSummary';
import {FlowDiagram} from './FlowDiagram';
import {Button} from './design';
import {assignRequests} from './assignRequests';
import {resolveStages,stageNextStep,sharedBlockerReasons,taskView,type NextStep} from './stageModel';
import {isProjectLead,nameOf,type Ctx} from './appCommon';
import type {Project} from './types';
import './ProjectFlow.css';
import './ProjectOverview.css';

const shortDate=(value:unknown)=>typeof value==='string' && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0,10) : '未設定';
export function ProjectOverview({c,p,assignments,selectedKey,sopTasks,workbench}:{c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>;selectedKey:string;sopTasks:ReturnType<typeof useSopTasks>;workbench:()=>ReactNode}){
 const {list,merged,model}=useCaseFlowModel(c,p,assignments,sopTasks,selectedKey,true);
 const unavailable=assignments.state.kind==='loading' || assignments.state.kind==='error';
 const destination=(target:OverviewTarget)=>({...target,...(target.tab==='flow'?{tab:'overview'}:{})});
 const go=(target:OverviewTarget)=>c.go({view:'project',project:p.id,...destination(target)});
 const stage=resolveStages({nodes:model.nodes,list,requested:c.route.node?selectedKey:undefined});
 const execution={allowed:executionAllowed(p,c.w),reason:executionReason(p)};
 const fresh=!!list&&list.writes_enabled&&!list.stale&&assignments.state.kind==='ready' || !list&&!unavailable;
 const step=stageNextStep({caseStatus:caseProgressStatus(p),ctx:stage,list,today:c.w.as_of,fresh,block:sourceStatusPending(p)?{kind:'source',reason:lifecycleGate(p)||'來源案件狀態待核對'}:caseProgressStatus(p)==='paused'?{kind:'paused',reason:`案件暫停中，等待${p.pm_id?nameOf(c.w,p.pm_id):'PM'}處理。`}:execution.allowed?undefined:{kind:p.execution_system==='meegle'?'meegle':!p.execution_system||p.execution_system==='pending'?'ownership':'execution',reason:execution.reason}});
 const current=stage.nodes.find(n=>n.key===stage.currentIds[0]);
 const shared=current?sharedBlockerReasons(current.taskRows.map(row=>taskView(row,current,c.w.as_of))):[];
 const emptyBlocked=stage.currentSelected&&!localCase(p)&&current&&!current.taskRows.length&&!execution.allowed&&isProjectLead(c.s,p);
 // The displayed task panel owns the case banner even when it is not the current stage.
 const selected=stage.nodes.find(n=>n.key===stage.selectedId);
 const summaryStep=!!selected?.taskRows.length&&'reasons' in step&&(!execution.allowed||p.status==='paused')?{...step,reasons:[]}:emptyBlocked&&'reasons' in step?{...step,reasons:step.reasons.filter(reason=>reason!==execution.reason)}:stage.currentSelected&&step.kind==='view'&&shared.includes(step.reason)?{...step,reason:''}:step;
 const executors=[...new Map(model.nodes.filter(n=>stage.currentIds.includes(n.key)||!!n.legacy?.started_at||!!n.assignment?.started_at||['進行中','待審核','已完成'].includes(n.state)||n.taskRows.some(t=>['in_progress','completed','進行中','已完成'].includes(t.status))).flatMap(n=>n.taskRows).filter(t=>t.ownerId&&t.ownerId!==p.pm_id&&t.ownerId!==p.nodes.find(n=>n.key==='field')?.supervisor_id).map(t=>[t.ownerId,t.owner])).values()];
 const openStep=(next:NextStep)=>{if(next.kind==='action'&&(!next.taskId||next.needs==='approve')){c.go({view:'project',project:p.id,tab:'flow',node:next.nodeKey});return}const sop=(next.kind==='action'||next.kind==='view')&&model.nodes.flatMap(n=>n.taskRows).find(r=>r.id===next.taskId&&r.source==='SOP 任務');if(sop){go({...flowTaskTarget(sop),tab:'overview'});return}if(next.kind==='action'&&next.needs==='assign'&&next.taskId){assignRequests.request(next.nodeKey,next.taskId);go({tab:'overview',node:next.nodeKey});return}if(next.kind==='action'||next.kind==='view')go({tab:'overview',node:next.nodeKey,task:next.taskId})};
 const localField=p.nodes.find(node=>node.key==='field');
 const pm=c.w.users.find(user=>user.id===p.pm_id),supervisor=c.w.users.find(user=>user.id===localField?.supervisor_id);
 const localNode=('data' in sopTasks.state?sopTasks.state.data?.localNodes:undefined)?.find(n=>n.key===current?.key);
 const canRecommend=!!current&&stage.currentKnown&&!stage.finished&&caseProgressStatus(p)!=='completed'&&caseProgressStatus(p)!=='paused'&&!sourceStatusPending(p)&&execution.allowed&&fresh;
 const canOwner=canRecommend&&!current.owners.length&&(localNode?.can.assign||list?.can[current.key]?.assign||list?.can[current.key]?.claim||assignments.state.kind==='disabled'&&isProjectLead(c.s,p));
 const canCreate=canRecommend&&!!current.owners.length&&current.tasks.total===0&&!current.taskRows.length&&!!(current.assignment?merged?.node_details?.[current.key]:current.legacy||localNode)&&(localNode?.can.create_task&&sopTasks.state.kind==='ready'&&sopTasks.state.data?.allowed.manage||list?.can[current.key]?.create_task||assignments.state.kind==='disabled'&&isProjectLead(c.s,p));
 const claimOnly=canOwner&&!localNode?.can.assign&&!list?.can[current.key]?.assign&&!!list?.can[current.key]?.claim;
 const recommendation=canOwner?(claimOnly?'認領節點':'指派負責人'):canCreate?'新增任務':'';
 const openRecommendation=()=>c.go({view:'project',project:p.id,tab:canOwner&&!current?.assignment&&!localNode?'people':'flow',node:current?.key,section:claimOnly?'node-claim':canOwner?'node-assign':'add-task'});
 return <div className="project-overview">
  <div className="po-main">
   <section className="po-card po-next-action" aria-label="下一步"><h2>下一步</h2>{recommendation?<><h3>{recommendation}</h3><p>{current?.label} · {canOwner?'尚未指派負責人':'此階段尚無任務'}</p><Button variant="primary" onClick={openRecommendation}>前往{recommendation}</Button></>:summaryStep.kind==='action'||summaryStep.kind==='view'?<><h3>{summaryStep.title}</h3><p>{summaryStep.reason}</p><Button variant="primary" onClick={()=>openStep(summaryStep)}>{summaryStep.button}</Button></>:<><h3>目前沒有可執行的下一步</h3>{summaryStep.kind==='none'&&caseProgressStatus(p)==='paused'&&summaryStep.reasons[0]&&<p>{summaryStep.reasons[0]}</p>}<p>先查看目前階段、負責人與待辦任務。</p><Button variant="primary" onClick={()=>c.go({view:'project',project:p.id,tab:'flow',node:stage.currentIds[0]})}>查看流程與任務</Button></>}{sourceStatusPending(p)&&<p className="po-source-note">來源與工作台狀態不同。<Button variant="plain" onClick={()=>c.go({view:'project',project:p.id,tab:'data',section:'basic'})}>查看狀態差異</Button></p>}</section>
   <FlowDiagram compact stageNavigation currentIds={stage.currentIds} nodes={model.nodes} overall={model.overall} selected={stage.selectedId} loading={assignments.state.kind==='loading'} onSelect={node=>c.go({view:'project',project:p.id,tab:'overview',node})}/>
   <div className="po-current-summary"><CaseSummary showNext={false} onRetry={()=>void assignments.reload()} ctx={stage} step={summaryStep} loading={assignments.state.kind==='loading'} error={assignments.state.kind==='error'?assignments.state.message:''} onStep={openStep} onCurrent={()=>go({tab:'overview',node:stage.currentIds[0]})}/></div>
   {workbench()}
  </div>
  <aside className="po-sidebar" aria-label="案件摘要資料">
   {(new Set([p.planned_start_date,p.planned_end_date,p.original_due_date].filter(Boolean).map(v=>String(v).slice(0,10))).size>=2) && <section className="po-card po-dates"><h2>關鍵日期</h2><dl>{p.planned_start_date && <div><dt><Flag size={17}/>預計開工</dt><dd>{shortDate(p.planned_start_date)}</dd></div>}{p.planned_end_date && <div><dt><CalendarDays size={17}/>預計完工</dt><dd>{shortDate(p.planned_end_date)}</dd></div>}{p.original_due_date && <div><dt><Clock3 size={17}/>合約期限</dt><dd>{shortDate(p.original_due_date)}</dd></div>}</dl></section>}
   <section className="po-card po-team"><h2>負責人與團隊</h2><dl><div><dt>PM</dt><dd className="po-person"><Avatar small user={pm}/>{p.pm_id ? nameOf(c.w,p.pm_id) : '未指派'}</dd></div><div><dt>組別主管</dt><dd className="po-person"><Avatar small user={supervisor}/>{supervisor?.name || '未指派'}</dd></div>{executors.length>0&&<div><dt>執行人</dt><dd className="po-executors">{executors.map(name=><span key={name}>{name}</span>)}</dd></div>}</dl></section>

  </aside>
 </div>;
}
