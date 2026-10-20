import {NODE_NAMES} from './workflowLabels';
import {taipeiTime} from './taipeiTime';
import {elapsed,nameOf} from './appCommon';
import {createPortal} from 'react-dom';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Button,Skeleton} from './design';
import {useNodeAssignments} from './useNodeAssignments';
import {useProjectProgress} from './useProjectProgress';
import {useStartSop} from './useStartSop';
import {SopControls} from './StartSopControls';
import {useFlowDetails} from './useFlowDetails';
import {buildFlowModel,needsViewerAction,productionKey,projectFlowRoute} from './flowModel';
import {FlowDiagram,FlowPanelSkeleton} from './FlowDiagram';
import {FlowAction,FlowNodeActions} from './FlowActions';
import {FlowTasks} from './FlowTasks';
import {SopTasks,type SopImportTarget} from './SopTasks';
import {useSopTasks} from './useSopTasks';
import {isSopNode} from './sopTaskApi';
import {FlowSchedule} from './FlowSchedule';
import {ProductionCard} from './FlowEvidence';
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
export function ProjectFlow({c,p,assignments,selectedKey,secondary,legacyActions}:{c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>;selectedKey:string;secondary:ReactNode;legacyActions:ReactNode}){
 const route=projectFlowRoute(c.route),enabled=c.s.features?.node_assignment===true;
 const read=useProjectProgress(p.id);
 const sopTasks=useSopTasks(p.id,c.s.workspace_id || '');
 const [sopImport,setSopImport]=useState<SopImportTarget>(null);
 const sop=useStartSop(p.id,enabled,assignments.reload);
 const list='data' in assignments.state ? assignments.state.data : undefined;
 const isLegacy=assignments.state.kind==='disabled';
 const all=route.allTasks || c.route.section==='all-tasks';
 const details=useFlowDetails(p.id,list,selectedKey,all || !!c.route.task,assignments.revision);
 const merged=list ? {...list,node_details:{...list.node_details,...Object.fromEntries(Object.entries(details.details).map(([key,d])=>[key,{tasks:d.tasks,assignable_people:d.assignable_people}]))}} : undefined;
 const model=buildFlowModel({project:isLegacy ? p : {...p,nodes:[]},assignments:merged,progress:read.state.kind==='ready' ? read.state.data : undefined,today:c.w.as_of,users:c.w.users});
 const selected=model.nodes.find(n=>n.key===selectedKey) || model.nodes[0];
 const category=productionKey(selected.key),detail=details.details[selected.key];
 const loading=assignments.state.kind==='loading';
 const busy=assignments.refreshing || !!assignments.pending || assignments.state.kind!=='ready' || !list?.writes_enabled;
 const reason=!list?.writes_enabled ? list?.writes_disabled_reason || '節點修改尚未開放。' : assignments.state.kind==='error' ? '節點來源更新失敗，請重試。' : '正在更新節點資料，請稍候。';
 const [report,setReport]=useState<ProgressReportRow|null>(null);
 const keyboardMove=useRef(false);
 const selectedTaskNode=Object.values(details.details).find(d=>d.tasks.some(t=>t.id===c.route.task))?.node.key;
 useEffect(()=>{if(selectedTaskNode && selectedTaskNode!==selectedKey)c.go({...c.route,node:selectedTaskNode},true)},[selectedTaskNode,selectedKey]);
 useEffect(()=>{
  if(loading)return;
  if(keyboardMove.current){keyboardMove.current=false;return;}
  const id=route.focus==='top' ? 'project-page-top' : route.focus==='tasks' ? 'flow-tasks' : route.focus==='evidence' ? 'flow-evidence' : c.route.node ? 'flow-selected' : '';
  if(!id)return;const frame=requestAnimationFrame(()=>document.getElementById(id)?.scrollIntoView({block:'start',behavior:'auto'}));return()=>cancelAnimationFrame(frame);
 },[c.route.tab,c.route.node,loading]);
 const reports=(row?:ReportTarget)=>{location.hash=progressHash('#view=reports&tab=progress',{dept:row?.dept || 'field',week:row?.week || '',group:'',caseKey:'',q:row?.case_code || p.code})};
 const select=(node:string,keyboard=false)=>{keyboardMove.current=keyboard;c.go({...c.route,tab:keyboard ? c.route.tab : 'flow',node,task:undefined,task_source:undefined,focus:undefined},keyboard)};
 const sopAllowed=sopTasks.state.kind==='ready' ? sopTasks.state.data.allowed : undefined;
 const sopNode=isSopNode(selected.key) ? selected.key : undefined;
 const sopNodeAction=sopAllowed && sopNode ? <FlowAction allowed={sopAllowed.import} reason="需 SOP 匯入權限" onClick={()=>setSopImport(sopNode)}>匯入此節點任務</FlowAction> : null;
 const localNode=p.nodes.find(n=>n.key===selected.key);
 const managers=c.w.users.filter(u=>u.active!==false && u.role==='manager' && selected.departments.includes(u.department));
 const taskIncomplete=(!isLegacy && assignments.state.kind==='error' && !list) || (all ? Object.keys(details.errors).length>0 : !!details.errors[selected.key]);
 const taskLoading=!isLegacy && !!list && (all ? list.nodes.some(n=>!details.details[n.key] && !details.errors[n.key]) : !!selected.assignment && !detail && !details.errors[selected.key]);
 return <div id="flow-top" className="project-flow">
  <div className="pf-next">{isLegacy ? <NextAction c={c} rows={p.nodes.flatMap(n=>n.tasks.map(t=>({p,n,t})))}/> : <><strong>下一步</strong><span>{selected.state==='待審核' ? '待審核' : selected.owners.length ? '待處理' : '待認領'}</span>{list && <div className="pf-attention" aria-label="需要我處理">{model.nodes.filter(n=>needsViewerAction(n,list,c.s.user?.id || '')).map(n=><Button key={n.key} onClick={()=>select(n.key)}>{n.label} · {n.state==='待審核' ? '待審核' : !n.owners.length ? '待認領' : '待處理'}</Button>)}</div>}</>}</div>
  <div className="pf-source"><span>{isLegacy ? '本地流程' : `Lark 節點與任務 · 讀取時間 ${list?.fetched_at ? taipeiTime(list.fetched_at) : '來源未提供'}`}{list?.stale && ' · 上次成功資料，待更新'}</span>{enabled && <SopControls sop={sop}/>}{!isLegacy && <FlowAction allowed={!assignments.refreshing} reason="正在更新節點與任務，請稍候。" onClick={()=>void assignments.reload()}>{assignments.refreshing ? '更新中…' : '更新節點與任務'}</FlowAction>}</div>
  {assignments.state.kind==='error' && <div role="alert" className="pg-callout">節點來源讀取失敗。{assignments.state.message}<Button onClick={()=>void assignments.reload()}>重試節點來源</Button></div>}
  {assignments.notice && <p role="status">{assignments.notice}</p>}
  {assignments.pending && <p role="status">儲存中…</p>}
  {assignments.error && <div role="alert" className="pg-callout">{assignments.error.message}{['outcome_unknown','readback_mismatch','busy'].includes(assignments.error.code || '') && <Button onClick={()=>void assignments.retryMutation()}>重試同一操作</Button>}</div>}
  <FlowDiagram nodes={model.nodes} overall={model.overall} selected={selected.key} loading={loading} onSelect={select}/>
  {loading ? <FlowPanelSkeleton/> : <section id="flow-selected" className="pf-panel glass--card" aria-label={`${selected.label}節點明細`} tabIndex={-1}>
   <header><div><span className="pf-eyebrow">選定節點</span><h2>{selected.label}</h2></div><FlowSchedule key={selected.key} project={p} node={selected} session={c.s} onPublished={()=>{void assignments.reload();read.retry()}}/></header>
   <dl className="pf-facts"><div><dt>負責組別</dt><dd>{selected.departments.join('、') || (isLegacy ? '本地流程' : '來源未提供')}</dd></div><div><dt>組別主管</dt><dd>{managers.map(u=>u.name).join('、') || (selected.departments.length ? '未能對應到本組主管' : '主管未設定')}</dd></div><div><dt>指派主管</dt><dd>{selected.assignment?.assigned_by?.name || '來源未提供'}</dd></div><div><dt>節點最後期限</dt><dd>{selected.finalDeadline?.slice(0,10) || '未排定'}</dd></div></dl>
   {selected.assignment?.auto_done && <p className="pg-callout">自動判定 · {selected.assignment.auto_done.reason}</p>}
   {detail ? <FlowNodeActions key={selected.key} detail={detail} busy={busy} reason={reason} error={assignments.error} mutate={assignments.mutate} extra={sopNodeAction}/> : !isLegacy && !!selected.assignment && assignments.state.kind==='ready' && !details.errors[selected.key] ? <Skeleton height="3rem"/> : sopNodeAction && <div className="pf-node-actions"><div className="pf-actions">{sopNodeAction}</div></div>}
   {!isLegacy && !selected.assignment && <p className="pf-empty">尚無節點指派</p>}

   {Object.entries(details.errors).map(([key,error])=><p role="alert" key={key}>{model.nodes.find(n=>n.key===key)?.label}任務明細讀取失敗。{error}<Button onClick={details.retry}>重試任務明細</Button></p>)}
   <div id="flow-evidence" className="pf-evidence" tabIndex={-1}>
    {read.state.kind==='error' ? <div role="alert" className="pg-callout">工程證據讀取失敗。{read.state.message}<Button onClick={read.retry}>重試工程證據</Button></div>
     : read.state.kind==='loading' ? <div aria-label="工程證據載入中" aria-busy="true"><Skeleton height="12rem"/></div>
     : category ? <ProductionCard node={selected} category={category} data={read.state.data} onDetail={setReport} onReports={reports}/>
     : <div className="pg-callout"><h3>來源證據</h3>{read.state.data.stages.find(s=>s.key===(selected.key==='pricing' ? 'billing' : selected.key))?.evidence.map((e,i)=><p key={i}>{e.label} · {e.value}</p>)}</div>}
    {read.state.kind==='ready' && read.state.data.sources.reports_status!=='ok' && <p className="pg-callout">週報來源{read.state.data.sources.reports_status==='cold' ? '建立中' : read.state.data.sources.reports_status==='restricted' ? '權限不足' : '暫不可用'}<Button onClick={read.retry}>重試週報來源</Button></p>}
    {read.state.kind!=='ready' && selected.assignment?.evidence && <NodeWorkItems node={selected.assignment} projectId={p.id} onRetryEvidence={read.state.kind==='error' ? read.retry : undefined}/>}
    {selected.gaps.filter(g=>g!==selected.quantity.reason).length>0 && <div className="pf-node-gaps"><h3>此節點待補</h3>{selected.gaps.filter(g=>g!==selected.quantity.reason).map((g,i)=><p key={i}>{g}</p>)}</div>}
   </div>
   <SopTasks c={c} p={p} nodeKey={selected.key} sop={sopTasks} importing={sopImport} setImporting={setSopImport}/>
   <FlowTasks c={c} p={p} nodes={model.nodes} selected={selected.key} details={details.details} all={all} onScope={value=>c.go({...c.route,tab:'flow',section:value ? 'all-tasks' : undefined})} busy={busy} reason={reason} error={assignments.error} mutate={assignments.mutate} loading={taskLoading} incomplete={taskIncomplete}/>
  </section>}
  {p.nodes.length>0 && <details className="pf-secondary pf-legacy"><summary>範本與本地流程</summary>
   <label>本地節點<select aria-label="本地節點" value={selectedKey} onChange={e=>select(e.target.value)}>{p.nodes.map(n=><option key={n.id} value={n.key}>{NODE_NAMES[n.key] || n.name}</option>)}</select></label>{legacyActions}
  </details>}
  <details className="pf-secondary"><summary>節點資訊</summary>
   <p>協作人員 {localNode?.collaborator_ids.map(id=>nameOf(c.w,id)).join('、') || '尚未設定'}</p>
   <p>經過 {elapsed(localNode?.started_at || selected.assignment?.started_at,c.w.as_of)} 天</p>
   <Button onClick={()=>c.go({...c.route,node:selectedKey,tab:'files'})}>開啟 作業資料與成果</Button>
  </details>
  {secondary}
  {read.state.kind==='ready' && <FlowSourceDetails data={read.state.data}/>}
  <details className="pf-secondary"><summary>案件就緒條件</summary><ProjectReadiness w={c.w} p={p}/></details>
  {report && createPortal(<ProgressDetail caseKey={report.case_key} dept={report.dept} week={report.week} onClose={()=>setReport(null)}/>,document.body)}
 </div>;
}
