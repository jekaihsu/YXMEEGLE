import type {Project,Workspace} from './types';

export function ProjectReadiness({w,p}:{w:Workspace;p:Project}){
 const summary=p.policy_summary||(w.policy_summary||[]).find((s:any)=>s.project_id===p.id);const closure=summary?.closure;
 const missing:string[]=closure?.missing||summary?.nodes?.find((n:any)=>n.id===p.nodes.find(n=>n.key==='settlement')?.id)?.missing||[];
 return <section className="project-readiness"><h2>交付進度與結案條件</h2><p>V4 顯示「{p.source_status||'來源待核對'}」僅是來源業務狀態；工作台仍核對技術交付、業務確認與財務條件。</p><strong>{closure?.status==='completed'?'工作台結案條件已完成':closure?.status==='ready'?'結案條件已齊，等待完成流程':closure?'尚有結案條件待處理':'結案條件尚待完整檢核'}</strong>{missing.length>0&&<ul>{missing.map((text,index)=><li key={index}>{text}</li>)}</ul>}{closure?.financial&&<dl><div><dt>收入確認</dt><dd>{closure.financial.incoming?.status==='incoming_settled'?'來源核對已齊':'尚待來源與收款條件核對'}</dd></div><div><dt>支出確認</dt><dd>{['no_payables','all_settled'].includes(closure.financial.payables?.status)?'核准條件已齊':'尚待有效財務確認'}</dd></div></dl>}</section>;
}

export function SourceContractIndex({w,p}:{w:Workspace;p:Project}){
 const confirmations=(w.source_confirmations||[]).filter((r:any)=>r.project_id===p.id);
 const items=(w.contract_items||[]).filter((r:any)=>r.project_id===p.id||r.task_refs?.some((ref:any)=>ref.project_id===p.id));
 const link=(r:any)=>/^https?:\/\//i.test(r.source_url||'')?<a href={r.source_url} target="_blank" rel="noreferrer">開啟 Lark 來源</a>:null;
 return <section className="source-contract-index"><h2>工程確認單與合約工項</h2><p>來源唯讀。報價可連到多份工程確認單；跨組任務引用同一合約工項，金額不重複加總。</p>{confirmations.map((row:any)=><article key={row.id}><h3>{row.code||'確認單案號待核對'}</h3><p>{row.source_missing?'來源已移除，保留紀錄':`${row.quote_ids?.length||0} 份關聯報價`}</p>{link(row)}</article>)}{items.map((row:any)=><article key={row.id}><h3>{row.name||row.title||'合約工項'}</h3><p>{row.task_refs?.length||0} 項跨組任務引用 · 分配狀態尚未核實</p><p>來源金額：{row.amount_original==null?'待核對':Number(row.amount_original).toLocaleString()} · 申報金額：{row.amount_reported==null?'待核對':Number(row.amount_reported).toLocaleString()}</p><ul>{(row.task_refs||[]).map((ref:any)=>{const project=w.projects.find(x=>x.id===ref.project_id),node=project?.nodes.find(x=>x.id===ref.node_id),task=node?.tasks.find(x=>x.id===ref.task_id);return <li key={ref.task_id}><a href={`#view=project&project=${encodeURIComponent(ref.project_id)}&node=${encodeURIComponent(ref.node_id)}&task=${encodeURIComponent(ref.task_id)}&tab=flow`}>{project?.code||'案件'} · {node?.name||'階段'} · {task?.title||'查看任務'}</a></li>})}</ul>{link(row)}</article>)}{!confirmations.length&&!items.length&&<p>尚無已核實的確認單／合約工項關聯，請查看來源同步狀態。</p>}</section>;
}
