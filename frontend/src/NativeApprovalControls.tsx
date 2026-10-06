import {executionAllowed,executionReason} from './ProjectExecution';
import {draftKey,useDraft} from './drafts';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError} from './api';
import type {Project,Workspace,Session} from './types';
type Context={w:Workspace;s:Session;busy:boolean;refresh:()=>Promise<void>;run?:(action:string,payload?:Record<string,unknown>,scope?:{project_id?:string;node_id?:string})=>Promise<Workspace|undefined>};
const terminalLabels:Record<string,string>={rejected:'Lark 已拒絕此申請，不能套用。',withdrawn:'Lark 申請已撤回，不能套用。',invalidated:'核准內容或範圍已失效，需重新核對。',canceled:'Lark 申請已取消，不能套用。'};
export function NativeApprovalControls({c,kind,item,canSubmit}:{c:Context;kind:string;item:any;canSubmit:boolean}){
 const [busy,setBusy]=useState(false);
 const [message,setMessage]=useState('');
 const [failed,setFailed]=useState(false);
 const section=useRef<HTMLElement>(null);
 const heading=useRef<HTMLHeadingElement>(null);
 const intent=useRef<string|null>(null);
 const lastFocus=useRef<HTMLElement|null>(null);
 // Controls unmount as confirm/abandon/cancel/poll/refresh change state; never leave focus on <body>.
 useEffect(()=>{
   if(busy)return;
   const active=document.activeElement;
   const lost=!active||active===document.body;
   if(!lost){intent.current=null;return}
   const gone=lastFocus.current;
   const action=intent.current||(gone&&!gone.isConnected?gone.dataset.action:null)||null;
   if(!action)return;
   intent.current=null;lastFocus.current=null;
   const enabled=[...(section.current?.querySelectorAll<HTMLButtonElement>('button[data-action]')||[])].filter(b=>!b.disabled);
   (enabled.find(b=>b.dataset.action===action)||enabled[0]||heading.current)?.focus();
 });
 if(c.s.mode==='demo'||c.w.environment==='test')return <p className="ops-notice">此為隔離環境，不向正式 Lark 送審。</p>;
 const project=c.w.projects.find(p=>p.id===item.project_id);
 const writable=!!project&&executionAllowed(project,c.w);
 const available=c.w.approval_connection?.native_submit?.by_type?.[kind]?.available===true;
 const binding=item.native_binding, receipt=item.native_receipt;
 const terminal=!!terminalLabels[item.status]||!!item.executed_at||!!item.applied_at;
 const originalApplicant=binding?.payload?.open_id===c.s.user?.id;
 // Show recovery only for the same documented rejection evidence accepted by the server.
 const notCreated=binding?.creation_outcome==='not_created'&&
   binding?.not_created_proof==='documented_api_rejection'&&
   binding?.creation_rejection?.http_status===400&&
   [1390001,1390015,1390013].includes(binding?.creation_rejection?.api_code)&&
   !!binding?.payload?.uuid&&binding.creation_rejection.uuid===binding.payload.uuid;
 const cancelRetry=!!binding?.cancel_rejection&&!binding?.cancel_attempted;
 const invoke=async(operation:string)=>{
   intent.current=operation;
   setBusy(true);setMessage('');setFailed(false);
   try{
     await api<Workspace>(`/api/native-approvals/${kind}/${encodeURIComponent(item.id)}/${operation}`,{
       method:'POST',body:JSON.stringify({project_version:project?.concurrency_version})});
     await c.refresh();
     setMessage(operation==='prepare'?'已核對並保存送審內容，尚未向 Lark 提單。':
       operation==='abandon'?'已結束這筆未建立的申請並保留紀錄；暫停工作仍須另行確認恢復。':
       '已查回處理結果，請查看最新審批狀態。');
   }catch(e){
     // A remote failure may have persisted a rejection or unknown-outcome checkpoint.
     if(e instanceof ApiError&&[401,409,503].includes(e.status))await c.refresh();
     setMessage((e as Error).message);setFailed(true);
   }finally{setBusy(false)}
 };
 const status=terminalLabels[item.status]||(
   item.executed_at||item.applied_at?'此核准已套用，歷史與最新查回結果分別留存。':
   notCreated?'Lark 已明確拒絕建立這筆申請。修正設定後可重試原申請，或結束這筆申請；不會另建第二張。':
   binding?.cancel_attempted?'撤回結果待核實，請查回原審批；不會重複送出撤回。':
   cancelRetry?'Lark 已明確拒絕撤回。修正原因後可重試撤回；系統會先核對原審批是否仍在審批中。':
   binding?.verification_failed_at?'最近查回失敗，待核對；完成查回前不能套用新核准。':
   receipt?.approved&&receipt.binding_verified&&receipt.simulated===false?'Lark 已核准且綁定已核實，尚須依規則套用。':
   binding?.status==='outcome_unknown'?'送出結果待核實；查回原申請，不建立第二張。':
   binding?.status==='prepared'?'送審內容已備妥，尚未送出。':
   binding?'已保留送審識別，請查回最新結果。':'尚未核實 Lark 審批單設定。');
 return <section ref={section} className="native-approval-controls" aria-busy={busy} onFocus={e=>{const t=(e.target as HTMLElement).closest<HTMLElement>('[data-action]');if(t)lastFocus.current=t}}>
   <h3 ref={heading} tabIndex={-1}>Lark 審批</h3>
   {!writable&&project&&<p>{executionReason(project)}既有審批仍可查回或由原申請人撤回。</p>}
   {!available&&<p>目前未開放新建 Lark 審批，既有申請仍可查回核對。</p>}
   <p>{status}</p>
   <div className="inline-actions">
     {writable&&!terminal&&!binding&&<button className="button" disabled={busy||c.busy||!canSubmit} data-action="prepare" onClick={()=>void invoke('prepare')}>核對送審設定</button>}
     {writable&&!terminal&&(binding?.status==='prepared'||notCreated)&&<button className="button primary" disabled={busy||c.busy||!canSubmit||!available} data-action="submit" onClick={()=>void invoke('submit')}>{notCreated?'重試原申請':'送出至 Lark'}</button>}
     {binding&&binding.status!=='prepared'&&!notCreated&&<button className="button" disabled={busy||c.busy} data-action="poll" onClick={()=>void invoke('poll')}>查回原審批結果</button>}
     {notCreated&&originalApplicant&&!item.executed_at&&!item.applied_at&&!['withdrawn','canceled'].includes(item.status)&&<button className="button" data-action="abandon" disabled={busy||c.busy} onClick={()=>{
       if(window.confirm('結束這筆確定未建立的申請？紀錄會保留；已暫停工作不會自動恢復。'))void invoke('abandon');else intent.current='abandon'
     }}>結束未建立的申請</button>}
     {binding?.attempted&&!notCreated&&!binding.cancel_attempted&&!item.executed_at&&!item.applied_at&&!['withdrawn','canceled','rejected'].includes(item.status)&&(item.can_cancel_native===true||originalApplicant)&&<button className="button" data-action="cancel" disabled={busy||c.busy} onClick={()=>{
       if(window.confirm('確定撤回此張 Lark 審批？查回確認前仍會保留原申請紀錄。'))void invoke('cancel');else intent.current='cancel'
     }}>{cancelRetry?'重試撤回原審批':'撤回原 Lark 審批'}</button>}
   </div>
   <p role="status" aria-live="polite">{busy?'正在處理，請稍候…':failed?'':message}</p>
   {!busy&&failed&&message&&<p className="form-error" role="alert">{message}</p>}
 </section>;
}
export function FinancialApprovalRequests({c,p}:{c:Context;p:Project}){
 // Remount per user/workspace/project so node, evidence, kind and payables state never carry over.
 return <FinancialApprovalForm key={draftKey(c.s,c.w,`financial:${p.id}`)} c={c} p={p}/>;
}
function FinancialApprovalForm({c,p}:{c:Context;p:Project}){
 const[reason,setReason]=useDraft(draftKey(c.s,c.w,`financial:${p.id}:reason`),'');const[kind,setKind]=useState('contract');const[payables,setPayables]=useState('unknown');const[node,setNode]=useState(p.nodes.find(n=>['pricing','settlement'].includes(n.key)&&(c.s.user?.can_business_override||[p.pm_id,p.admin_id,n.owner_id].includes(c.s.user?.id||'')))?.id||'');const[evidence,setEvidence]=useState<string[]>([]);const[busy,setBusy]=useState(false);const[error,setError]=useState('');
 const businessLead=c.s.user?.can_business_override===true||c.s.user?.id===p.pm_id;
 const canCreateForNode=(nodeId:string)=>executionAllowed(p,c.w)&&(businessLead||c.s.user?.id===p.admin_id||c.s.user?.id===p.nodes.find(n=>n.id===nodeId)?.owner_id);
 const financialNodes=p.nodes.filter(n=>['pricing','settlement'].includes(n.key)&&canCreateForNode(n.id));
 const canCreate=financialNodes.length>0;
 const canFinalize=(nodeId:string)=>{const n=p.nodes.find(n=>n.id===nodeId);return !!n&&executionAllowed(p,c.w)&&(businessLead||[p.admin_id,p.supervisor_id,n.owner_id,n.supervisor_id,...n.collaborator_ids,...n.tasks.map(t=>t.owner_id)].includes(c.s.user?.id||''))};
 const requests=(c.w.financial_requests||[]).filter((r:any)=>r.project_id===p.id);
 const create=async()=>{setBusy(true);setError('');try{await api('/api/native-approvals/financial/request',{method:'POST',body:JSON.stringify({version:c.w.version,project_id:p.id,node_id:node,evidence_ids:evidence,reason,confirmation_kind:kind,payables_declaration:payables})});await c.refresh();setReason('');setEvidence([])}catch(e){if(e instanceof ApiError&&[401,409].includes(e.status))await c.refresh();setError((e as Error).message)}finally{setBusy(false)}};
 return <section className="financial-requests"><h3>重大財務確認</h3><p>引用來源與佐證交 PM、行政確認；此入口不新增帳務或登錄收付款。</p>{requests.map((item:any)=><article key={item.id}><strong>{item.reason||'財務確認'}</strong><p>{terminalLabels[item.status]?terminalLabels[item.status]:item.status==='approved'?'已核准':item.status==='pending'?'審批中':'待核對送審'}</p><NativeApprovalControls c={c} kind="financial" item={item} canSubmit={executionAllowed(p,c.w)&&(businessLead||item.created_by===c.s.user?.id)}/>{canFinalize(item.node_id)&&item.status==='approved'&&item.native_receipt?.approved&&item.native_receipt?.binding_verified&&item.native_receipt?.simulated===false&&<button className="button primary" disabled={c.busy||!c.run||!!item.native_binding?.verification_failed_at} onClick={()=>void c.run?.('financial_finalize',{},{project_id:p.id,node_id:item.node_id})}>核實條件並完成財務節點</button>}</article>)}{(c.s.mode==='demo'||c.w.environment==='test')&&<p className="ops-notice">隔離環境不建立正式財務審批；請在正式工作區核實来源與佐證後送審。</p>}{canCreate&&c.s.mode!=='demo'&&c.w.environment!=='test'&&<details className="ops-form"><summary>建立財務確認草稿</summary><form onSubmit={e=>{e.preventDefault();void create()}}><label className="form-field">確認事項<select value={kind} onChange={e=>setKind(e.target.value)}><option value="contract">合約確認</option><option value="payment">款項確認</option><option value="settlement">結算確認</option></select></label><label className="form-field">所屬階段<select value={node} onChange={e=>setNode(e.target.value)}>{financialNodes.map(n=><option key={n.id} value={n.id}>{n.name}</option>)}</select></label><label className="form-field">下包與其他應付款確認<select value={payables} onChange={e=>setPayables(e.target.value)}><option value="unknown">尚未確認</option><option value="no_payables">本案無應付款（須附佐證並共同核准）</option><option value="all_settled">應付款已結清（須附佐證並共同核准）</option></select></label><p>此為待審聲明，並非記帳或付款；核准回執通過前不會視為已結清。</p><label className="form-field">確認原因<textarea value={reason} onChange={e=>setReason(e.target.value)} required/></label><p>只列已覆核的交付證明或已核實的檔案。缺件請先<a href={`#view=project&project=${encodeURIComponent(p.id)}&node=${encodeURIComponent(node)}&tab=flow&section=review`}>返回交付與確認補齊</a>。</p><fieldset><legend>引用佐證</legend>{[...(p.evidence||[]),...p.files].filter((e:any)=>!e.withdrawn&&!e.superseded_for_current&&(!e.status||e.status==='accepted')&&(e.storage!=='local'||e.remote_status==='verified')&&(!e.node_id||e.node_id===node)).map((item:any)=><label key={item.id}><input type="checkbox" checked={evidence.includes(item.id)} onChange={e=>setEvidence(ids=>e.target.checked?[...ids,item.id]:ids.filter(id=>id!==item.id))}/>{item.note||item.name||item.key}</label>)}</fieldset><button className="button" disabled={busy||c.busy||!reason.trim()||!node||!evidence.length||!canCreateForNode(node)}>保存確認草稿</button></form></details>}{error&&<p className="form-error" role="alert">{error}</p>}</section>;
}
