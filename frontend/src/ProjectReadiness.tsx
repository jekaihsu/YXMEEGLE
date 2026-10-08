import {Circle,CircleAlert,CircleCheck} from 'lucide-react';
import {Row} from './design';
import './ProjectPanels.css';
import type {Project,Workspace} from './types';
import {declaredLifecycle,lifecycleLabel,lifecycleReasonLabel,quoteWorkflowLabel} from './sourceLifecycle';

export function ProjectReadiness({w,p}:{w:Workspace;p:Project}){
 const summary=p.policy_summary||(w.policy_summary||[]).find((s:any)=>s.project_id===p.id);const closure=summary?.closure;
 const missing:string[]=closure?.missing||summary?.nodes?.find((n:any)=>n.id===p.nodes.find(n=>n.key==='settlement')?.id)?.missing||[];
 const status=closure?.status==='completed'?'工作台結案條件已完成':closure?.status==='ready'?'結案條件已齊，等待完成流程':closure?'尚有結案條件待處理':'結案條件尚待完整檢核';
 const done=closure?.status==='completed'||closure?.status==='ready';
 return <section className="ds-section project-readiness"><h2>交付進度與結案條件</h2><div className="ds-group glass--flat"><Row icon={done?<CircleCheck size={20}/>:<CircleAlert size={20}/>} label={<strong>{status}</strong>}/><details className="pr-more"><summary>來源業務資料（另行核對）</summary><Row label="來源案件狀態" detail={<>來源案件狀態：{lifecycleLabel(p.source_lifecycle)}{!declaredLifecycle(p)&&`（${lifecycleReasonLabel(p.source_lifecycle)}）`} · 報價狀態：{quoteWorkflowLabel(p.source_lifecycle)} · 關聯：{p.source_lifecycle?.relationship||p.source_status||'來源待核對'}。這些僅是來源業務資料；工作台仍核對技術交付、業務確認與財務條件。</>}/></details>{missing.slice(0,3).map((text,index)=><Row key={index} label={text} icon={<Circle size={14}/>}/>)}{missing.length>3&&<details className="pr-more"><summary>其餘 {missing.length-3} 項待處理條件</summary>{missing.slice(3).map((text,index)=><Row key={index+3} label={text} icon={<Circle size={14}/>}/>)}</details>}{closure?.financial&&<><Row label="收入確認" value={closure.financial.incoming?.status==='incoming_settled'?'來源核對已齊':'尚待來源與收款條件核對'}/><Row label="支出確認" value={['no_payables','all_settled'].includes(closure.financial.payables?.status)?'核准條件已齊':'尚待有效財務確認'}/></>}</div></section>;
}

export function SourceContractIndex({w,p}:{w:Workspace;p:Project}){
 const confirmations=(w.source_confirmations||[]).filter((r:any)=>r.project_id===p.id);
 const items=(w.contract_items||[]).filter((r:any)=>r.project_id===p.id||r.task_refs?.some((ref:any)=>ref.project_id===p.id));
 const link=(r:any)=>/^https?:\/\//i.test(r.source_url||'')?<a href={r.source_url} target="_blank" rel="noreferrer">開啟 Lark 來源</a>:null;
 return <section className="ds-section source-contract-index"><h2>工程確認單與合約工項</h2><div className="ds-group glass--flat">{confirmations.map((row:any)=><Row key={row.id} label={row.code||'確認單案號待核對'} detail={row.source_missing?'來源已移除，保留紀錄':`${row.quote_ids?.length||0} 份關聯報價`} value={link(row)}/>)}{items.map((row:any)=><div key={row.id} className="sc-item"><Row label={row.name||row.title||'合約工項'} detail={<>{row.task_refs?.length||0} 項跨組任務引用 · 分配狀態尚未核實<br/>來源金額：{row.amount_original==null?'待核對':Number(row.amount_original).toLocaleString()} · 申報金額：{row.amount_reported==null?'待核對':Number(row.amount_reported).toLocaleString()}</>} value={link(row)}/>{(row.task_refs||[]).map((ref:any)=>{const project=w.projects.find(x=>x.id===ref.project_id),node=project?.nodes.find(x=>x.id===ref.node_id),task=node?.tasks.find(x=>x.id===ref.task_id);return <Row key={ref.task_id} href={`#view=project&project=${encodeURIComponent(ref.project_id)}&node=${encodeURIComponent(ref.node_id)}&task=${encodeURIComponent(ref.task_id)}&tab=flow`} label={`${project?.code||'案件'} · ${node?.name||'階段'} · ${task?.title||'查看任務'}`}/>})}</div>)}{!confirmations.length&&!items.length&&<Row label="尚無已核實的確認單／合約工項關聯，請查看來源同步狀態。"/>}</div><p className="ds-footer">來源唯讀。報價可連到多份工程確認單；跨組任務引用同一合約工項，金額不重複加總。</p></section>;
}
