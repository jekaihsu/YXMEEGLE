// Pure display rules for execution admission. The server stays authoritative:
// nothing here grants admission, it only explains it and routes the handler.
export type AdmissionInput={id?:string;execution_system?:string|null;execution_system_label?:string|null;execution_readonly_reason?:string|null;execution_allowed?:boolean|null;workbench_execution_enabled?:boolean|null;case_visibility?:string|null};
export type AdmissionHandling='none'|'manager_assign'|'request_manager_review';
export type AdmissionState={admitted:boolean;system:string;label:string;reason:string;handling:AdmissionHandling;notice:string};
const LABELS:Record<string,string>={pending:'待確認歸屬',meegle:'Meegle 舊案（唯讀參考）',workbench:'工作台執行'};
const REQUEST_REVIEW='請向管理員申請核定；你無權自行指派執行歸屬。';
const MANAGER_ENTRY='管理員可於案件頁或待核定佇列逐案核定。';
export const isManager=(role?:string|null)=>role==='manager';
export function admissionState(p:AdmissionInput,role?:string|null):AdmissionState{
 const system=p.execution_system&&p.execution_system in LABELS?p.execution_system:'pending';
 const admitted=(p.execution_allowed??p.workbench_execution_enabled)===true;
 const label=p.execution_system_label||LABELS[system];
 if(admitted)return{admitted,system,label,reason:'',handling:'none',notice:''};
 const reason=p.execution_readonly_reason||(system==='meegle'?'舊案留在 Meegle 完成':'等待管理員核定案件歸屬');
 // Meegle-owned or isolated history is not a pending decision a manager can queue.
 const assignable=system==='pending'&&p.case_visibility!=='excluded_history';
 const handling:AdmissionHandling=!assignable?'none':isManager(role)?'manager_assign':'request_manager_review';
 return{admitted,system,label,reason,handling,notice:handling==='manager_assign'?MANAGER_ENTRY:handling==='request_manager_review'?REQUEST_REVIEW:''};
}
// Manager-only queue of cases still waiting for an individual decision.
export function pendingAdmissionQueue<T extends AdmissionInput>(projects:T[],role?:string|null):T[]{
 if(!isManager(role))return[];
 return projects.filter(p=>p.case_visibility==='source_reference'&&admissionState(p,role).handling==='manager_assign');
}
