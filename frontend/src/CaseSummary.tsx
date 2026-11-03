import {DataState,Button,Skeleton} from './design';
import {nodeStatusText,type NextStep,type StageContext} from './stageModel';
import './StageWorkspace.css';
import './CaseDetailRedesign.css';
export function CaseSummary({ctx,step,loading,error,onStep,onCurrent,onRetry,showNext=true}:{ctx:StageContext;step:NextStep;loading:boolean;error:string;onStep:(step:NextStep)=>void;onCurrent:()=>void;onRetry:()=>void;showNext?:boolean}){
 const current=ctx.currentIds.map(key=>ctx.nodes.find(n=>n.key===key)?.label||key);
 const label=(key:string)=>ctx.nodes.find(n=>n.key===key)?.label||key;
 const node=ctx.nodes.find(n=>n.key===ctx.currentIds[0]);
 const owners=node?.owners.map(o=>o.name).filter(Boolean).join('、')||'尚未指派';
 const deadline=node?.deadline?node.deadline.slice(0,10):'未排定';
 const actionable=step.kind==='action'||step.kind==='view';
 return <section className="po-card cs-summary" aria-label="案件摘要" aria-busy={loading}>
  {error ? <DataState kind="Error" title="流程來源暫不可用" body={`無法確認目前階段。${error}`} actions={<Button onClick={onRetry}>重試</Button>}/> : loading ? <div role="status"><p>正在核對節點與任務…</p><Skeleton lines={3} width="100%"/></div> : <>
   <dl className="cs-band">
    <div className="cs-stage"><dt>目前階段</dt><dd>{ctx.workflow==='missing' ? '流程尚未設定' : current.length ? <><strong>{current[0]} · {nodeStatusText(node?.state||'')}</strong>{current.length>1 && <small>另有進行中：{current.slice(1).join('、')}</small>}</> : ctx.finished ? '所有節點已完成或略過' : '目前階段待確認'}</dd></div>
    <div><dt>負責人</dt><dd><strong>{node?owners:'未知'}</strong></dd></div>
    <div><dt>階段期限</dt><dd><strong>{node?deadline:'未知'}</strong></dd></div>
    {showNext&&<div className="cs-next"><dt>下一步</dt><dd><strong title={step.title}>{step.title}</strong>{actionable ? <><small title={step.reason}>{step.reason}</small><Button variant="primary" onClick={()=>onStep(step)}>{step.button}</Button></> : <small title={step.reasons[0]}>{step.reasons[0]}</small>}</dd></div>}
   </dl>
   {!ctx.currentSelected && ctx.selectedId && <p className="cs-selected" role="status"><span>選取階段</span>正在檢視「{label(ctx.selectedId)}」，不是目前階段<Button variant="plain" onClick={onCurrent}>回到目前階段</Button></p>}
  </>}
 </section>;
}
