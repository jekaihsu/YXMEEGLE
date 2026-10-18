import {api} from './api.ts';
const object=(v:unknown):Record<string,unknown>=>v!==null&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:{};
const str=(v:unknown)=>typeof v==='string'?v:'';
const list=(v:unknown):unknown[]=>Array.isArray(v)?v:[];
const strings=(v:unknown)=>list(v).filter((x):x is string=>typeof x==='string');
const num=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)?v:0;
function member<T extends string>(v:unknown,values:readonly T[]):T|'unknown' {return values.find(x=>x===v)??'unknown'}
export const commandLabels={pending:'處理中',committed:'已確認',outcome_unknown:'結果不明',reconciliation_required:'需對帳',failed:'失敗',rejected:'已拒絕',unknown:'命令狀態待核實'};
export type CommandState=keyof typeof commandLabels;
export const planningLabels={unassigned:'未分配',draft:'草稿',pending_approval:'待核定',publishing:'發布中',confirmed:'已確認',conflict:'衝突',cancelled:'已取消',unknown:'排程待核實'};
export const seatLabels={group_leader_confirmed:'組長確認',manager_review:'經理審核',pm_final:'PM 最終確認',unknown:'核准席位待核實'};
export const actionLabels={assign:'排班',reassign:'改派',edit_detail:'編輯',approve:'核准',return:'退回',reconcile:'重新對帳',cancel_draft:'取消草稿'};
export type Action=keyof typeof actionLabels;
export type Person={person_ref:string;name:string;avatar_url:string};
const person=(v:unknown):Person=>{const x=object(v);return {person_ref:str(x.person_ref),name:str(x.name),avatar_url:str(x.avatar_url)}};
export type Proposal={task_id?:string;project_ref:string;case_ref:string;title:string;content:string;phase:string;kind:'execution'|'obligation'|'unknown';package_id:string;parent_task_ref:string;group:string;primary_owner:string;crew:string[];start:string;end:string;est_person_hours:number;instruments:string[];vehicles:string[];department:string;deadline:string;note:string;manual_verifications:Record<string,string>};
export function normalizeProposal(value:unknown):Proposal {
 const x=object(value),owner=str(x.primary_owner),manual=object(x.manual_verifications);
 return {task_id:str(x.task_id)||undefined,project_ref:str(x.project_ref),case_ref:str(x.case_ref),title:str(x.title),content:str(x.content),phase:member(x.phase??'正式',['正式','接案前']),kind:member(x.kind,['execution','obligation']),package_id:str(x.package_id),parent_task_ref:str(x.parent_task_ref),group:str(x.group),primary_owner:owner,crew:[...new Set([owner,...strings(x.crew)].filter(Boolean))],start:str(x.start),end:str(x.end),est_person_hours:num(x.est_person_hours),instruments:[...new Set(strings(x.instruments))],vehicles:[...new Set(strings(x.vehicles))],department:str(x.department),deadline:str(x.deadline),note:str(x.note),manual_verifications:Object.fromEntries(Object.entries(manual).filter((entry):entry is [string,string]=>typeof entry[1]==='string'))};
}
export const personHours=(p:Proposal)=>Math.max(0,(Date.parse(p.end)-Date.parse(p.start))/3600000)*new Set([p.primary_owner,...p.crew].filter(Boolean)).size;
export function validateProposal(p:Proposal):string[] {
 const errors=[];
 if(!p.title.trim())errors.push('請填寫工作標題。');
 if(!p.project_ref.trim())errors.push('請填寫專案編號。');
 if(!p.primary_owner)errors.push('請選擇負責人。');
 if(!Number.isFinite(Date.parse(p.start))||!Number.isFinite(Date.parse(p.end)))errors.push('請填寫完整開始與結束時間。');
 else if(Date.parse(p.end)<=Date.parse(p.start))errors.push('結束時間必須晚於開始時間。');
 if([p.start,p.end].some(t=>Number.isFinite(Date.parse(t))&&Date.parse(t)%900000!==0))errors.push('開始與結束時間須為 15 分鐘刻度。');
 if(!Number.isFinite(p.est_person_hours)||p.est_person_hours<0)errors.push('預估人時必須為非負數。');
 if(p.phase==='unknown')errors.push('請確認任務階段。');
 if(p.kind==='unknown')errors.push('請確認任務種類。');
 return errors;
}
export type Command={command_id:string;state:CommandState;revision:number;task_record_id:string;created_at:string;updated_at:string;next_action:'reconcile'|'none'|'unknown';receipt:string};
export function parseCommand(value:unknown):Command {const envelope=object(value),x=Object.keys(object(envelope.command)).length?object(envelope.command):envelope;return {command_id:str(x.command_id),state:member(x.state,Object.keys(commandLabels) as CommandState[]),revision:num(x.revision),task_record_id:str(x.task_record_id),created_at:str(x.created_at),updated_at:str(x.updated_at),next_action:member(envelope.next_action??x.next_action,['reconcile','none']),receipt:typeof x.receipt==='string'?x.receipt:JSON.stringify(x.receipt??envelope.receipt??null)}}
export type WorkRow={task_id:string;title:string;content:string;case:{ref:string;code:string;name:string};project_id:string;package_id:string;kind:Proposal['kind'];phase:string;status:string;planning_status:keyof typeof planningLabels;acceptance_status:string;acceptance_summary:string;owner:Person;crew:Person[];interval:{start:string;end:string;precision:string};instruments:{ref:string;label:string}[];vehicles:{ref:string;label:string}[];deadline:string;est_person_hours:number;revision:number;command:Command|null;source:string;needs_me:string[];allowed_actions:Action[];parent_task_ref:string;department:string;scope_version:string;rule_version:string;evidence_version:string;read_back_at:string;node_position:string;preview_id:string};
const resources=(value:unknown)=>list(value).map(v=>{const x=object(v);return {ref:str(x.ref),label:str(x.label)}});
function parseRow(value:unknown):WorkRow {const x=object(value),c=object(x.case),i=object(x.interval);return {task_id:str(x.task_id),title:str(x.title),content:str(x.content),case:{ref:str(c.ref),code:str(c.code),name:str(c.name)},project_id:str(x.project_id),package_id:str(x.package_id),kind:member(x.kind,['obligation','execution']),phase:member(x.phase,['正式','接案前']),status:member(x.status,['待處理','進行中','已完成','取消']),planning_status:member(x.planning_status,Object.keys(planningLabels) as (keyof typeof planningLabels)[]),acceptance_status:member(x.acceptance_status,['草稿','審核中','已接受','已退回','已取代']),acceptance_summary:str(x.acceptance_summary),owner:person(x.owner),crew:list(x.crew).map(person),interval:{start:str(i.start),end:str(i.end),precision:member(i.precision,['date','datetime'])},instruments:resources(x.instruments),vehicles:resources(x.vehicles),deadline:str(x.deadline),est_person_hours:num(x.est_person_hours),revision:num(x.revision),command:x.command?parseCommand(x.command):null,source:member(x.source,['v4_task']),needs_me:strings(x.needs_me),allowed_actions:strings(x.allowed_actions).filter((v):v is Action=>Object.hasOwn(actionLabels,v)),parent_task_ref:str(x.parent_task_ref),department:str(x.department),scope_version:typeof x.scope_version==='number'?String(num(x.scope_version)):str(x.scope_version),rule_version:str(x.rule_version),evidence_version:str(x.evidence_version),read_back_at:str(x.read_back_at),node_position:str(x.node_position),preview_id:str(x.preview_id)}}
export type Work={rows:WorkRow[];needs_me:WorkRow[];progress:{status:Record<string,number>;planning_status:Record<string,number>};fetched_at:string;states:string[]};
export function parseWork(value:unknown):Work {const x=object(value);if(!Array.isArray(x.rows))throw Error('工作進度回應格式不正確。');const source=object(x.source),quality=object(source.quality),states=strings(quality.states).map(v=>member(v,['complete','partial','stale','read_failed','forbidden','unknown']));const rows=states.includes('forbidden')?[]:x.rows.map(parseRow).filter((r,i,all)=>r.task_id&&all.findIndex(other=>other.task_id===r.task_id)===i);if(!states.includes('forbidden')&&rows.length!==x.rows.length)states.push('partial');const count=(key:'status'|'planning_status')=>rows.reduce<Record<string,number>>((out,r)=>{out[r[key]]=(out[r[key]]??0)+1;return out},{});return {rows,needs_me:rows.filter(r=>r.needs_me.length),progress:{status:count('status'),planning_status:count('planning_status')},fetched_at:str(source.fetched_at),states:states.length?states:['unknown']}}
export type Preview={preview_id:string;preview_hash:string;expires_at:string;proposal:Proposal;source_vector:{schedule:string;tasks:string;schema:string};feasibility:{kind:string;ref:string;label:string;state:string;reasons:string[]}[];conflicts:{kind:string;ref:string;other_slot_or_task:string;start:string;end:string}[];warnings:string[];required_seats:{seat:keyof typeof seatLabels;holder:Person;status:string;reason:string;actor:string}[];can_commit:boolean;blockers:string[]};
export function parsePreview(value:unknown):Preview {
 const x=object(value),s=object(x.source_vector);
 const seats=list(x.required_seats).map(v=>{const a=object(v);return {seat:member(a.seat,Object.keys(seatLabels) as (keyof typeof seatLabels)[]),holder:person(a.holder),status:member(a.status,['pending','accepted','returned']),reason:str(a.reason),actor:str(a.actor)}});
 const feasibility=list(x.feasibility).map(v=>{const a=object(v);return {kind:member(a.kind,['person','instrument','vehicle']),ref:str(a.ref),label:str(a.label),state:member(a.state??a.feasibility,['feasible','conflict','unavailable','unknown']),reasons:strings(a.reasons)}});
 return {preview_id:str(x.preview_id),preview_hash:str(x.preview_hash),expires_at:str(x.expires_at),proposal:normalizeProposal(x.proposal),source_vector:{schedule:str(object(s.schedule).fetched_at??s.schedule_fetched_at),tasks:str(object(s.tasks).fetched_at??s.tasks_fetched_at),schema:str(s.schema_version)||String(num(s.schema_version))},feasibility,conflicts:list(x.conflicts).map(v=>{const a=object(v),i=object(a.interval);return {kind:str(a.kind),ref:str(a.ref),other_slot_or_task:str(a.other_slot_or_task),start:str(i.start),end:str(i.end)}}),warnings:strings(x.warnings),required_seats:seats,can_commit:x.can_commit===true&&!!str(x.preview_hash)&&!!str(x.preview_id)&&seats.every(a=>a.seat!=='unknown'&&a.status==='accepted'&&!!a.holder.person_ref&&!!a.actor)&&new Set(seats.map(a=>a.actor)).size===seats.length&&feasibility.length>0&&feasibility.every(a=>a.kind!=='unknown'&&(a.state==='feasible'||a.state==='unknown'&&!!normalizeProposal(x.proposal).manual_verifications[a.ref]?.trim())),blockers:strings(x.blockers)};
}
export const taskFields=['專案編號','工程確認單','任務階段','任務種類','工作包編號','父義務','範圍版本','規則版本','證據版本','預定開始','預定結束','預估人時','組員','使用儀器','使用車輛','排程狀態','排程版本','命令編號','讀回時間','成果接受狀態','接受摘要'];
export function rowProposal(r:WorkRow):Proposal {return normalizeProposal({task_id:r.task_id,project_ref:r.project_id,case_ref:r.case.ref,title:r.title,content:r.content,phase:r.phase,kind:r.kind,package_id:r.package_id,parent_task_ref:r.parent_task_ref,primary_owner:r.owner.person_ref,crew:r.crew.map(p=>p.person_ref),start:r.interval.start,end:r.interval.end,est_person_hours:r.est_person_hours,instruments:r.instruments.map(p=>p.ref),vehicles:r.vehicles.map(p=>p.ref),department:r.department,deadline:r.deadline})}
export type SavedDraft={draft_id:string;proposal:Proposal;preview_id:string;command_id:string;saved_at:string};
export function parseDraft(value:unknown):SavedDraft {const x=object(value);return {draft_id:str(x.draft_id),proposal:normalizeProposal(x.proposal),preview_id:str(x.preview_id),command_id:str(x.command_id),saved_at:str(x.saved_at)}}
export function parseDrafts(value:unknown):SavedDraft[] {return list(object(value).drafts).map(parseDraft)}
export function readLocalDrafts(raw:string|null):SavedDraft[] {try{return list(JSON.parse(raw??'[]')).map(parseDraft).filter(d=>d.draft_id)}catch{return []}}
export function needLabel(reason:string):string {if(reason.startsWith('approve_seat:'))return `等待${seatLabels[member(reason.split(':')[1],Object.keys(seatLabels) as (keyof typeof seatLabels)[])]}`;if(reason.startsWith('verify_unknown:'))return '資格或請假待人工核實';return ({confirm_assignment:'等待指派確認',reconcile_command:'命令需要對帳',review_returned:'退回內容待檢視'} as Record<string,string>)[reason]??'需要核實未識別事項'}
export function blockerLabel(code:string):string {return ({unknown_feasibility:'資格或請假尚未核實',approval_not_configured:'尚未設定核准席位持有人',approvals_required:'尚待必要席位核准',returned:'此預覽已被退回，請修改後重新預覽',conflict:'人員或資源時段衝突',preview_expired:'預覽已過期，請重新預覽',source_changed:'來源已更新，請重新預覽'} as Record<string,string>)[code]??`尚未通過的檢核（${code}），請管理員核實`}
export async function dispatchRequest(path:string,signal:AbortSignal,body?:unknown):Promise<unknown> {
 let status=0;
 const result=await api<unknown>(path,{signal,cache:'no-store',timeoutMs:30000,...(body===undefined?{}:{method:'POST',body:JSON.stringify(body)})},()=>!signal.aborted,value=>{status=value});
 if(status!==202||(path!==dispatchPaths.commits&&!path.startsWith('/api/v2/commands/')))return result;
 const envelope=object(result),command=object(envelope.command);
 return envelope.command?{...envelope,command:{...command,state:command.state==='committed'?'pending':command.state}}:{...envelope,state:envelope.state==='committed'?'pending':envelope.state};
}

export const dispatchPaths={
 previews:'/api/v2/dispatch/previews',commits:'/api/v2/dispatch/commits',drafts:'/api/v2/dispatch/drafts',
 work:(query:URLSearchParams)=>`/api/v2/dispatch/work?${query}`,
 preview:(id:string)=>`/api/v2/dispatch/previews/${encodeURIComponent(id)}`,
 decisions:(id:string)=>`/api/v2/dispatch/previews/${encodeURIComponent(id)}/decisions`,
 command:(id:string)=>`/api/v2/commands/${encodeURIComponent(id)}`,
 reconcile:(id:string)=>`/api/v2/commands/${encodeURIComponent(id)}/reconcile`,
 cancelDraft:(id:string)=>`/api/v2/dispatch/drafts/${encodeURIComponent(id)}/cancel`
};
