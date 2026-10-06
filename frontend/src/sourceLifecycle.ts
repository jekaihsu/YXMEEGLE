// Relationship class, quote workflow (狀態) and engineering lifecycle (案件狀態) stay separate.
// Only a canonical lifecycle may gate behavior; raw source_status never counts as closure.
export interface SourceLifecycle{
 relationship:string;state:'mapped'|'needs_verification';canonical:string|null;reasons:string[];
 quote_workflow?:{raw:string;kind:'blank'|'won'|'date'|'other'}[];
}
export const UNVERIFIED='待核對';
export const declaredLifecycle=(p:{source_lifecycle?:SourceLifecycle|null})=>p.source_lifecycle?.canonical||null;
export const lifecycleLabel=(l?:SourceLifecycle|null)=>l?.canonical||UNVERIFIED;
export const lifecycleReasonLabel=(l?:SourceLifecycle|null)=>{
 const reasons=l?.reasons??['unreviewed'];
 return reasons.map(r=>({blank:'尚未填寫案件狀態',unknown_option:'含無法對應的狀態選項',conflict:'確認單與報價的案件狀態不一致',unreviewed:'尚未核對'}[r]||'需人工核對')).join('、');
};
export const quoteWorkflowLabel=(l?:SourceLifecycle|null)=>{
 const raws=[...new Set((l?.quote_workflow||[]).map(w=>w.raw).filter(Boolean))];
 return raws.length?raws.join('、'):'—';
};
