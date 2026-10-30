import {SOP_ERROR_TEXT,type SopTask} from './sopTaskApi';
import {ACTIONS,type TaskAction} from './sopTaskModel';

export type ReasonKind='stale'|'finished'|'unassigned'|'dependency'|'stage_closed'|'no_permission';
export type Unavailable={kind:ReasonKind;reason:string;actions:{action:TaskAction|'edit';label:string}[]};
export type SopActionView={
 edit:{allowed:boolean;kind?:ReasonKind;reason:string};
 available:{action:TaskAction;label:string;reason:boolean}[];
 unavailable:Unavailable[];
 completion:{allowed:boolean;kind?:ReasonKind;reason:string};
};
const STALE='資料正在更新或可能已過期，請等重新整理完成後再操作。';
const NO_PERMISSION='你可查看此任務，但目前沒有這項操作的權限；權限由伺服器判定，本頁不會變更。';
const STAGE_CODES=['node_not_enrolled','node_already_started_or_finished','local_node_blocked','node_not_done_by_data','legacy_case_requires_opt_in','local_node_only'];
const DEPENDENCY_CODES=['applicability_unresolved','completion_evidence_missing','task_reopen_required'];
export function classifyCode(code:string|null|undefined):{kind:ReasonKind;reason:string}|undefined {
 if(!code)return undefined;
 const text=SOP_ERROR_TEXT[code]||'目前條件尚未滿足';
 if(code==='participant_unresolved')return {kind:'unassigned',reason:`尚未有可用的執行人：${text}`};
 if(STAGE_CODES.includes(code))return {kind:'stage_closed',reason:`流程階段尚未開放：${text}`};
 if(DEPENDENCY_CODES.includes(code))return {kind:'dependency',reason:`前置條件未完成：${text}`};
 return {kind:'dependency',reason:text};
}
const RELEVANT:Record<string,TaskAction[]>={pending:['start','block','complete','archive'],in_progress:['block','reset','complete','archive'],blocked:['resume','reset','complete','archive'],done:['reopen','archive'],archived:['restore']};
export function sopActionView(task:SopTask,fresh:boolean):SopActionView {
 const allowed=(a:string)=>task.allowedActions.includes(a);
 const editReason=():{kind:ReasonKind;reason:string}=>{
  if(!fresh)return {kind:'stale',reason:STALE};
  if(task.state==='archived')return {kind:'finished',reason:'此任務已封存；需先「還原」才能修改。'};
  if(task.state==='done')return {kind:'finished',reason:'此任務已完成；需先「重新開啟」才能修改。'};
  return classifyCode(task.assignmentBlockedReason)||{kind:'no_permission',reason:NO_PERMISSION};
 };
 const edit:SopActionView['edit']=allowed('edit')&&fresh?{allowed:true,reason:''}:{allowed:false,...editReason()};
 const why=(action:TaskAction):{kind:ReasonKind;reason:string}=>{
  if(!fresh)return {kind:'stale',reason:STALE};
  if(action==='complete'){
   const coded=classifyCode(task.completionBlockedReason);if(coded)return coded;
   if(!task.participants.executor)return {kind:'unassigned',reason:'尚未指派執行人，指派後才能完成。'};
  }else{const coded=classifyCode(task.assignmentBlockedReason);if(coded&&action!=='archive'&&action!=='restore')return coded}
  return {kind:'no_permission',reason:NO_PERMISSION};
 };
 const relevant=RELEVANT[task.state]||[];
 const available=ACTIONS.filter(a=>a.action!=='complete'&&allowed(a.action)&&fresh&&relevant.includes(a.action)).map(a=>({action:a.action,label:a.label,reason:a.reason}));
 const groups=new Map<string,Unavailable>();
 if(!edit.allowed){const key=`${edit.kind}|${edit.reason}`;groups.set(key,{kind:edit.kind||'no_permission',reason:edit.reason,actions:[{action:'edit',label:'編輯任務內容'}]})}
 for(const a of ACTIONS){
  if(!relevant.includes(a.action)||(allowed(a.action)&&fresh))continue;
  const r=why(a.action),key=`${r.kind}|${r.reason}`;
  const group=groups.get(key)||{kind:r.kind,reason:r.reason,actions:[]};group.actions.push({action:a.action,label:a.label});groups.set(key,group);
 }
 const completeAllowed=allowed('complete')&&fresh&&!task.completionBlockedReason;
 const completion=completeAllowed?{allowed:true,reason:''}:{allowed:false,...why('complete')};
 return {edit,available,unavailable:[...groups.values()],completion};
}
export const uniqueReasons=(reasons:readonly string[])=>[...new Set(reasons.map(r=>r.trim()).filter(Boolean))];
