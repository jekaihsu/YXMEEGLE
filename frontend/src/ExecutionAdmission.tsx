import {useState} from 'react';
import type {Project,Session,Workspace} from './types';
import {admissionState,pendingAdmissionQueue,type AdmissionInput} from './admissionRules';

// Shows execution_system and the exact not-admitted reason in list surfaces.
export function AdmissionCell({p,role}:{p:AdmissionInput;role?:string|null}){
 const a=admissionState(p,role);
 return <span className={`admission-cell${a.admitted?'':' not-admitted'}`} data-admission={a.admitted?'admitted':a.handling}>
  <strong>{a.label}</strong>
  {!a.admitted&&<small className="admission-reason">未核定執行：{a.reason}</small>}
  {a.notice&&<small className="admission-handling">{a.notice}{p.id&&a.handling==='manager_assign'&&<> <a href={`#view=project&project=${encodeURIComponent(p.id)}`} onClick={e=>e.stopPropagation()}>前往案件核定</a></>}</small>}
 </span>;
}

type Run=(action:string,payload:Record<string,unknown>,scope:{project_id:string})=>Promise<Workspace|undefined>;
// One audited case_execution_assign per submit; no bulk and no default target.
export function ExecutionAdmissionQueue({w,s,run,busy}:{w:Workspace;s:Session;run:Run;busy:boolean}){
 const rows=pendingAdmissionQueue(w.projects,s.user?.role);
 if(!rows.length)return null;
 return <section className="ops-notice admission-queue" aria-label="待核定執行歸屬佇列"><strong>待核定執行歸屬（{rows.length}）</strong><p>逐案核定；每次送出只更新一個案件並留下稽核紀錄，不提供批次核准。</p>
  <ul>{rows.map(p=><AdmissionQueueRow key={p.id} p={p} run={run} busy={busy}/>)}</ul></section>;
}
function AdmissionQueueRow({p,run,busy}:{p:Project;run:Run;busy:boolean}){
 const[value,setValue]=useState('');const[reason,setReason]=useState('');
 const ready=!!value&&!!reason.trim();
 return <li><a href={`#view=project&project=${encodeURIComponent(p.id)}`}>{p.code} {p.name}</a><small>{admissionState(p,'manager').reason}</small>
  <form onSubmit={e=>{e.preventDefault();if(!ready||busy)return;void run('case_execution_assign',{execution_system:value,reason},{project_id:p.id}).then(r=>{if(r){setValue('');setReason('')}})}}>
   <label>執行系統<select value={value} disabled={busy} onChange={e=>setValue(e.target.value)}><option value="">請選擇</option><option value="meegle">Meegle 執行至完成</option><option value="workbench">本工作台執行</option></select></label>
   <label>核定依據<input required maxLength={1000} value={reason} disabled={busy} onChange={e=>setReason(e.target.value)}/></label>
   <button className="button compact" disabled={busy||!ready}>核定此案</button></form></li>;
}
