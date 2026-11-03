import type {Project} from './types';
import type {CaseSnapshot} from './detailRefresh';
/** Omitted fields mean this source has no new evidence for that region. */
export function mergeCaseFacts<T extends {project:Project;snapshot?:CaseSnapshot}>(previous:T|undefined,next:T):T {
 if(!previous||previous.project.id!==next.project.id)return next;
 const snapshot=next.snapshot?{...previous.snapshot,...Object.fromEntries(Object.entries(next.snapshot).filter(([,v])=>v!=null))}:previous.snapshot;
 return {...next,project:{...previous.project,...next.project},snapshot};
}
export function caseNextExplanation(current:{label:string;owners:unknown[];finalDeadline?:unknown}|undefined,reason:string){
 return [current&&!current.owners.length?`${current.label}尚未指派負責人`:'',current&&!current.finalDeadline?'尚未排定節點期限':'',reason].filter(Boolean).join('；')||'先查看目前階段、負責人與待辦任務。';
}
export function financeSources(p:Partial<Project>){
 const number=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)?v:null;
 const basic=number(p.contract_amount),contract=number(p.source_projection?.finance?.contract_amount??p.source_finance?.合約總額);
 return {basic,contract,conflict:basic!==null&&contract!==null&&basic!==contract};
}
