import {ReportLinkReview} from './ReportLinkReview';
import {withLocalChecklist,buildNodeWorkbench,localCase} from './nodeWorkbenchModel';
import {LocalNodeActions} from './LocalNodeActions';
import {CaseSopStart} from './CaseSopStart';
import {ReportLinkSummary} from './ReportLinkSummary';
import {NODE_NAMES} from './workflowLabels';
import {taipeiTime} from './taipeiTime';
import {elapsed,nameOf,safeUrl} from './appCommon';
import {createPortal} from 'react-dom';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Button,Skeleton} from './design';
import {useNodeAssignments} from './useNodeAssignments';
import {useProjectProgress} from './useProjectProgress';
import {useStartSop} from './useStartSop';
import {SopControls} from './StartSopControls';
import {useFlowDetails} from './useFlowDetails';
import {buildFlowModel,needsViewerAction,productionKey,projectFlowRoute} from './flowModel';
import {withTaskScope} from './projectRoutes';
import {FlowDiagram,FlowPanelSkeleton} from './FlowDiagram';
import {FlowAction,FlowNodeActions} from './FlowActions';
import {FlowTasks} from './FlowTasks';
import {SopTasks,type SopImportTarget} from './SopTasks';
import {useSopTasks,canReadSop} from './useSopTasks';
import {FlowSchedule} from './FlowSchedule';
import {ProductionCard,ProductionPlanFacts} from './FlowEvidence';
import {isProductionSeedTask,productionPlanFacts,productionPlanGaps} from './productionPlan';
import {FlowSourceDetails} from './FlowSourceDetails';
import {NodeWorkItems} from './NodeWorkItems';
import {NextAction} from './DailyHome';
import {ProjectReadiness} from './ProjectReadiness';
import {progressHash} from './reports/progressView';
import ProgressDetail from './reports/ProgressDetail';
import type {ReportTarget} from './projectProgressView';
import type {ProgressReportRow} from './projectProgressApi';
import type {Ctx} from './appCommon';
import type {Project} from './types';
import './NodeAssignments.css';
import './StartSop.css';
import './ProjectFlow.css';
export function ProjectFlow({c,p,assignments,selectedKey,secondary,legacyActions,sopTasks:providedSop,inline=false}:{c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>;selectedKey:string;secondary:ReactNode;legacyActions:ReactNode;sopTasks?:ReturnType<typeof useSopTasks>;inline?:boolean}){
 const route=projectFlowRoute(c.route),enabled=!localCase(p)&&c.s.features?.node_assignment===true;
 const read=useProjectProgress(p.id);
 const ownSop=useSopTasks(p.id,c.s.workspace_id || '',!providedSop&&canReadSop(c.s.user));
 const sopTasks=providedSop||ownSop;
 const [sopImport,setSopImport]=useState<SopImportTarget>(null);
 const sop=useStartSop(p.id,enabled,assignments.reload);
 const list='data' in assignments.state ? assignments.state.data : undefined;
 const isLegacy=assignments.state.kind==='disabled';
 const all=route.allTasks || c.route.section==='all-tasks';
 const details=useFlowDetails(p.id,list,selectedKey,all || !!c.route.task,assignments.revision);
 const merged=list ? {...list,node_details:{...list.node_details,...Object.fromEntries(Object.entries(details.details).map(([key,d])=>[key,{tasks:d.tasks,assignable_people:d.assignable_people}]))}} : undefined;
 const flow=buildFlowModel({project:isLegacy ? p : {...p,nodes:[]},assignments:merged,progress:read.state.kind==='ready' ? read.state.data : undefined,today:c.w.as_of,users:c.w.users});
 const sopData='data' in sopTasks.state?sopTasks.state.data:undefined;
 const model={...flow,nodes:withLocalChecklist(flow.nodes,sopData,sopTasks.assignees)};
 const selected=model.nodes.find(n=>n.key===selectedKey) || model.nodes[0];
 const category=productionKey(selected.key),detail=details.details[selected.key];
 const loading=assignments.state.kind==='loading';
 const nodeBusy=!!list?.stale || assignments.refreshing || !!assignments.pending || assignments.state.kind!=='ready';
 const busy=nodeBusy || !list?.writes_enabled;
 const reason=!list?.writes_enabled ? list?.writes_disabled_reason || '節點修改尚未開放。' : assignments.state.kind==='error' ? '節點來源更新失敗，請重試。' : '正在更新節點資料，請稍候。';
 const workbench=buildNodeWorkbench({node:selected,sop:sopData,local:sopData?.localNodes?.find(n=>n.key===selected.key),can:detail?.can,users:c.w.users,busy:localCase(p)?sopTasks.state.kind!=='ready'||sopTasks.state.refreshing:nodeBusy,reason:localCase(p)?'':nodeBusy||!list?.writes_enabled?reason:''});
 const [reviewLinks,setReviewLinks]=useState(false);
 const [report,setReport]=useState<ProgressReportRow|null>(null);
 const keyboardMove=useRef(false);
 const selectedTaskNode=Object.values(details.details).find(d=>d.tasks.some(t=>t.id===c.route.task))?.node.key;
 useEffect(()=>{if(selectedTaskNode && selectedTaskNode!==selectedKey)c.go({...c.route,node:selectedTaskNode},true)},[selectedTaskNode,selectedKey]);
 useEffect(()=>{
  if(loading)return;
  if(keyboardMove.current){keyboardMove.current=false;return;}
  const id=c.route.section==='evidence' ? 'flow-evidence' : route.focus==='tasks' ? 'flow-tasks' : c.route.node ? 'flow-selected' : '';
  if(!id)return;const frame=requestAnimationFrame(()=>{const target=document.getElementById(id);if(id==='flow-evidence' && target instanceof HTMLDetailsElement)target.open=true;target?.scrollIntoView({block:'start',behavior:'auto'})});return()=>cancelAnimationFrame(frame);
 },[c.route.tab,c.route.node,c.route.section,loading]);
 const reports=(row?:ReportTarget)=>{location.hash=progressHash('#view=reports&tab=progress',{dept:row?.dept || 'field',week:row?.week || '',group:'',caseKey:'',q:row?.case_code || p.code})};
 const select=(node:string,keyboard=false)=>{keyboardMove.current=keyboard;c.go({...c.route,tab:inline ? 'overview' : keyboard ? c.route.tab : 'flow',node,task:undefined,task_source:undefined,focus:undefined},keyboard)};
 const localNode=p.nodes.find(n=>n.key===selected.key);
 const taskIncomplete=(!isLegacy && assignments.state.kind==='error' && !list) || (all ? Object.keys(details.errors).length>0 : !!details.errors[selected.key]);
 const seed=selected.taskRows.find(row=>row.task && isProductionSeedTask(row.task,selected.key));
 const plan=seed?.task ? productionPlanFacts(seed.task,selected.key,selected.production) : null;
 const taskLoading=loading || !isLegacy && !!list && (all ? list.nodes.some(n=>!details.details[n.key] && !details.errors[n.key]) : !!selected.assignment && !detail && !details.errors[selected.key]);
 const gapCount=category && selected.production ? productionPlanGaps(selected).length : selected.gaps.length;
 const evidence=<details id="flow-evidence" className="pf-evidence" key={selected.key} open><summary>工程證據與節點待補<span className="pf-evidence-state">{read.state.kind==='error' ? '讀取失敗，可重試' : read.state.kind==='loading' ? '讀取中' : gapCount ? `${gapCount} 項待核對` : '查看來源'}</span></summary><div>
    {read.state.kind!=='ready' && plan && <ProductionPlanFacts plan={plan}/>}
    {read.state.kind==='error' ? <div role="alert" className="pg-callout">工程證據讀取失敗。{read.state.message}{(read.canRefresh || read.canRetryRead) && <Button onClick={read.retry}>重試工程證據</Button>}</div>
     : read.state.kind==='loading' ? <div aria-label="工程證據載入中" aria-busy="true"><Skeleton height="12rem"/></div>
     : category ? <ProductionCard node={selected} category={category} data={read.state.data} plan={plan} stale={!!list?.stale || c.w.freshness?.datasets.sources.status==='stale'} onItems={()=>c.go({view:'project',project:p.id,tab:'items',node:selected.key})} onDetail={setReport} onReports={reports}/>
     : <div className="pg-callout"><h3>來源證據</h3>{read.state.data.stages.find(s=>s.key===(selected.key==='pricing' ? 'billing' : selected.key))?.evidence.map((e,i)=><p key={i}>{e.label} · {e.value}</p>)}</div>}
    {read.state.kind==='ready' && read.state.data.sources.reports_status!=='ok' && <p className="pg-callout">週報來源{read.state.data.sources.reports_status==='cold' ? '建立中' : read.state.data.sources.reports_status==='restricted' ? '權限不足' : '暫不可用'}<Button onClick={read.retry}>重試週報來源</Button></p>}
    {read.state.kind!=='ready' && !plan && selected.assignment?.evidence && <NodeWorkItems node={selected.assignment} projectId={p.id} onRetryEvidence={read.state.kind==='error' ? read.retry : undefined}/>}
    {!category && selected.gaps.filter(g=>g!==selected.quantity.reason).length>0 && <div className="pf-node-gaps"><h3>此節點待補</h3>{selected.gaps.filter(g=>g!==selected.quantity.reason).map((g,i)=><p key={i}>{g}</p>)}</div>}
   </div></details>;
 return <div id="flow-top" className="project-flow">
  {!inline && <div className="pf-toolbar"><span className="pf-source">{isLegacy ? '本地流程' : `Lark 節點與任務 · 讀取時間 ${list?.fetched_at ? taipeiTime(list.fetched_at) : '來源未提供'}`}{list?.stale && ' · 上次成功資料，待更新'}</span><div className="pf-toolbar-actions">{enabled && <SopControls sop={sop}/>}{!isLegacy && <FlowAction allowed={!assignments.refreshing} reason="正在更新節點與任務，請稍候。" onClick={()=>void assignments.reload()}>{assignments.refreshing ? '更新中…' : '更新節點與任務'}</FlowAction>}</div></div>}
  {assignments.state.kind==='error' && <div role="alert" className="pg-callout">節點來源讀取失敗。{assignments.state.message}<Button onClick={()=>void assignments.reload()}>重試節點來源</Button></div>}
  {!enabled&&!localCase(p)&&c.route.task&&c.route.task_source!=='sop_local'&&!p.nodes.some(n=>n.tasks.some(t=>t.id===c.route.task))&&<p role="alert">節點指派尚未開放，無法定位此 Lark 節點或任務。</p>}
  {assignments.notice && <p role="status">{assignments.notice}</p>}
  {assignments.pending && <p role="status">儲存中…</p>}
  {assignments.error && <div role="alert" className="pg-callout">{assignments.error.message}{['outcome_unknown','readback_mismatch','busy'].includes(assignments.error.code || '') && <Button onClick={()=>void assignments.retryMutation()}>重試同一操作</Button>}</div>}
  {!inline && <FlowDiagram compact selectionFollowsFocus nodes={model.nodes} overall={model.overall} selected={selected.key} loading={loading} onSelect={select}/>}
  {loading && <FlowPanelSkeleton/>}<section id="flow-selected" className="pf-panel glass--card nw-selected" aria-label={`${selected.label}節點明細`} tabIndex={-1}>
   <header><div className="pf-selected-heading"><h2>{selected.label}</h2><span className="pf-selected-state" role="status">{selected.state}</span></div><div className="pf-panel-tools">{safeUrl(p.source_url)&&<a className="button" href={p.source_url} target="_blank" rel="noreferrer">開啟案件來源</a>}{inline&&enabled&&<SopControls sop={sop}/>} {!enabled&&<CaseSopStart projectId={p.id} sop={sopTasks}/>}<FlowSchedule key={selected.key} project={p} node={selected} session={c.s} onPublished={()=>{void assignments.reload();read.reload()}}/>{list && <details className="pf-attention-menu"><summary>需要我處理</summary><div className="pf-attention" aria-label="需要我處理">{model.nodes.filter(n=>needsViewerAction(n,list,c.s.user?.id || '')).map(n=><Button key={n.key} onClick={()=>select(n.key)}>{n.label} · {n.state==='待審核' ? '待審核' : !n.owners.length ? '待認領' : '待處理'}</Button>)}</div></details>}</div></header>
   <dl className="pf-facts">{workbench.facts.map(fact=><div key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}{selected.assignment?.legacy_completion && <div><dt>舊案直接完成</dt><dd>{selected.assignment.legacy_completion.actor.name} · {taipeiTime(selected.assignment.legacy_completion.at)}<small>{selected.assignment.legacy_completion.reason}</small></dd></div>}</dl>
   {selected.assignment?.auto_done && <p className="pg-callout">自動判定 · {selected.assignment.auto_done.reason}</p>}
   {inline&&isLegacy&&!localCase(p)&&!workbench.local&&legacyActions}
   {workbench.local ? <LocalNodeActions workbench={workbench} sop={sopTasks} projectId={p.id}/> : detail ? <FlowNodeActions key={selected.key} detail={detail} busy={nodeBusy} reason={nodeBusy||!list?.writes_enabled?reason:''} error={assignments.error} mutate={assignments.mutate} registry={workbench.actions} /> : !isLegacy && !!selected.assignment && assignments.state.kind==='ready' && !details.errors[selected.key] ? <Skeleton height="3rem"/> : null}
   {!workbench.local && !isLegacy && !selected.assignment && <p className="pf-empty">尚無節點指派</p>}

   {Object.entries(details.errors).map(([key,error])=><p role="alert" key={key}>{model.nodes.find(n=>n.key===key)?.label}任務明細讀取失敗。{error}<Button onClick={details.retry}>重試任務明細</Button></p>)}
   {(!workbench.local || selected.taskRows.some(row=>row.source!=='SOP 任務')) && <FlowTasks c={c} p={p} nodes={model.nodes} selected={selected.key} details={details.details} all={all} onScope={value=>c.go(withTaskScope({...c.route,tab:inline?'overview':'flow'},value))} busy={busy} reason={reason} error={assignments.error} mutate={assignments.mutate} loading={taskLoading} incomplete={taskIncomplete} evidence={evidence}>{selected.assignment&&<SopTasks remote c={c} p={p} nodeKey={selected.key} sop={sopTasks} importing={sopImport} setImporting={setSopImport}/>}</FlowTasks>}
   {!selected.assignment&&<SopTasks c={c} p={p} nodeKey={selected.key} sop={sopTasks} importing={sopImport} setImporting={setSopImport}/>}
  </section>
  {!inline && p.nodes.length>0 && legacyActions && <details className="pf-secondary pf-legacy"><summary>範本與本地流程</summary>
   <label>本地節點<select aria-label="本地節點" value={selectedKey} onChange={e=>select(e.target.value)}>{p.nodes.map(n=><option key={n.id} value={n.key}>{NODE_NAMES[n.key] || n.name}</option>)}</select></label>{legacyActions}
  </details>}
  <details className="pf-secondary"><summary>節點說明與背景</summary>
   {isLegacy && <NextAction c={c} rows={p.nodes.flatMap(n=>n.tasks.map(t=>({p,n,t})))}/>}
   {(localNode?.guidance || localNode?.description) && <p>{localNode.guidance || localNode.description}</p>}
   <p>協作人員 {localNode?.collaborator_ids.map(id=>nameOf(c.w,id)).join('、') || '尚未設定'}</p>
   <p>經過 {elapsed(localNode?.started_at || selected.assignment?.started_at,c.w.as_of)} 天</p>
   <Button onClick={()=>c.go({...c.route,node:selectedKey,tab:'files'})}>開啟 作業資料與成果</Button>
  </details>
  <details className="pf-secondary"><summary>日報連結與核對</summary><ReportLinkSummary projectId={p.id} version={c.w.version} compact onReview={()=>setReviewLinks(true)}/>{reviewLinks&&<ReportLinkReview c={c} compact/>}</details>
  {secondary}
  {read.state.kind==='ready' && <FlowSourceDetails data={read.state.data}/>}
  <details className="pf-secondary"><summary>案件就緒條件</summary><ProjectReadiness w={c.w} p={p}/></details>
  {report && createPortal(<ProgressDetail caseKey={report.case_key} dept={report.dept} week={report.week} onClose={()=>setReport(null)}/>,document.body)}
 </div>;
}
