import type {LocalNode} from './nodeWorkbenchModel';
import {api, ApiError} from './api';

export const SOP_NODES = [['sales','報價'],['pm','PM 派工'],['confirmation','確認單'],['field','外業'],['control','控制'],['mapping','圖資'],['report','報告'],['pricing','計價請款'],['settlement','入帳結算']] as const;
export type SopNodeKey = typeof SOP_NODES[number][0];
export const SOP_NODE_KEYS: readonly SopNodeKey[] = SOP_NODES.map(([key]) => key);
export const sopNodeLabel = (key: string) => SOP_NODES.find(([k]) => k === key)?.[1] || key;
export const isSopNode = (v: unknown): v is SopNodeKey => typeof v === 'string' && (SOP_NODE_KEYS as readonly string[]).includes(v);

export type Applicability = 'applicable'|'not_applicable'|'unresolved';
export type Lifecycle = 'pending'|'in_progress'|'blocked'|'done'|'archived';
export type Role = 'executor'|'checker'|'confirmer';
export const ROLES: readonly Role[] = ['executor','checker','confirmer'];
export interface SopCounts {done: number; total: number; unresolved: number; not_applicable: number; archived: number}
export interface SopAssignee {id: string; name: string; case_roles: string[]; department: string|null}
export interface SopSuggestion {taskId: string; ruleId: string; ruleRevision: number; tier: 'proof'|'indicator'; state: 'done'|'in_progress'; facts: Record<string, unknown>; hash: string}
export const SYNC_STATES = ['同步中','已同步','Lark 已變更','同步失敗','未啟用'] as const;
export interface SopLarkSync {state: typeof SYNC_STATES[number]; syncedAt: number|null; recordId: string|null; baseId: string|null; tableId: string|null}
export interface SopTask {
 isTest: boolean;
 larkSync: SopLarkSync;
 result?:{note:string; actorId:string; actorName:string; at:number}|null; completionBlockedReason?:string|null;
 allowedActions: string[]; suggestion: SopSuggestion|null; shared: boolean; conditional: boolean;
 id: string; title: string; instructions: string|null; participants: Partial<Record<Role,string>>;
 applicability: Applicability; state: Lifecycle; revision: number; overdue: boolean; manual: boolean;
 dueDate: string|null; dateStatus: string; completionRule: string;
 nodes: {node_key: SopNodeKey; node_id: string; order: number}[];
 origin: {template_family_id: string; source_row_key: string; instance_scope: string; imported_version_id: string|null};
 source: Record<string, unknown>|null; restricted: boolean;
}
export type SopPolicy = 'legacy'|'managed'|'needs_review';
export interface EnrollmentAttempt {
 id:string; projectId:string; status:'pending'|'failed'|'succeeded'; lastError:string|null; attempts:number;
 createdCount:number;
}
export interface SopEnrollment {
 policy:SopPolicy; canOptIn:boolean; canRetry:boolean; attempt:EnrollmentAttempt|null;
 nodes:{key:SopNodeKey; name:string; status:string; eligible:boolean}[];
}
export interface SopOverview {
 managedNodeKeys?:SopNodeKey[];
 localNodes?:LocalNode[];
 enrollment?:SopEnrollment|null;
 caseHeader?:{id:string; code:string|null; name:string|null}; projectId: string; startNode: SopNodeKey; checklistRevision: number; caseCounts: SopCounts; nodeCounts: Record<SopNodeKey, SopCounts>;
 tasks: SopTask[]; allowed: {import: boolean; manage: boolean; work: boolean; startAllNodes?:boolean};
 nodeDone: Partial<Record<SopNodeKey, {rule: string; reason: string}>>;
}
export interface CloseNodeResult {closed: number; leftOpen: {shared: number; unresolved: number}}
export interface SopTemplate {version_id: string; template_family_id: string; revision: string; name: string; is_default: boolean}
export type Outcome = 'new'|'already_present'|'link_addition'|'excluded'|'routing_reference'|'review_required'|'routine_excluded'|'disabled_excluded';
export interface CompletionSummary {state: Lifecycle; actorId:string|null; actorName:string|null; at:number|null; ruleId:string|null; factsHash:string|null; evidenceRefs:string[]}
export interface PreviewOutcome {completion:CompletionSummary|null; source_row_key: string; title: string; disposition: string; selected: boolean; outcome: Outcome; existing_task_id: string|null; existing_state: Lifecycle|null; applicability: Applicability; links_to_add: {node_key: SopNodeKey}[]}
export interface ImportPreview {
 previewId: string; expiresAt: number; startNode: SopNodeKey; template: {version_id: string; revision: string};
 nodeKeys: SopNodeKey[]; outcomes: PreviewOutcome[]; unresolved: {applicability: number; participants: number; dates: number};
 counts: {new_tasks: number; existing_tasks: number; added_links: number}; rowKeys: string[];
}
export interface ImportReceipt {requestId: string; created: string[]; existing: string[]; links: number; unresolved: {applicability: number; participants: number; dates: number}; checklistRevision: number}
export interface MutationResult {task_id: string; revision: number; checklist_revision: number; task?: SopTask}

export class SopError extends Error {
 constructor(public status: number, public code: string,public reason?:string) {super(code)}
 // No status means the request may have reached the server, so its outcome is unknown.
 get ambiguous() {return this.status === 0 || this.status === 408 || this.status >= 500}
}
const malformed = () => new SopError(502, 'malformed');
const object = (v: unknown): Record<string, unknown> => {if (!v || typeof v !== 'object' || Array.isArray(v)) throw malformed(); return v as Record<string, unknown>};
const str = (v: unknown): string => {if (typeof v !== 'string') throw malformed(); return v};
const optStr = (v: unknown): string|null => v == null ? null : str(v);
const int = (v: unknown): number => {if (!Number.isSafeInteger(v) || (v as number) < 0) throw malformed(); return v as number};
const seconds = (v: unknown): number => {if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) throw malformed(); return v};
const bool = (v: unknown): boolean => {if (typeof v !== 'boolean') throw malformed(); return v};
const list = <T>(v: unknown, parse: (item: unknown) => T): T[] => {if (!Array.isArray(v)) throw malformed(); return v.map(parse)};
const oneOf = <T extends string>(values: readonly T[]) => (v: unknown): T => {if (!values.includes(v as T)) throw malformed(); return v as T};
const node = (v: unknown): SopNodeKey => {if (!isSopNode(v)) throw malformed(); return v};
const applicability = oneOf<Applicability>(['applicable','not_applicable','unresolved']);
const lifecycle = oneOf<Lifecycle>(['pending','in_progress','blocked','done','archived']);
const counts = (v: unknown): SopCounts => {const c = object(v); return {done: int(c.done), total: int(c.total), unresolved: int(c.unresolved), not_applicable: int(c.not_applicable), archived: int(c.archived)}};
const unresolvedCounts = (v: unknown) => {const c = object(v); return {applicability: int(c.applicability), participants: int(c.participants), dates: int(c.dates)}};

export function parseSuggestion(v: unknown): SopSuggestion {
 const s = object(v); return {taskId: str(s.task_id), ruleId: str(s.rule_id), ruleRevision: int(s.rule_revision), tier: oneOf(['proof','indicator'] as const)(s.tier), state: oneOf(['done','in_progress'] as const)(s.suggested_state), facts: object(s.facts), hash: str(s.facts_hash)};
}
export function parseAssignees(v: unknown): SopAssignee[] {return list(object(v).people, p => {const x=object(p);return {id:str(x.id),name:str(x.name),case_roles:list(x.case_roles,str),department:optStr(x.department)}})}
function parseLarkSync(v: unknown): SopLarkSync {
 if (v == null) return {state: '未啟用', syncedAt: null, recordId: null, baseId: null, tableId: null};
 const s = object(v);
 return {state: oneOf(SYNC_STATES)(s.state), syncedAt: s.synced_at == null ? null : seconds(s.synced_at), recordId: optStr(s.record_id), baseId: optStr(s.base_id), tableId: optStr(s.table_id)};
}
function task(v: unknown): SopTask {
 const t = object(v), local = object(t.local), origin = object(t.origin), people = object(t.participants);
 const participants: SopTask['participants'] = {};
 for (const [role, id] of Object.entries(people)) {if (!ROLES.includes(role as Role)) throw malformed(); participants[role as Role] = str(id)}
 const dueDate = optStr(local.due_date);
 if (dueDate !== null && !/^\d{4}-\d{2}-\d{2}$/.test(dueDate)) throw malformed();
 const result=t.result==null?null:object(t.result);
 return {isTest: local.is_test == null ? false : bool(local.is_test), larkSync: parseLarkSync(t.lark_sync), result:result?{note:str(result.note),actorId:str(result.actor_id),actorName:str(result.actor_name),at:seconds(result.at)}:null,
  completionBlockedReason:optStr(t.completion_blocked_reason),allowedActions: list(t.allowed_actions,str), suggestion: t.suggestion == null ? null : parseSuggestion(t.suggestion), shared: bool(t.is_shared), conditional: bool(t.is_conditional), id: str(t.id), title: str(t.title), instructions: optStr(t.instructions), participants, applicability: applicability(t.applicability),
  state: lifecycle(t.state), revision: int(t.revision), overdue: bool(t.overdue), manual: origin.template_family_id === 'manual',
  dueDate, dateStatus: str(local.date_status), completionRule: str(local.completion_rule_status),
  nodes: list(t.nodes, n => {const l = object(n); return {node_key: node(l.node_key), node_id: str(l.node_id), order: int(l.order)}}),
  origin: {template_family_id: str(origin.template_family_id), source_row_key: str(origin.source_row_key), instance_scope: str(origin.instance_scope), imported_version_id: optStr(origin.imported_version_id)},
  source: t.source_snapshot == null ? null : object(t.source_snapshot), restricted: t.source_restriction != null};
}
export function parseEnrollmentAttempt(v:unknown):EnrollmentAttempt {
 const x=object(v), receipt=x.receipt==null?null:object(x.receipt);
 return {id:str(x.id), projectId:str(x.project_id), status:oneOf(['pending','failed','succeeded'] as const)(x.status),
  lastError:optStr(x.last_error), attempts:int(x.attempts), createdCount:receipt?list(receipt.created_task_ids,str).length+list(receipt.existing_task_ids,str).length:0};
}
export function parseEnrollment(v:unknown):SopEnrollment {
 const x=object(v), policy=object(x.policy);
 return {policy:oneOf<SopPolicy>(['legacy','managed','needs_review'])(policy.policy), canOptIn:bool(x.can_opt_in),canRetry:bool(x.can_retry),
  attempt:x.enrollment==null?null:parseEnrollmentAttempt(x.enrollment),
  nodes:list(x.nodes,v=>{const n=object(v);return {key:node(n.key),name:str(n.name),status:str(n.status),eligible:bool(n.eligible)}})};
}
export function parseReadiness(v:unknown) {
 const x=object(v);
 return list(x.items,v=>{const c=object(v),p=object(c.policy);return {projectId:str(c.project_id),code:optStr(c.code),name:optStr(c.name),
  policy:oneOf<SopPolicy>(['legacy','managed','needs_review'])(p.policy),enrollments:list(c.enrollments,parseEnrollmentAttempt)}});
}
function parseLocalNode(v:unknown):LocalNode {
 const n=object(v),can=object(n.can);
 return {key:node(n.key),id:str(n.id),revision:int(n.revision),status:str(n.status),ownerId:optStr(n.owner_id),completedAt:optStr(n.completed_at),reason:optStr(n.reason),disabledReason:optStr(n.disabled_reason),completeDisabledReason:optStr(n.complete_disabled_reason),can:{assign:bool(can.assign),complete:bool(can.complete),reject:bool(can.reject),create_task:bool(can.create_task)}};
}
export function parseOverview(v: unknown): SopOverview {
 const o = object(v), allowed = object(o.allowed_actions), nodeCounts = object(o.node_counts);
 if (o.task_source !== 'sop_local') throw malformed();
 const tasks = list(o.tasks, task);
 if (new Set(tasks.map(t => t.id)).size !== tasks.length) throw malformed();
 const header=o.case==null?null:object(o.case);
 return {managedNodeKeys:o.managed_node_keys==null?undefined:list(o.managed_node_keys,node),localNodes:o.local_nodes==null?[]:list(o.local_nodes,parseLocalNode),enrollment:o.sop_enrollment==null?null:parseEnrollment(o.sop_enrollment),caseHeader:header?{id:str(header.id),code:optStr(header.code),name:optStr(header.name)}:undefined,projectId: str(o.project_id), startNode: node(o.start_node), checklistRevision: int(o.checklist_revision), caseCounts: counts(o.case_counts),
  nodeCounts: Object.fromEntries(SOP_NODE_KEYS.map(key => [key, counts(nodeCounts[key])])) as Record<SopNodeKey, SopCounts>,
  tasks, allowed: {import: bool(allowed.import), manage: bool(allowed.manage), work: bool(allowed.work), startAllNodes: allowed.start_all_nodes===true},
  nodeDone: Object.fromEntries(Object.entries(o.node_done == null ? {} : object(o.node_done)).filter(([key]) => isSopNode(key)).map(([key, v]) => {const d = object(v); return [key, {rule: str(d.rule), reason: str(d.reason)}]}))};
}
export function parseTemplates(v: unknown): SopTemplate[] {
 return list(object(v).templates, t => {const x = object(t); return {version_id: str(x.version_id), template_family_id: str(x.template_family_id), revision: str(x.revision), name: str(x.name), is_default: bool(x.is_default)}});
}
const OUTCOMES: readonly Outcome[] = ['new','already_present','link_addition','excluded','routing_reference','review_required','routine_excluded','disabled_excluded'];
function parseCompletion(value:unknown):CompletionSummary|null {
 if(value==null)return null;
 const c=object(value),basis=c.evidence_basis==null?null:object(c.evidence_basis);
 return {state:lifecycle(c.state),actorId:optStr(c.actor_id),actorName:optStr(c.actor_name),at:c.at==null?null:seconds(c.at),ruleId:optStr(basis?.rule_id),factsHash:optStr(basis?.facts_hash),evidenceRefs:list(c.evidence_refs,str)};
}
export function parsePreview(v: unknown): ImportPreview {
 const p = object(v), template = object(p.template), selection = object(p.selection);
 return {previewId: str(p.preview_id), expiresAt: seconds(p.expires_at), startNode: node(p.start_node), template: {version_id: str(template.version_id), revision: str(template.revision)},
  nodeKeys: list(selection.node_keys, node), rowKeys: list(selection.row_keys, str),
  outcomes: list(p.outcomes, item => {const o = object(item); return {source_row_key: str(o.source_row_key), title: str(o.title), disposition: str(o.disposition), selected: bool(o.selected), outcome: oneOf(OUTCOMES)(o.outcome),
   completion: parseCompletion(o.completion), existing_task_id: optStr(o.existing_task_id), existing_state: o.existing_state == null ? null : lifecycle(o.existing_state), applicability: applicability(o.applicability),
   links_to_add: list(o.links_to_add, l => ({node_key: node(object(l).node_key)}))}}),
  unresolved: unresolvedCounts(p.unresolved_counts),
  counts: (c => ({new_tasks: int(c.new_tasks), existing_tasks: int(c.existing_tasks), added_links: int(c.added_links)}))(object(p.counts))};
}
export function parseReceipt(v: unknown): ImportReceipt {
 const r = object(v);
 return {requestId: str(r.request_id), created: list(r.created_task_ids, str), existing: list(r.existing_task_ids, str), links: list(r.added_links, object).length,
  unresolved: unresolvedCounts(r.unresolved_counts), checklistRevision: int(r.checklist_revision)};
}
export function parseMutation(v: unknown): MutationResult {
 const r = object(v);
 return {task_id: str(r.task_id), revision: int(r.revision), checklist_revision: int(r.checklist_revision), ...(r.task == null ? {} : {task: task(r.task)})};
}

async function request(url: string, init: RequestInit, current: () => boolean): Promise<unknown> {
 try {return await api<unknown>(url, {cache: 'no-store', ...init, timeoutMs: 20000}, current)}
 catch (error) {
  if (error instanceof ApiError) throw new SopError(error.status, error.code || (error.status === 408 ? 'client_timeout' : 'request_failed'),error.payload&&typeof error.payload==='object'&&'reason' in error.payload&&typeof error.payload.reason==='string'?error.payload.reason:undefined);
  if (error instanceof DOMException && error.name === 'AbortError') throw error;
  throw new SopError(0, 'network');
 }
}
const base = (id: string) => `/api/projects/${encodeURIComponent(id)}`;
const post = (body: unknown, method = 'POST'): RequestInit => ({method, body: JSON.stringify(body)});
export const sopApi = {
 localNode:(id:string,key:string,body:{action:'assign'|'complete'|'reject';expected_revision:number;owner_id?:string;reason?:string},current:()=>boolean)=>request(`${base(id)}/sop-nodes/${encodeURIComponent(key)}`,post(body),current),
 readiness: (signal?:AbortSignal) => api<unknown>('/api/sop-import/readiness',{signal}).then(parseReadiness),
 optIn: (id:string, nodeKeys:SopNodeKey[], current:()=>boolean) => request(`${base(id)}/sop-import/opt-in`,{method:'POST',body:JSON.stringify({node_keys:nodeKeys,confirmed:true})},current).then(parseEnrollmentAttempt),
 retryEnrollment: (id:string, enrollmentId:string, current:()=>boolean) => request(`${base(id)}/sop-import/retry`,{method:'POST',body:JSON.stringify({enrollment_id:enrollmentId})},current).then(parseEnrollmentAttempt),
 assignees: (id: string, current: () => boolean) => request(`${base(id)}/sop-assignees`, {}, current).then(parseAssignees),
 suggestion: (id: string, taskId: string, body: Record<string, unknown>, current: () => boolean) => request(`${base(id)}/sop-tasks/${encodeURIComponent(taskId)}/suggestion`, post(body), current).then(parseMutation),
 acceptSuggestions: (id: string, body: Record<string, unknown>, current: () => boolean) => request(`${base(id)}/sop-tasks/suggestions/accept`, post(body), current),
 overview: (id: string, current: () => boolean) => request(`${base(id)}/sop-tasks`, {}, current).then(parseOverview),
 templates: (current: () => boolean) => request('/api/sop-templates', {}, current).then(parseTemplates),
 preview: (id: string, body: {template_version_id: string; node_keys: SopNodeKey[]; row_keys?: string[]; applicability_decisions?: Record<string, {value: Applicability; reason: string}>}, current: () => boolean) =>
  request(`${base(id)}/sop-import/preview`, post(body), current).then(parsePreview),
 apply: (id: string, body: {preview_id: string; request_id: string}, current: () => boolean) => request(`${base(id)}/sop-import/apply`, post(body), current).then(parseReceipt),
 run: (id: string, requestId: string, current: () => boolean) => request(`${base(id)}/sop-import/runs/${encodeURIComponent(requestId)}`, {}, current).then(parseReceipt),
 create: (id: string, body: {title: string; node_keys: SopNodeKey[];instructions?:string;participants?:{executor?:string};due_date?:string|null;is_test?:boolean}, current: () => boolean) => request(`${base(id)}/sop-tasks`, post(body), current).then(r => ({task_id: str(object(r).task_id), checklist_revision: int(object(r).checklist_revision)})),
 cleanupTest: (id: string, taskId: string, body: {expected_revision: number; reason: string}, current: () => boolean) => request(`${base(id)}/sop-tasks/${encodeURIComponent(taskId)}/cleanup-test`, post(body), current).then(r => {const o = object(r); return {taskId: str(o.task_id), removed: bool(o.removed), replayed: bool(o.replayed), checklistRevision: int(o.checklist_revision)}}),
 patch: (id: string, taskId: string, body: Record<string, unknown>, current: () => boolean) => request(`${base(id)}/sop-tasks/${encodeURIComponent(taskId)}`, post(body, 'PATCH'), current).then(parseMutation),
 closeNode: (id: string, nodeKey: SopNodeKey, current: () => boolean): Promise<CloseNodeResult> => request(`${base(id)}/sop-tasks/close-node`, post({node_key: nodeKey}), current).then(r => {const o = object(r), left = object(o.left_open); return {closed: int(o.closed), leftOpen: {shared: int(left.shared), unresolved: int(left.unresolved)}}}),
 transition: (id: string, taskId: string, body: Record<string, unknown>, current: () => boolean) => request(`${base(id)}/sop-tasks/${encodeURIComponent(taskId)}/transition`, post(body), current).then(parseMutation),
};

export const SOP_ERROR_TEXT: Record<string, string> = {
 cleanup_migration_required: '測試任務清除尚未開放，請聯絡管理員套用清除稽核遷移（503）',
 test_task_projection_exists: '此測試任務已有 Lark 投影紀錄，無法清除，請聯絡管理員核對，避免留下孤立資料（409）',
 test_task_required: '僅能清除建立時標記為測試且仍有測試標記的任務（409）',
 node_revision_conflict:'節點已更新，請重新載入後再試',local_node_blocked:'節點目前無法操作，請核對任務與狀態',local_node_only:'請使用此案件的正式節點流程',
 result_note_required: '請填寫結果說明', quote_number_taken: '報價編號已使用', quote_number_invalid: '報價編號格式不正確', local_case_creation_disabled: '本地建立暫停', quote_not_found: '找不到報價', suggestion_stale: '建議已更新', suggestion_confirmation_required: '需確認建議並填寫原因', identity_forbidden:'帳號或工作區尚未獲准存取，請聯絡管理員核對身分與名冊', session_expired: '登入已過期', sop_import_forbidden: '沒有 SOP 任務權限', case_not_found: '找不到此案件', task_not_found: '找不到此 SOP 任務',
 preview_stale: '預覽已過期，已重新產生', preview_not_found: '預覽已失效，已重新產生', idempotency_mismatch: '匯入請求不一致，請重新預覽',
 task_revision_conflict: '任務已被更新，已重新載入', node_mapping_invalid: '節點對應有誤', row_not_importable: '此列不可匯入',
 applicability_unresolved: '需先確認適用', completion_evidence_missing: '此任務需先完成佐證或審核', import_unavailable: 'SOP 任務暫停寫入',
 template_unavailable: '範本版本不可用', template_mapping_conflict: '範本節點對應衝突', participant_unresolved: '此人員已停用或不存在', node_not_done_by_data: '資料尚未判定此節點完成',
 task_reopen_required: '需先重新開啟', invalid_transition: '目前狀態不可執行', legacy_case_requires_opt_in: '舊案需先確認套用 SOP', node_not_enrolled: '此節點尚未套用 SOP', node_already_started_or_finished: '已開始或已完成的節點維持原流程', case_identity_unresolved: '案件識別待核對', case_policy_changed: '案件納管範圍已變更，請重新讀取', confirmation_required: '請選擇節點並勾選確認', case_already_managed: '此案已套用 SOP，請重新讀取', invalid_request: '內容格式不正確', run_not_found: '找不到匯入紀錄',
 network: '連線中斷', client_timeout: '連線逾時', malformed: '回應格式不正確',
};
export const sopErrorText = (error: unknown) => error instanceof SopError ? error.reason || SOP_ERROR_TEXT[error.code] || `操作未完成（${error.status}）` : '操作未完成';
