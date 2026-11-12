// Relationship class, quote workflow (狀態) and engineering lifecycle (案件狀態) stay separate.
// Only a canonical lifecycle may gate behavior; raw source_status never counts as closure.
export interface SourceLifecycle{
 relationship:string;state:'mapped'|'needs_verification';canonical:string|null;reasons:string[];
 quote_workflow?:{raw:string;kind:'blank'|'won'|'date'|'other'}[];
}
export const UNVERIFIED='待核對';
// Verified only: mapped state, no outstanding review reasons. Missing/blank/unknown/conflicting → null.
export const declaredLifecycle=(p:{source_lifecycle?:SourceLifecycle|null})=>{
 const l=p.source_lifecycle;
 return l&&l.state==='mapped'&&!l.reasons?.length&&l.canonical?l.canonical:null;
};
// Lark-sourced cases need a verified lifecycle before work may run (fail closed).
export const lifecycleUnverified=(p:{source_lifecycle?:SourceLifecycle|null;source_kind?:string})=>(p.source_kind==='lark'||p.source_lifecycle!==undefined)&&declaredLifecycle(p)===null;
export const lifecycleGate=(p:{source_lifecycle?:SourceLifecycle|null;source_kind?:string})=>declaredLifecycle(p)==='中止'?'來源案件已中止':lifecycleUnverified(p)?'來源案件狀態待核對':'';
export const lifecycleLabel=(l?:SourceLifecycle|null)=>declaredLifecycle({source_lifecycle:l})||UNVERIFIED;
export const lifecycleReasonLabel=(l?:SourceLifecycle|null)=>{
 const reasons=l?.reasons??['unreviewed'];
 return reasons.map(r=>({blank:'尚未填寫案件狀態',unknown_option:'含無法對應的狀態選項',conflict:'確認單與報價的案件狀態不一致',unreviewed:'尚未核對'}[r]||'需人工核對')).join('、');
};
export const quoteWorkflowLabel=(l?:SourceLifecycle|null)=>{
 const raws=[...new Set((l?.quote_workflow||[]).map(w=>w.raw).filter(Boolean))];
 return raws.length?raws.join('、'):'—';
};
