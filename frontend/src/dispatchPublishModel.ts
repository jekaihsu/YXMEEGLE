import {api,ApiError} from './api.ts';
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
export const workSourceLabels={v4_task:'已寫入任務',workbench_preview:'預覽提案',workbench_draft:'未發布草稿',workbench_command:'發布命令',unknown:'來源待核實'};
export const actionLabels={assign:'排班',reassign:'改派',edit_detail:'編輯',approve:'核准',return:'退回',reconcile:'重新對帳',cancel_draft:'取消草稿',review_preview:'檢視派工提案'};
export type Action=keyof typeof actionLabels;
export type Person={person_ref:string;name:string;avatar_url:string;open_id:string};
const person=(v:unknown):Person=>{const x=object(v);return {person_ref:str(x.person_ref),name:str(x.name),avatar_url:str(x.avatar_url),open_id:str(x.open_id)}};
export type Proposal={task_id?:string;project_ref:string;case_ref:string;title:string;content:string;phase:string;kind:'execution'|'obligation'|'unknown';package_id:string;parent_task_ref:string;primary_owner:string;crew:string[];start:string;end:string;est_person_hours:number;instruments:string[];vehicles:string[];department:string;deadline:string;manual_verifications:Record<string,string>};
export function normalizeProposal(value:unknown):Proposal {
 const x=object(value),owner=str(x.primary_owner),manual=object(x.verifications??x.manual_verifications);
 return {task_id:str(x.task_id)||undefined,project_ref:str(x.project_ref),case_ref:str(x.case_ref),title:str(x.title),content:str(x.content),phase:member(({formal:'正式',intake:'接案前'} as Record<string,string>)[str(x.phase)]??x.phase??'正式',['正式','接案前']),kind:member(x.kind,['execution','obligation']),package_id:str(x.package_id),parent_task_ref:str(x.parent_task_ref),primary_owner:owner,crew:[...new Set([owner,...strings(x.crew)].filter(Boolean))],start:str(x.start),end:str(x.end),est_person_hours:num(x.est_person_hours),instruments:[...new Set(strings(x.instruments))],vehicles:[...new Set(strings(x.vehicles))],department:str(x.department),deadline:str(x.deadline),manual_verifications:Object.fromEntries(Object.entries(manual).filter((entry):entry is [string,string]=>typeof entry[1]==='string'))};
}
export function proposalBody(p:Proposal) {
 const optional=(v:string)=>v||null;
 return {task_id:p.task_id??null,project_ref:p.project_ref,case_ref:optional(p.case_ref),title:p.title,content:p.content,
  phase:p.phase==='正式'?'formal':p.phase==='接案前'?'intake':null,kind:p.kind==='unknown'?null:p.kind,package_id:optional(p.package_id),parent_task_ref:optional(p.parent_task_ref),
  department:optional(p.department),primary_owner:optional(p.primary_owner),crew:p.crew,start:optional(p.start),end:optional(p.end),est_person_hours:p.est_person_hours,
  instruments:p.instruments,vehicles:p.vehicles,deadline:optional(p.deadline),
  verifications:Object.fromEntries(Object.entries(p.manual_verifications).filter(([key,reason])=>reason.trim()&&[...p.crew.map(ref=>`person:${ref}`),...p.instruments.map(ref=>`instrument:${ref}`),...p.vehicles.map(ref=>`vehicle:${ref}`)].includes(key)))};
}
export const previewBody=(p:Proposal,draftId?:string)=>({...proposalBody(p),...(draftId?{draft_id:draftId}:{})});
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
export type Command={command_id:string;state:CommandState;revision:number;task_record_id:string;created_at:string;updated_at:string;next_action:'reconcile'|'none'|'unknown';receipt:string;issue:string;read_back_at:string};
export function parseCommand(value:unknown):Command {const envelope=object(value),x=Object.keys(object(envelope.command)).length?object(envelope.command):envelope;return {command_id:str(x.command_id),state:member(x.state,Object.keys(commandLabels) as CommandState[]),revision:num(x.revision),task_record_id:str(x.task_id??x.task_record_id??object(envelope.receipt).record_id),created_at:str(x.created_at),updated_at:str(x.updated_at),next_action:member(envelope.next_action??x.next_action,['reconcile','none']),issue:str(object(envelope.receipt).error)||(list(object(envelope.receipt).mismatches).length||list(object(envelope.receipt).duplicates).length||list(object(envelope.receipt).changed_since_commit).length?'readback_mismatch':''),read_back_at:str(object(envelope.receipt).read_back_at),receipt:typeof x.receipt==='string'?x.receipt:JSON.stringify(x.receipt??envelope.receipt??null)}}
export type WorkRow={row_id:string;draft_id:string;task_id:string;title:string;content:string;case:{ref:string;code:string;name:string};project_id:string;package_id:string;kind:Proposal['kind'];phase:string;status:string;planning_status:keyof typeof planningLabels;acceptance_status:string;acceptance_summary:string;owner:Person;crew:Person[];interval:{start:string;end:string;precision:string};instruments:{ref:string;label:string}[];vehicles:{ref:string;label:string}[];deadline:string;est_person_hours:number|null;revision:number|null;command:Command|null;source:keyof typeof workSourceLabels;needs_me:string[];allowed_actions:Action[];parent_task_ref:string;department:string;scope_version:string;rule_version:string;evidence_version:string;read_back_at:string;node_position:string;preview_id:string};
const resources=(value:unknown)=>list(value).map(v=>{const x=object(v);return {ref:str(x.ref),label:str(x.label)}});
function parseRow(value:unknown):WorkRow {const x=object(value),c=object(x.case),i=object(x.interval);return {row_id:str(x.task_id)||str(x.preview_id)||str(x.draft_id)||str(object(x.command).command_id),draft_id:str(x.draft_id),task_id:str(x.task_id),title:str(x.title),content:str(x.content),case:{ref:str(c.ref),code:str(c.code),name:str(c.name)},project_id:str(x.project_id),package_id:str(x.package_id),kind:member(x.kind,['obligation','execution']),phase:member(({formal:'正式',intake:'接案前'} as Record<string,string>)[str(x.phase)]??x.phase,['正式','接案前']),status:member(x.status,['待處理','進行中','已完成','取消']),planning_status:member(x.planning_status,Object.keys(planningLabels) as (keyof typeof planningLabels)[]),acceptance_status:member(x.acceptance_status,['草稿','審核中','已接受','已退回','已取代']),acceptance_summary:str(x.acceptance_summary),owner:person(x.owner),crew:list(x.crew).map(person),interval:{start:str(i.start),end:str(i.end),precision:member(i.precision,['date','datetime'])},instruments:resources(x.instruments),vehicles:resources(x.vehicles),deadline:str(x.deadline),est_person_hours:typeof x.est_person_hours==='number'?num(x.est_person_hours):null,revision:typeof x.revision==='number'?num(x.revision):null,command:x.command?parseCommand(x.command):null,source:member(x.source,['v4_task','workbench_preview','workbench_draft','workbench_command']),needs_me:strings(x.needs_me),allowed_actions:strings(x.allowed_actions).filter((v):v is Action=>Object.hasOwn(actionLabels,v)),parent_task_ref:str(x.parent_task_ref),department:str(x.department),scope_version:String(object(x.versions).scope??x.scope_version??''),rule_version:String(object(x.versions).rule??x.rule_version??''),evidence_version:String(object(x.versions).evidence??x.evidence_version??''),read_back_at:str(x.readback_at??x.read_back_at),node_position:str(object(x.node).label??x.node_position),preview_id:str(x.preview_id)}}
export type Work={rows:WorkRow[];needs_me:WorkRow[];progress:{status:Record<string,number>;planning_status:Record<string,number>};fetched_at:string;states:string[];gaps:{draft_id:string;field:string}[]};
export function parseWork(value:unknown):Work {const x=object(value);if(!Array.isArray(x.rows))throw Error('工作進度回應格式不正確。');const source=object(x.source),quality=object(source.quality),states=strings(quality.states).map(v=>member(v,['complete','partial','stale','read_failed','forbidden','unknown']));const gaps=list(x.gaps).map(v=>({draft_id:str(object(v).draft_id),field:str(object(v).field)}));if(gaps.length&&!states.includes('partial'))states.push('partial');const rows=states.includes('forbidden')?[]:x.rows.map(parseRow).filter((r,i,all)=>r.row_id&&all.findIndex(other=>other.row_id===r.row_id)===i);if(!states.includes('forbidden')&&rows.length!==x.rows.length)states.push('partial');const count=(key:'status'|'planning_status')=>rows.reduce<Record<string,number>>((out,r)=>{out[r[key]]=(out[r[key]]??0)+1;return out},{});return {gaps,rows,needs_me:rows.filter(r=>r.needs_me.length),progress:{status:count('status'),planning_status:count('planning_status')},fetched_at:str(source.fetched_at),states:states.length?states:['unknown']}}
export type Seat=keyof typeof seatLabels;
export type ApprovalSeat={seat:Seat;holders:string[];names:string[];configured:boolean;status:string;reason:string;actor:string};
export type Preview={preview_id:string;preview_hash:string;expires_at:string;proposal:Proposal;source_vector:{schedule:string;tasks:string;schema:string};feasibility:{kind:string;ref:string;key:string;label:string;state:string;reasons:string[]}[];conflicts:{kind:string;ref:string;other_slot_or_task:string;start:string;end:string}[];warnings:string[];required_seats:ApprovalSeat[];my_seats:string[];can_commit:boolean;blockers:string[];hours:number;booked_person_hours:number};
export function parsePreview(value:unknown):Preview {
 const x=object(value),s=object(x.source_vector);
 const seats=list(x.required_seats).map(v=>{
  const a=object(v),holder=object(a.holder);
  const holders=strings(a.holders).length?strings(a.holders):[str(holder.open_id??holder.person_ref)].filter(Boolean);
  const peopleNames=list(a.people??a.holder_people).map(v=>str(object(v).name)).filter(Boolean);
  const names=strings(a.names).length?strings(a.names):peopleNames.length?peopleNames:strings(a.holder_names).length?strings(a.holder_names):[str(holder.name)].filter(Boolean);
  return {seat:member(a.seat,Object.keys(seatLabels) as Seat[]),holders,names,configured:typeof a.configured==='boolean'?a.configured:holders.length>0,
   status:member(a.decision??a.status??'pending',['pending','accepted','returned']),reason:str(a.reason),actor:str(a.actor)};
 });
 const checks=Array.isArray(x.crew)||Array.isArray(x.resources)?[...list(x.crew).map(v=>({...object(v),kind:'person',ref:object(v).person_ref,label:object(v).name})),...list(x.resources)]:list(x.feasibility);
 const feasibility=checks.map(v=>{const a=object(v),kind=member(a.kind,['person','instrument','vehicle']),ref=str(a.ref);return {kind,ref,key:`${kind}:${ref}`,label:str(a.label)||ref,state:member(a.feasibility??a.state,['feasible','conflict','unavailable','unknown']),reasons:strings(a.reasons)}});
 const proposal=normalizeProposal(x.proposal),blockers=strings(x.blockers);
 for(const seat of seats)if(!seat.configured&&!blockers.includes(`approval_not_configured:${seat.seat}`))blockers.push(`approval_not_configured:${seat.seat}`);
 return {preview_id:str(x.preview_id),preview_hash:str(x.preview_hash),expires_at:str(x.expires_at),proposal,
 source_vector:{schedule:str(object(s.schedule).fetched_at??s.schedule??s.schedule_fetched_at),tasks:str(object(s.tasks).fetched_at??s.tasks??s.tasks_fetched_at),schema:String(s.schema_version??'')},
 feasibility,conflicts:list(x.conflicts).map(v=>{const a=object(v),i=object(a.interval);return {kind:str(a.kind),ref:str(a.ref),other_slot_or_task:str(object(a.other).title??a.title??a.other_slot_or_task??a.task_id),start:str(i.start),end:str(i.end)}}),
 warnings:strings(x.warnings),required_seats:seats,my_seats:strings(x.my_seats),hours:num(x.hours),booked_person_hours:num(x.booked_person_hours),
 can_commit:x.can_commit===true&&!!str(x.preview_hash)&&!!str(x.preview_id)&&!blockers.length&&seats.every(a=>a.seat!=='unknown'&&a.status==='accepted'&&a.configured&&!!a.actor)&&new Set(seats.map(a=>a.actor)).size===seats.length&&feasibility.length>0&&feasibility.every(a=>a.kind!=='unknown'&&(a.state==='feasible'||a.state==='unknown'&&!!proposal.manual_verifications[a.key]?.trim())),blockers};
}
export type DispatchOptions={people:(Person&{active:boolean;has_lark_account:boolean})[];instruments:{ref:string;label:string;feasibility:string}[];vehicles:{ref:string;label:string;feasibility:string}[];cases:{ref:string;code:string;name:string}[];departments:string[];seats:{seat:Seat;configured:boolean;names:string[];by_department:Record<string,string[]>}[];unavailable:string[]};
export function parseOptions(value:unknown):DispatchOptions {
 const x=object(value);if(!Array.isArray(x.people)||!Array.isArray(x.instruments)||!Array.isArray(x.vehicles)||!Array.isArray(x.cases))throw Error('派工選項回應格式不正確。');
 const resource=(v:unknown)=>list(v).map(v=>{const a=object(v);return {ref:str(a.ref),label:str(a.label)||str(a.ref),feasibility:member(a.feasibility,['feasible','unavailable','unknown'])}});
 const seats=list(x.seats).map(v=>{
  const a=object(v);return {seat:member(a.seat,Object.keys(seatLabels) as Seat[]),configured:a.configured===true,
   names:list(a.holders).map(v=>str(object(v).name)).filter(Boolean),
   by_department:Object.fromEntries(Object.entries(object(a.by_department)).map(([key,v])=>[key,list(v).map(p=>str(object(p).name)).filter(Boolean)]))};
 });
 return {people:x.people.map(v=>({...person(v),active:object(v).active===true,has_lark_account:object(v).has_lark_account===true})),instruments:resource(x.instruments),vehicles:resource(x.vehicles),cases:x.cases.map(v=>{const a=object(v);return {ref:str(a.ref),code:str(a.code),name:str(a.name)}}),departments:[...new Set([...strings(x.departments),...seats.flatMap(s=>Object.keys(s.by_department))])],seats,unavailable:Object.entries(object(x.joins)).filter(([,v])=>v!=='ok').map(([k])=>k)};
}
export function parseTaskForm(value:unknown):{proposal:Proposal;row:WorkRow;unmapped_people:string[]} {
 const x=object(value);if(!x.proposal||!x.row)throw Error('任務表單回應格式不正確。');
 const system=object(x.system),row=parseRow({...object(x.row),scope_version:system.scope_version,rule_version:system.rule_version,evidence_version:system.evidence_version,revision:system.revision,readback_at:system.readback_at,acceptance_status:system.acceptance_status,acceptance_summary:system.acceptance_summary,command:system.command_id?{command_id:system.command_id,state:'committed'}:object(x.row).command});
 return {proposal:normalizeProposal(x.proposal),row,unmapped_people:strings(x.unmapped_people)};
}
export const taskFields=['專案編號','工程確認單','任務階段','任務種類','工作包編號','父義務','範圍版本','規則版本','證據版本','預定開始','預定結束','預估人時','組員','使用儀器','使用車輛','排程狀態','排程版本','命令編號','讀回時間','成果接受狀態','接受摘要'];
export function rowProposal(r:WorkRow):Proposal {return normalizeProposal({task_id:r.task_id,project_ref:r.project_id,case_ref:r.case.ref,title:r.title,content:r.content,phase:r.phase,kind:r.kind,package_id:r.package_id,parent_task_ref:r.parent_task_ref,primary_owner:r.owner.person_ref,crew:r.crew.map(p=>p.person_ref),start:r.interval.start,end:r.interval.end,est_person_hours:r.est_person_hours,instruments:r.instruments.map(p=>p.ref),vehicles:r.vehicles.map(p=>p.ref),department:r.department,deadline:r.deadline})}
export type SavedDraft={draft_id:string;proposal:Proposal;preview_id:string;command_id:string;saved_at:string;version?:number};
export function parseDraft(value:unknown):SavedDraft {const x=object(value);return {draft_id:str(x.id??x.draft_id),proposal:normalizeProposal(x.proposal),preview_id:str(x.preview_id),command_id:str(x.command_id),saved_at:typeof x.updated_at==='number'?new Date(x.updated_at*1000).toISOString():str(x.saved_at),version:typeof x.version==='number'?x.version:undefined}}
export function draftBody(d:SavedDraft){return {proposal:proposalBody(d.proposal),...(d.version===undefined?{}:{version:d.version})}}
export function parseDrafts(value:unknown):SavedDraft[] {return list(object(value).drafts).map(parseDraft)}
export function readLocalDrafts(raw:string|null):SavedDraft[] {try{return list(JSON.parse(raw??'[]')).map(parseDraft).filter(d=>d.draft_id)}catch{return []}}
export function needLabel(reason:string):string {if(reason.startsWith('approve_seat:'))return `等待${seatLabels[member(reason.split(':')[1],Object.keys(seatLabels) as (keyof typeof seatLabels)[])]}`;if(reason.startsWith('verify_unknown:'))return '資格或請假待人工核實';return ({confirm_assignment:'等待指派確認',reconcile_command:'命令需要對帳',review_returned:'退回內容待檢視'} as Record<string,string>)[reason]??'需要核實未識別事項'}
const blockerMessages:Record<string,string>={
 unknown:'資格、請假或資源可用性尚未人工核實',unknown_feasibility:'資格或請假尚未核實',conflict:'人員或資源時段衝突',unavailable:'人員已停用或資源不可使用',
 approval_not_configured:'尚未設定核准席位持有人',approval_missing:'尚待席位核准',approvals_required:'尚待必要席位核准',approval_returned:'此預覽已退回，請修改後重新預覽',returned:'此預覽已退回，請修改後重新預覽',
 person_without_lark_account:'此人員尚未綁定 Lark 帳號，請先完成帳號設定',source_unavailable:'必要來源讀取失敗',sources_unavailable:'無法讀取最新資料，請稍後更新',case_unresolved:'工程確認單無法解析，請重新選擇案件',task_not_found:'原任務不存在，請更新工作清單',obligation_changed:'改派不能變更父義務',
 invalid_draft:'有草稿格式不正確，已保留但無法列入工作進度，請重新載入修正',invalid:'資料格式不正確，請核對表單',blocked:'尚有未解除的發布條件',forbidden:'權限不足，操作未獲准',writes_disabled:'正式外部連線尚未開啟，不能發布',not_found:'找不到資料，請更新清單',disabled:'派工功能尚未開放',
 preview_expired:'預覽已過期，請重新預覽',preview_stale:'預覽或來源已變更，請重新預覽',stale_revision:'任務版本已更新，請重新讀取任務與預覽',source_changed:'來源已更新，請重新預覽',reservation_conflict:'同時段已被其他工作占用，草稿已保留',
 duplicate_command:'這份預覽已有發布命令，請查詢原命令，勿另建任務',idempotency_conflict:'命令編號已用於其他預覽，請查詢原命令',busy:'另一項操作正在處理，請稍後重試',version_conflict:'草稿已在其他地方更新，本機內容保留，請重新載入伺服器版本',
 seat_conflict:'核准席位決定衝突',seat_not_required:'此席位不在必要核准流程',not_seat_holder:'只有此席持有人可以核准',hash_returned:'這份內容已被退回，請修改後重新預覽',seat_already_decided:'此席已完成決定，請更新預覽',actor_holds_another_seat:'同一人不能兼任兩個核准席位',earlier_seat_pending:'前一席尚未核准，請依序處理',
 nothing_to_reconcile:'此命令目前不需要對帳，請更新命令狀態',payload_too_large:'內容超過上限，請縮短後重試',lark_unconfigured:'公司 Lark 身分或任務回寫設定未完成',
 rate_limited:'服務請求過於頻繁，請稍後重試',lark_permission:'Lark 拒絕回寫，請管理員檢查權限',lark_error:'Lark 拒絕此次寫入，請核對內容',lark_unavailable:'Lark 服務暫時無法使用',roster_unavailable:'人員名冊暫時無法讀取',readback_mismatch:'寫入後讀回不一致，請重新對帳',revision_conflict:'任務版本衝突，請重新載入',search_missing:'寫入已讀回，但命令搜尋尚未找到資料，請重新對帳',outcome_unknown:'遠端寫入結果不明，請查詢原命令',unverified_unknown:'此項仍未人工核實',person_unresolved:'名冊無法解析此人員',repair:'儀器或車輛送修中',abnormal_status:'儀器或車輛狀態異常',resource_status_unknown:'資源啟用或狀態資料尚未確認',same_day_other_slot:'同日另有預約，精確時段尚待核實',person_not_found:'找不到名冊人員',no_capability_source:'尚無資格資料來源，請人工核實',no_leave_source:'尚無請假資料來源，請人工核實',timed_overlap:'與既有人員或資源預約重疊',date_only_overlap:'既有預約僅有日期，時段需要核實',inactive:'人員已停用',missing:'找不到此人員或資源',client_timeout:'服務回應逾時，請保留命令並查詢原結果'};
export function blockerLabel(code:string):string {
 if(code.startsWith('search_')&&code!=='search_missing')return `命令搜尋未完成 · ${blockerLabel(code.slice(7))}`;
 if(code.startsWith('readback_')&&code!=='readback_mismatch')return `讀回檢查未完成 · ${blockerLabel(code.slice(9))}`;
 const [key,...parts]=code.split(':'),detail=parts.join(':');
 const label=blockerMessages[key]??`尚未通過的檢核（${code}），請管理員核實`;
 const seat=member(detail,Object.keys(seatLabels) as Seat[]);
 return detail?`${label} · ${seat==='unknown'?detail:seatLabels[seat]}`:label;
}
export class DispatchError extends ApiError {
 constructor(public original:ApiError,public blockers:string[],public command_id:string,public reason:string){super(original.status,[original.code?blockerLabel(original.code):original.status===503?'派工服務暫時無法使用，請稍後更新':original.status===502?'Lark 回寫失敗，請查詢原命令':original.message,original.message,reason?blockerLabel(reason):'',...blockers.map(blockerLabel),command_id?`原命令編號 · ${command_id}`:''].filter(Boolean).filter((v,i,a)=>a.indexOf(v)===i).join('。'),original.code)}
}
export async function dispatchRequest(path:string,signal:AbortSignal,body?:unknown,method?:'PUT'|'DELETE'):Promise<unknown> {
 let status=0;
 let result:unknown;
 try{result=await api<unknown>(path,{signal,cache:'no-store',timeoutMs:30000,...(body===undefined&&!method?{}:{method:method??'POST',...(body===undefined?{}:{body:JSON.stringify(body)})})},()=>!signal.aborted,value=>{status=value})}
 catch(error){if(!(error instanceof ApiError))throw error;const payload=object(error.payload);if(error.status===502&&(path===dispatchPaths.commits||path.endsWith('/reconcile'))&&str(object(payload.command).command_id)&&parseCommand(payload).state==='failed')return payload;throw new DispatchError(error,strings(payload.blockers),str(payload.command_id),str(payload.reason))}
 if(status!==202||(path!==dispatchPaths.commits&&!path.startsWith('/api/v2/commands/')))return result;
 const envelope=object(result),command=object(envelope.command);
 return envelope.command?{...envelope,command:{...command,state:command.state==='committed'?'pending':command.state}}:{...envelope,state:envelope.state==='committed'?'pending':envelope.state};
}
export const dispatchPaths={
 options:'/api/v2/dispatch/options',task:(id:string)=>`/api/v2/dispatch/tasks/${encodeURIComponent(id)}`,
 previews:'/api/v2/dispatch/previews',commits:'/api/v2/dispatch/commits',drafts:'/api/v2/dispatch/drafts',
 draft:(id:string)=>`/api/v2/dispatch/drafts/${encodeURIComponent(id)}`,
 work:(query:URLSearchParams)=>`/api/v2/dispatch/work?${query}`,
 preview:(id:string)=>`/api/v2/dispatch/previews/${encodeURIComponent(id)}`,
 decisions:(id:string)=>`/api/v2/dispatch/previews/${encodeURIComponent(id)}/decisions`,
 command:(id:string)=>`/api/v2/commands/${encodeURIComponent(id)}`,
 reconcile:(id:string)=>`/api/v2/commands/${encodeURIComponent(id)}/reconcile`
};
