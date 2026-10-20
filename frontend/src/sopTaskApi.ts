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
export interface SopTask {
 id: string; title: string; instructions: string|null; participants: Partial<Record<Role,string>>;
 applicability: Applicability; state: Lifecycle; revision: number; overdue: boolean; manual: boolean;
 dueDate: string|null; dateStatus: string; completionRule: string;
 nodes: {node_key: SopNodeKey; node_id: string; order: number}[];
 origin: {template_family_id: string; source_row_key: string; instance_scope: string; imported_version_id: string|null};
 source: Record<string, unknown>|null; restricted: boolean;
}
export interface SopOverview {
 projectId: string; startNode: SopNodeKey; checklistRevision: number; caseCounts: SopCounts; nodeCounts: Record<SopNodeKey, SopCounts>;
 tasks: SopTask[]; allowed: {import: boolean; manage: boolean; work: boolean};
}
export interface SopTemplate {version_id: string; template_family_id: string; revision: string; name: string; is_default: boolean}
export type Outcome = 'new'|'already_present'|'link_addition'|'excluded'|'routing_reference'|'review_required'|'routine_excluded'|'disabled_excluded';
export interface PreviewOutcome {source_row_key: string; title: string; disposition: string; selected: boolean; outcome: Outcome; existing_task_id: string|null; existing_state: Lifecycle|null; applicability: Applicability; links_to_add: {node_key: SopNodeKey}[]}
export interface ImportPreview {
 previewId: string; expiresAt: number; startNode: SopNodeKey; template: {version_id: string; revision: string};
 nodeKeys: SopNodeKey[]; outcomes: PreviewOutcome[]; unresolved: {applicability: number; participants: number; dates: number};
 counts: {new_tasks: number; existing_tasks: number; added_links: number}; rowKeys: string[];
}
export interface ImportReceipt {requestId: string; created: string[]; existing: string[]; links: number; unresolved: {applicability: number; participants: number; dates: number}; checklistRevision: number}
export interface MutationResult {task_id: string; revision: number; checklist_revision: number}

export class SopError extends Error {
 constructor(public status: number, public code: string) {super(code)}
 // No status means the request may have reached the server, so its outcome is unknown.
 get ambiguous() {return this.status === 0 || this.status === 408 || this.status >= 500}
}
const malformed = () => new SopError(502, 'malformed');
const object = (v: unknown): Record<string, unknown> => {if (!v || typeof v !== 'object' || Array.isArray(v)) throw malformed(); return v as Record<string, unknown>};
const str = (v: unknown): string => {if (typeof v !== 'string') throw malformed(); return v};
const optStr = (v: unknown): string|null => v == null ? null : str(v);
const int = (v: unknown): number => {if (!Number.isSafeInteger(v) || (v as number) < 0) throw malformed(); return v as number};
const bool = (v: unknown): boolean => {if (typeof v !== 'boolean') throw malformed(); return v};
const list = <T>(v: unknown, parse: (item: unknown) => T): T[] => {if (!Array.isArray(v)) throw malformed(); return v.map(parse)};
const oneOf = <T extends string>(values: readonly T[]) => (v: unknown): T => {if (!values.includes(v as T)) throw malformed(); return v as T};
const node = (v: unknown): SopNodeKey => {if (!isSopNode(v)) throw malformed(); return v};
const applicability = oneOf<Applicability>(['applicable','not_applicable','unresolved']);
const lifecycle = oneOf<Lifecycle>(['pending','in_progress','blocked','done','archived']);
const counts = (v: unknown): SopCounts => {const c = object(v); return {done: int(c.done), total: int(c.total), unresolved: int(c.unresolved), not_applicable: int(c.not_applicable), archived: int(c.archived)}};
const unresolvedCounts = (v: unknown) => {const c = object(v); return {applicability: int(c.applicability), participants: int(c.participants), dates: int(c.dates)}};

function task(v: unknown): SopTask {
 const t = object(v), local = object(t.local), origin = object(t.origin), people = object(t.participants);
 const participants: SopTask['participants'] = {};
 for (const [role, id] of Object.entries(people)) {if (!ROLES.includes(role as Role)) throw malformed(); participants[role as Role] = str(id)}
 const dueDate = optStr(local.due_date);
 if (dueDate !== null && !/^\d{4}-\d{2}-\d{2}$/.test(dueDate)) throw malformed();
 return {id: str(t.id), title: str(t.title), instructions: optStr(t.instructions), participants, applicability: applicability(t.applicability),
  state: lifecycle(t.state), revision: int(t.revision), overdue: bool(t.overdue), manual: origin.template_family_id === 'manual',
  dueDate, dateStatus: str(local.date_status), completionRule: str(local.completion_rule_status),
  nodes: list(t.nodes, n => {const l = object(n); return {node_key: node(l.node_key), node_id: str(l.node_id), order: int(l.order)}}),
  origin: {template_family_id: str(origin.template_family_id), source_row_key: str(origin.source_row_key), instance_scope: str(origin.instance_scope), imported_version_id: optStr(origin.imported_version_id)},
  source: t.source_snapshot == null ? null : object(t.source_snapshot), restricted: t.source_restriction != null};
}
export function parseOverview(v: unknown): SopOverview {
 const o = object(v), allowed = object(o.allowed_actions), nodeCounts = object(o.node_counts);
 if (o.task_source !== 'sop_local') throw malformed();
 const tasks = list(o.tasks, task);
 if (new Set(tasks.map(t => t.id)).size !== tasks.length) throw malformed();
 return {projectId: str(o.project_id), startNode: node(o.start_node), checklistRevision: int(o.checklist_revision), caseCounts: counts(o.case_counts),
  nodeCounts: Object.fromEntries(SOP_NODE_KEYS.map(key => [key, counts(nodeCounts[key])])) as Record<SopNodeKey, SopCounts>,
  tasks, allowed: {import: bool(allowed.import), manage: bool(allowed.manage), work: bool(allowed.work)}};
}
export function parseTemplates(v: unknown): SopTemplate[] {
 return list(object(v).templates, t => {const x = object(t); return {version_id: str(x.version_id), template_family_id: str(x.template_family_id), revision: str(x.revision), name: str(x.name), is_default: bool(x.is_default)}});
}
const OUTCOMES: readonly Outcome[] = ['new','already_present','link_addition','excluded','routing_reference','review_required','routine_excluded','disabled_excluded'];
export function parsePreview(v: unknown): ImportPreview {
 const p = object(v), template = object(p.template), selection = object(p.selection);
 return {previewId: str(p.preview_id), expiresAt: int(p.expires_at), startNode: node(p.start_node), template: {version_id: str(template.version_id), revision: str(template.revision)},
  nodeKeys: list(selection.node_keys, node), rowKeys: list(selection.row_keys, str),
  outcomes: list(p.outcomes, item => {const o = object(item); return {source_row_key: str(o.source_row_key), title: str(o.title), disposition: str(o.disposition), selected: bool(o.selected), outcome: oneOf(OUTCOMES)(o.outcome),
   existing_task_id: optStr(o.existing_task_id), existing_state: o.existing_state == null ? null : lifecycle(o.existing_state), applicability: applicability(o.applicability),
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
 return {task_id: str(r.task_id), revision: int(r.revision), checklist_revision: int(r.checklist_revision)};
}

async function request(url: string, init: RequestInit, current: () => boolean): Promise<unknown> {
 try {return await api<unknown>(url, {cache: 'no-store', ...init, timeoutMs: 20000}, current)}
 catch (error) {
  if (error instanceof ApiError) throw new SopError(error.status, error.code || (error.status === 408 ? 'client_timeout' : 'request_failed'));
  if (error instanceof DOMException && error.name === 'AbortError') throw error;
  throw new SopError(0, 'network');
 }
}
const base = (id: string) => `/api/projects/${encodeURIComponent(id)}`;
const post = (body: unknown, method = 'POST'): RequestInit => ({method, body: JSON.stringify(body)});
export const sopApi = {
 overview: (id: string, current: () => boolean) => request(`${base(id)}/sop-tasks`, {}, current).then(parseOverview),
 templates: (current: () => boolean) => request('/api/sop-templates', {}, current).then(parseTemplates),
 preview: (id: string, body: {template_version_id: string; node_keys: SopNodeKey[]; row_keys?: string[]; applicability_decisions?: Record<string, {value: Applicability; reason: string}>}, current: () => boolean) =>
  request(`${base(id)}/sop-import/preview`, post(body), current).then(parsePreview),
 apply: (id: string, body: {preview_id: string; request_id: string}, current: () => boolean) => request(`${base(id)}/sop-import/apply`, post(body), current).then(parseReceipt),
 run: (id: string, requestId: string, current: () => boolean) => request(`${base(id)}/sop-import/runs/${encodeURIComponent(requestId)}`, {}, current).then(parseReceipt),
 create: (id: string, body: {title: string; node_keys: SopNodeKey[]}, current: () => boolean) => request(`${base(id)}/sop-tasks`, post(body), current).then(r => ({task_id: str(object(r).task_id), checklist_revision: int(object(r).checklist_revision)})),
 patch: (id: string, taskId: string, body: Record<string, unknown>, current: () => boolean) => request(`${base(id)}/sop-tasks/${encodeURIComponent(taskId)}`, post(body, 'PATCH'), current).then(parseMutation),
 transition: (id: string, taskId: string, body: Record<string, unknown>, current: () => boolean) => request(`${base(id)}/sop-tasks/${encodeURIComponent(taskId)}/transition`, post(body), current).then(parseMutation),
};

export const SOP_ERROR_TEXT: Record<string, string> = {
 session_expired: '登入已過期', sop_import_forbidden: '沒有 SOP 任務權限', case_not_found: '找不到此案件', task_not_found: '找不到此 SOP 任務',
 preview_stale: '預覽已過期，已重新產生', preview_not_found: '預覽已失效，已重新產生', idempotency_mismatch: '匯入請求不一致，請重新預覽',
 task_revision_conflict: '任務已被更新，已重新載入', node_mapping_invalid: '節點對應有誤', row_not_importable: '此列不可匯入',
 applicability_unresolved: '需先確認適用', completion_evidence_missing: '完成條件待審核', import_unavailable: 'SOP 任務暫停寫入',
 template_unavailable: '範本版本不可用', template_mapping_conflict: '範本節點對應衝突', participant_unresolved: '人員不符資格',
 task_reopen_required: '需先重新開啟', invalid_transition: '目前狀態不可執行', invalid_request: '內容格式不正確', run_not_found: '找不到匯入紀錄',
 network: '連線中斷', client_timeout: '連線逾時', malformed: '回應格式不正確',
};
export const sopErrorText = (error: unknown) => error instanceof SopError ? SOP_ERROR_TEXT[error.code] || `操作未完成（${error.status}）` : '操作未完成';
