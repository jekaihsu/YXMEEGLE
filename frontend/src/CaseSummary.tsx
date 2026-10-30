import {TriangleAlert} from 'lucide-react';
import {Button,Skeleton} from './design';
import {STATUS_LEVEL_NOTE,caseStatusLabel,type NextStep,type StageContext} from './stageModel';
import './StageWorkspace.css';
export function CaseSummary({status,ctx,step,blockers,loading,error,stale,onStep,onCurrent}:{status:string|undefined;ctx:StageContext;step:NextStep;blockers:string[];loading:boolean;error:string;stale:boolean;onStep:(step:NextStep)=>void;onCurrent:()=>void}){
 const current=ctx.currentIds.map(key=>ctx.nodes.find(n=>n.key===key)?.label||key);
 return <section className="po-card cs-summary" aria-label="案件摘要" aria-busy={loading}>
  <h2>案件摘要</h2>
  {error ? <p role="alert">流程來源暫不可用，無法確認目前階段。{error}</p> : loading ? <div role="status"><p>正在核對節點與任務…</p><Skeleton lines={3}/></div> : <>
   <dl>
    <div><dt>案件狀態</dt><dd>{caseStatusLabel(status)}</dd></div>
    <div><dt>目前階段</dt><dd>{ctx.workflow==='missing' ? '流程尚未設定' : current.length ? <>{current[0]}{current.length>1 && <small>，另有進行中：{current.slice(1).join('、')}</small>}{!ctx.currentSelected && <Button variant="plain" onClick={onCurrent}>回到目前階段</Button>}</> : ctx.finished ? '所有節點已完成或略過' : '目前階段待確認'}</dd></div>
    <div><dt>待處理原因</dt><dd>{blockers.length ? <ul>{blockers.map((b,i)=><li key={i}>{b}</li>)}</ul> : '目前沒有已知阻礙'}</dd></div>
    <div><dt>下一步</dt><dd>{step.kind==='action'||step.kind==='view' ? <><strong>{step.title}</strong><small>{step.reason}</small><Button variant="primary" onClick={()=>onStep(step)}>{step.button}</Button></> : <><strong>{step.title}</strong>{step.reasons.map((r,i)=><small key={i}>{r}</small>)}</>}</dd></div>
   </dl>
   {stale && <p className="cs-stale" role="status"><TriangleAlert size={14} aria-hidden="true"/>資料為上次成功讀取，可能已過期，請重新整理後再操作。</p>}
   <p className="cs-note">{STATUS_LEVEL_NOTE}</p>
  </>}
 </section>;
}
