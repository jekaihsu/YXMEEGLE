import {TriangleAlert} from 'lucide-react';
import {Button,Skeleton} from './design';
import {STATUS_LEVEL_NOTE,caseStatusLabel,nodeStatusText,type NextStep,type StageContext} from './stageModel';
import './StageWorkspace.css';
import './CaseDetailRedesign.css';
export function CaseSummary({status,ctx,step,blockers,loading,error,stale,onStep,onCurrent}:{status:string|undefined;ctx:StageContext;step:NextStep;blockers:string[];loading:boolean;error:string;stale:boolean;onStep:(step:NextStep)=>void;onCurrent:()=>void}){
 const current=ctx.currentIds.map(key=>ctx.nodes.find(n=>n.key===key)?.label||key);
 const label=(key:string)=>ctx.nodes.find(n=>n.key===key)?.label||key;
 const node=ctx.nodes.find(n=>n.key===ctx.currentIds[0]);
 const owners=node?.owners.map(o=>o.name).filter(Boolean).join('、')||'尚未指派';
 const deadline=node?.deadline?node.deadline.slice(0,10):'未排定';
 const actionable=step.kind==='action'||step.kind==='view';
 return <section className="po-card cs-summary" aria-label="案件摘要" aria-busy={loading}>
  {error ? <p role="alert">流程來源暫不可用，無法確認目前階段。{error}</p> : loading ? <div role="status"><p>正在核對節點與任務…</p><Skeleton lines={3}/></div> : <>
   <dl className="cs-band">
    <div className="cs-stage"><dt>目前階段</dt><dd>{ctx.workflow==='missing' ? '流程尚未設定' : current.length ? <><strong>{current[0]}</strong>{current.length>1 && <small>另有進行中：{current.slice(1).join('、')}</small>}</> : ctx.finished ? '所有節點已完成或略過' : '目前階段待確認'}</dd></div>
    <div><dt>負責人</dt><dd><strong>{node?owners:'未知'}</strong></dd></div>
    <div><dt>期限</dt><dd><strong>{node?deadline:'未知'}</strong></dd></div>
    <div className="cs-next"><dt>下一步</dt><dd><strong>{step.title}</strong>{actionable ? <><small>{step.reason}</small><Button variant="primary" onClick={()=>onStep(step)}>{step.button}</Button></> : step.reasons.map((r,i)=><small key={i}>{r}</small>)}</dd></div>
   </dl>
   <div className="cs-levels" aria-label="狀態層級">
    <p className="cs-level cs-level-case" title={STATUS_LEVEL_NOTE}><span>案件狀態</span>{caseStatusLabel(status)}</p>
    {node && <p className="cs-level cs-level-flow" title={STATUS_LEVEL_NOTE}><span>流程節點狀態</span>{label(node.key)}：{nodeStatusText(node.state)}</p>}
   </div>
   {!ctx.currentSelected && ctx.selectedId && <p className="cs-selected" role="status"><span>選取階段</span>正在檢視「{label(ctx.selectedId)}」，不是目前階段<Button variant="plain" onClick={onCurrent}>回到目前階段</Button></p>}
   {!!blockers.length && <ul className="cs-blockers" aria-label="待處理原因">{blockers.map((b,i)=><li key={i}>{b}</li>)}</ul>}
   {stale && <p className="cs-stale" role="status"><TriangleAlert size={14} aria-hidden="true"/>資料為上次成功讀取，可能已過期，請重新整理後再操作。</p>}
  </>}
 </section>;
}
