import {FlowDiagram} from './FlowDiagram';
import {buildFlowModel} from './flowModel';
import {fieldworkSnapshot,needsAttention,selectNextAction,type OverviewTarget} from './projectOverviewModel';
import {executionAllowed,executionReason} from './ProjectExecution';
import {useProjectProgress} from './useProjectProgress';
import type {useNodeAssignments} from './useNodeAssignments';
import {Button} from './design';
import {eventMessage,isProjectLead,nameOf,stamp,type Ctx} from './appCommon';
import type {Project} from './types';
import './ProjectFlow.css';
import './ProjectOverview.css';
export function ProjectOverview({c,p,assignments}:{c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>}){
 const read=useProjectProgress(p.id),list='data' in assignments.state ? assignments.state.data : undefined;
 const data=read.state.kind==='ready' ? read.state.data : undefined;
 const model=buildFlowModel({project:assignments.state.kind==='disabled' ? p : {...p,nodes:[]},assignments:list,progress:data,today:c.w.as_of,users:c.w.users});
 const unavailable=assignments.state.kind==='loading' || assignments.state.kind==='error';
 const approval=c.s.features?.change_extension ? c.w.approvals.filter(a=>a.project_id===p.id && a.status==='pending' && p.nodes.some(n=>n.id===a.node_id && n.status==='paused')).sort((a,b)=>a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))[0] : undefined;
 const action=selectNextAction({nodes:model.nodes,list,user:c.s.user,today:c.w.as_of,execution:{allowed:executionAllowed(p,c.w),reason:executionReason(p)},localLead:isProjectLead(c.s,p),assignmentsUnavailable:unavailable,blockingApproval:approval ? {id:approval.id,title:approval.title,node:approval.node_id,owner:p.supervisor_id ? nameOf(c.w,p.supervisor_id) : '案件主管'} : undefined});
 const snapshot=fieldworkSnapshot(data?.production.field,p.daily_reports,!!data?.sources.reports_stale || !!list?.stale),issues=needsAttention(model.nodes,data?.production.field);
 const latest=c.w.events.filter(e=>e.project_id===p.id).slice().sort((a,b)=>b.created_at.localeCompare(a.created_at))[0];
 const go=(target:OverviewTarget)=>c.go({view:'project',project:p.id,...target});
 const current=list?.summary.current_node || model.nodes.find(n=>n.state==='進行中' || n.state==='待審核')?.key || model.nodes[0].key;
 return <div className="project-overview">
  <section className="po-next" aria-labelledby="po-next-title"><div><p className="po-eyebrow">下一步</p><h2 id="po-next-title">{action.title}</h2><p>{action.reason}</p><small>負責窗口 · {action.owner}</small></div><Button variant="primary" onClick={()=>go(action.target)}>{action.button}</Button></section>
  {assignments.state.kind==='loading' && <p className="po-source-state" role="status">節點指派載入中，其他案件資訊仍可查看。</p>}
  {assignments.state.kind==='error' && <p className="po-source-state" role="alert">節點來源暫不可用 · {assignments.state.message}<Button variant="plain" onClick={()=>void assignments.reload()}>重試節點來源</Button></p>}
  {list?.stale && <p className="po-source-state">節點來源為上次成功資料，待更新核對。{list.stale_reason}</p>}
  <FlowDiagram compact nodes={model.nodes} overall={model.overall} selected={current} loading={assignments.state.kind==='loading'} onSelect={node=>go({tab:'flow',node})}/>
  <div className="po-grid"><section className="po-card" aria-labelledby="po-field-title"><h2 id="po-field-title">外業進度</h2><p className="po-quantity">{read.state.kind==='loading' ? '工程證據載入中' : read.state.kind==='error' ? '工程證據暫不可用' : '尚無可信完成量'}<small>{read.state.kind==='ready' ? '待核對' : '完成比例未知'}</small></p><p>{read.state.kind==='error' ? read.state.message : snapshot.reason}</p><dl><div><dt>關聯工項</dt><dd>{snapshot.count===null ? '尚未提供' : `${snapshot.count} 筆`}</dd></div><div><dt>最近有效回報</dt><dd>{snapshot.latestDate || '尚未提供可核實的回報日期'}</dd></div></dl>{data?.sources.reports_status==='restricted' && <p>週報來源權限不足，日報與工項狀態分開核對。</p>}{data?.sources.reports_stale && <p>週報為上次成功資料，待更新。</p>}{read.state.kind==='error' && <Button variant="plain" onClick={read.retry}>重試工程證據</Button>}<Button variant="plain" onClick={()=>go({tab:'items',node:'field'})}>查看工項與進度 →</Button></section>
  <section className="po-card" aria-labelledby="po-attention-title"><h2 id="po-attention-title">需要注意</h2>{issues.length ? <ul className="po-issues">{issues.slice(0,3).map(issue=><li key={issue.id}><a href={`#${new URLSearchParams({view:'project',project:p.id,...issue.target})}`} onClick={e=>{e.preventDefault();go(issue.target)}}><strong>{issue.title}</strong><p>{issue.reason}</p><small>負責窗口 · {issue.owner} · 查看詳情 →</small></a></li>)}</ul> : <p>{unavailable ? '節點來源尚未核實，暫時無法確認是否有待處理事項。' : '目前沒有需要立即處理的事項'}</p>}{issues.length>3 && <Button variant="plain" onClick={()=>go({tab:'flow'})}>查看全部 {issues.length} 項</Button>}</section></div>
  <footer className="po-footer">最近活動 · {latest ? `${eventMessage(latest)}（${stamp(latest.created_at)}）` : '尚未提供'} · 最後成功來源同步 {data?.sources.source_synced_at || c.w.source_status.last_sync || '尚未提供'}{c.w.source_status.status!=='ready' && ' · 來源狀態待核對'}</footer>
 </div>;
}
