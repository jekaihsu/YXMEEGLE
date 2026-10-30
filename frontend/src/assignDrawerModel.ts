import {NodeAssignmentError,type AssignablePerson,type AssignmentTask} from './nodeAssignmentApi';
export type AssignDraft={assignee:string;due:string};
export type AssignField=keyof AssignDraft;
export const FIELD_LABELS:Record<AssignField,string>={assignee:'執行人',due:'期限'};
export const draftOf=(task:AssignmentTask):AssignDraft=>({assignee:task.assignee?.open_id||'',due:task.deadline?.slice(0,10)||''});
export const changedFields=(base:AssignDraft,draft:AssignDraft)=>(Object.keys(FIELD_LABELS) as AssignField[]).filter(k=>base[k]!==draft[k]);
export function validateDraft(base:AssignDraft,draft:AssignDraft,people:Pick<AssignablePerson,'open_id'>[]):Partial<Record<AssignField,string>> {
 const errors:Partial<Record<AssignField,string>>={};
 if(draft.assignee!==base.assignee&&draft.assignee&&!people.some(p=>p.open_id===draft.assignee))errors.assignee='此人員已不在可指派名單，請重新選擇。';
 if(draft.due&&(!/^\d{4}-\d{2}-\d{2}$/.test(draft.due)||Number.isNaN(Date.parse(`${draft.due}T00:00:00Z`))||new Date(`${draft.due}T00:00:00Z`).toISOString().slice(0,10)!==draft.due))errors.due='請輸入有效日期（年-月-日）。';
 return errors;
}
export function patchOf(base:AssignDraft,draft:AssignDraft){
 return {...(draft.assignee!==base.assignee?{assignee_open_id:draft.assignee||null}:{}),...(draft.due!==base.due?{deadline:draft.due||null}:{})};
}
export type FailureKind='conflict'|'unknown'|'revoked'|'validation'|'other';
export function classifyFailure(error:unknown):{kind:FailureKind;fields:Partial<Record<AssignField,string>>} {
 if(!(error instanceof NodeAssignmentError))return {kind:'unknown',fields:{}};
 const code=error.code||'';
 if(code==='revision_conflict')return {kind:'conflict',fields:{}};
 if(error.status===401||error.status===403||['forbidden','writes_disabled','lark_permission'].includes(code))return {kind:'revoked',fields:{}};
 if(error.status===422){
  const fields:Partial<Record<AssignField,string>>={};
  if(error.fields.assignee_open_id)fields.assignee=error.fields.assignee_open_id;
  if(error.fields.deadline)fields.due=error.fields.deadline;
  return {kind:'validation',fields};
 }
 if(error.status===408||error.status>=500||['client_timeout','outcome_unknown','readback_mismatch','busy'].includes(code))return {kind:'unknown',fields:{}};
 return {kind:'other',fields:{}};
}
export type FieldOutcome='saved'|'unsaved'|'unchanged';
export function fieldOutcomes(base:AssignDraft,draft:AssignDraft,latest:AssignDraft):Record<AssignField,FieldOutcome> {
 const one=(k:AssignField):FieldOutcome=>base[k]===draft[k]?'unchanged':latest[k]===draft[k]?'saved':'unsaved';
 return {assignee:one('assignee'),due:one('due')};
}
export type Verdict='applied'|'partial'|'not_applied'|'moved';
export function verdict(base:AssignDraft,draft:AssignDraft,latest:AssignDraft,baseRevision:string,latestRevision:string):Verdict {
 const outcomes=Object.values(fieldOutcomes(base,draft,latest));
 const touched=outcomes.filter(o=>o!=='unchanged');
 if(touched.length&&touched.every(o=>o==='saved'))return 'applied';
 if(touched.includes('saved'))return 'partial';
 return latestRevision===baseRevision?'not_applied':'moved';
}
