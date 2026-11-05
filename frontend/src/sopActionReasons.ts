import {SOP_ERROR_TEXT,type SopTask} from './sopTaskApi';
import {ACTIONS,type TaskAction} from './sopTaskModel';

export type ReasonKind='stale'|'finished'|'unassigned'|'dependency'|'stage_closed'|'no_permission'|'writes_disabled'|'server_reason'|'no_reason';
export type Unavailable={kind:ReasonKind;reason:string;hint?:string;actions:{action:TaskAction|'edit';label:string}[]};
export type SopActionView={
 edit:{allowed:boolean;kind?:ReasonKind;reason:string};
 available:{action:TaskAction;label:string;reason:boolean}[];
 unavailable:Unavailable[];
 completion:{allowed:boolean;kind?:ReasonKind;reason:string};
};
const STALE='資料正在更新或可能已過期，請等重新整理完成後再操作。';
export const NO_REASON='系統未提供原因：伺服器目前沒有開放這項操作，也沒有說明原因。';
const STAGE_CODES=['node_not_enrolled','node_already_started_or_finished','local_node_blocked','node_not_done_by_data','legacy_case_requires_opt_in','local_node_only'];
const DEPENDENCY_CODES=['applicability_unresolved','completion_evidence_missing','task_reopen_required'];
const PERMISSION_CODES=['forbidden','identity_forbidden','lark_permission','writes_disabled'];
// Only server-supplied codes become a stated reason; an unknown code is quoted, never paraphrased into a rule.
export function classifyCode(code:string|null|undefined):{kind:ReasonKind;reason:string}|undefined {
 if(!code)return undefined;
 const text=SOP_ERROR_TEXT[code];
 if(code==='participant_unresolved')return {kind:'unassigned',reason:`尚未有可用的執行人：${text}`};
 if(STAGE_CODES.includes(code))return {kind:'stage_closed',reason:`流程階段尚未開放：${text}`};
 if(DEPENDENCY_CODES.includes(code))return {kind:'dependency',reason:`前置條件未完成：${text}`};
 if(code==='import_unavailable')return {kind:'writes_disabled',reason:`目前寫入已停用：${text}`};
 if(PERMISSION_CODES.includes(code)||/forbid|permission/.test(code))return {kind:'no_permission',reason:`沒有權限：${text||`伺服器回報 ${code}`}`};
 return {kind:'server_reason',reason:text?`伺服器回報：${text}`:`伺服器回報原因代碼「${code}」，尚無對應說明。`};
}
const RELEVANT:Record<string,TaskAction[]>={pending:['start','block','complete','archive'],in_progress:['block','reset','complete','archive'],blocked:['resume','reset','complete','archive'],done:['reopen','archive'],archived:['restore']};
export function sopActionView(task:SopTask,fresh:boolean,owner?:string):SopActionView {
 const hint=(kind:ReasonKind)=>kind==='no_reason'||kind==='stale'?`可先按「重新整理」重新讀取（不會變更任何狀態）${owner?`；仍無法操作時請聯絡節點負責人 ${owner}`:''}。`:undefined;
 const allowed=(a:string)=>task.allowedActions.includes(a);
 const editReason=():{kind:ReasonKind;reason:string}=>{
  if(!fresh)return {kind:'stale',reason:STALE};
  if(task.state==='archived')return {kind:'finished',reason:'此任務已封存。如需修改，請使用「還原」（需有此操作）。'};
  if(task.state==='done')return {kind:'finished',reason:'此任務已完成。如需修改，請使用「重新開啟」（需有此操作）。'};
  return classifyCode(task.assignmentBlockedReason)||{kind:'no_reason',reason:NO_REASON};
 };
 const edit:SopActionView['edit']=allowed('edit')&&fresh?{allowed:true,reason:''}:{allowed:false,...editReason()};
 const why=(action:TaskAction):{kind:ReasonKind;reason:string}=>{
  if(!fresh)return {kind:'stale',reason:STALE};
  const coded=action==='complete'?classifyCode(task.completionBlockedReason):action==='archive'||action==='restore'?undefined:classifyCode(task.assignmentBlockedReason);
  return coded||{kind:'no_reason',reason:NO_REASON};
 };
 const relevant=RELEVANT[task.state]||[];
 const available=ACTIONS.filter(a=>a.action!=='complete'&&allowed(a.action)&&fresh&&relevant.includes(a.action)).map(a=>({action:a.action,label:a.label,reason:a.reason}));
 const groups=new Map<string,Unavailable>();
 if(!edit.allowed){const key=`${edit.kind}|${edit.reason}`;groups.set(key,{kind:edit.kind||'no_reason',reason:edit.reason,hint:hint(edit.kind||'no_reason'),actions:[{action:'edit',label:'編輯任務內容'}]})}
 for(const a of ACTIONS){
  if(!relevant.includes(a.action)||(allowed(a.action)&&fresh))continue;
  const r=why(a.action),key=`${r.kind}|${r.reason}`;
  const group=groups.get(key)||{kind:r.kind,reason:r.reason,hint:hint(r.kind),actions:[]};group.actions.push({action:a.action,label:a.label});groups.set(key,group);
 }
 const completeAllowed=allowed('complete')&&fresh&&!task.completionBlockedReason;
 const completion=completeAllowed?{allowed:true,reason:''}:{allowed:false,...why('complete')};
 return {edit,available,unavailable:[...groups.values()],completion};
}
export const uniqueReasons=(reasons:readonly string[])=>[...new Set(reasons.map(r=>r.trim()).filter(Boolean))];
