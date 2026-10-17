import {api, ApiError} from './api';

export const NODE_ASSIGNMENT_ORDER = ['sales', 'pm', 'confirmation', 'field', 'control', 'mapping', 'report', 'pricing', 'settlement'] as const;
export type NodeAction = 'claim' | 'assign' | 'complete' | 'approve' | 'reject' | 'create_task';
export type NodePermissions = Partial<Record<NodeAction, boolean>>;
export interface AssignmentPerson {open_id: string; name: string; avatar_url?: string}
export interface AssignablePerson extends AssignmentPerson {departments: string[]}
export interface AssignmentNode {
  key: string; label: string; status: string | null; derived_status: string; record_id: string | null; revision: string | null;
  departments: string[]; assignment_method: string | null; started_at: string | null; finished_at: string | null;
  tasks: {done: number; total: number}; progress: number;
  owners: AssignmentPerson[]; assigned_by: AssignmentPerson | null; approver: AssignmentPerson | null;
  approved_at: string | null; reject_reason: string | null; deadline: string | null; warnings: string[];
  next_due?: string | null; deadline_basis?: string; assignment_key?: string | null; origin?: 'lark';
}
export interface AssignmentTask {
  id: string; title: string; detail: string; assignee: AssignmentPerson | null;
  assigned_by: AssignmentPerson | null; department: string; deadline: string | null; status: string; revision: string; record_id: string; done_at: string | null; created_at: string | null;
  can: Record<'edit_status' | 'cancel' | 'assign' | 'claim' | 'edit_details', boolean>;
}
export interface NodeAssignmentList {
  fetched_at?: string | null; stale_reason?: string | null;
  code: string; summary: {done: number; total: number; current_node: string | null};
  node_details?: Record<string, Pick<NodeAssignmentDetail, 'tasks' | 'assignable_people'>>;
  nodes: AssignmentNode[]; stale: boolean; writes_enabled: boolean; writes_disabled_reason: string | null; roster: {available: boolean; stale: boolean}; warnings: string[]; can: Record<string, NodePermissions>;
}
export interface NodeAssignmentDetail extends Pick<NodeAssignmentList, 'summary' | 'writes_enabled' | 'writes_disabled_reason' | 'roster' | 'warnings' | 'fetched_at' | 'stale_reason'> {can: NodePermissions; record_id: string | null; node: AssignmentNode; tasks: AssignmentTask[]; assignable_people: AssignablePerson[]}
export interface NewAssignmentTask {title: string; detail: string; assignee_open_id: string; department: string; deadline: string}
export type AssignmentMutation =
  | {action: 'claim' | 'complete' | 'approve'; nodeKey: string; expected_revision: string | null}
  | {action: 'assign'; nodeKey: string; owner_open_ids: string[]; expected_revision: string | null}
  | {action: 'reject'; nodeKey: string; reason: string; expected_revision: string | null}
  | {action: 'create_task'; nodeKey: string; task: NewAssignmentTask}
  | {action: 'update_task'; nodeKey: string; taskId: string; expected_revision: string; patch: Partial<Pick<NewAssignmentTask, 'assignee_open_id' | 'deadline' | 'detail'>> & {status?: string}};

const NODE_LABELS: Record<string, string> = {
  not_started: '未開始', pending: '待處理', in_progress: '進行中', pending_review: '待審核', completed: '已完成', skipped: '略過',
  awaiting_review: '待審核', 未開始: '未開始', 待處理: '待處理', 進行中: '進行中', 待審核: '待審核', 已完成: '已完成', 略過: '略過',
};
export const TASK_STATUS_OPTIONS = [['待處理', '待處理'], ['進行中', '進行中'], ['已完成', '已完成'], ['取消', '取消']] as const;
export const nodeStatusLabel = (status: string) => NODE_LABELS[status] || '狀態待確認';
export const taskStatusLabel = (status: string) => TASK_STATUS_OPTIONS.find(([key, label]) => key === status || label === status)?.[1] || (status === 'canceled' ? '取消' : '狀態待確認');
export const taskStatusValue = (status: string) => TASK_STATUS_OPTIONS.find(([key, label]) => key === status || label === status)?.[0] || (status === 'canceled' ? 'cancelled' : '');

export class NodeAssignmentError extends Error {
  constructor(public status: number, message: string, public code?: string, public fields: Record<string, string> = {}) {super(message)}
}
const malformed = () => new NodeAssignmentError(502, '節點資料格式不正確，請稍後重試。');
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw malformed();
  return Object.fromEntries(Object.entries(value));
}
function text(value: unknown): string {if (typeof value !== 'string') throw malformed(); return value}
function optionalText(value: unknown): string | null {return value == null ? null : text(value)}
function count(value: unknown): number {if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) throw malformed(); return value}
function array<T>(value: unknown, parse: (item: unknown) => T): T[] {if (!Array.isArray(value)) throw malformed(); return value.map(parse)}
function person(value: unknown): AssignmentPerson {
  if (typeof value === 'string') return {open_id: value, name: '姓名待確認'};
  const p = record(value); return {open_id: text(p.open_id), name: text(p.name), ...(typeof p.avatar_url === 'string' ? {avatar_url: p.avatar_url} : {})};
}
function optionalPerson(value: unknown): AssignmentPerson | null {return value == null || value === '' ? null : person(value)}
function node(value: unknown): AssignmentNode {
  const n = record(value), tasks = record(n.tasks);
  return {
    record_id: optionalText(n.record_id), revision: optionalText(n.revision), departments: array(n.departments, text),
    assignment_method: optionalText(n.assignment_method), started_at: optionalText(n.started_at), finished_at: optionalText(n.finished_at),
    key: text(n.key), label: text(n.label), status: optionalText(n.status), derived_status: text(n.derived_status),
    tasks: {done: count(tasks.done), total: count(tasks.total)}, progress: count(n.progress), owners: array(n.owners, person),
    assigned_by: optionalPerson(n.assigned_by), approver: optionalPerson(n.approver), approved_at: optionalText(n.approved_at),
    reject_reason: optionalText(n.reject_reason), deadline: optionalText(n.deadline), warnings: array(n.warnings, text),
    ...('next_due' in n ? {next_due: optionalText(n.next_due)} : {}),
    ...('assignment_key' in n ? {assignment_key: optionalText(n.assignment_key)} : {}),
    ...('deadline_basis' in n ? {deadline_basis: text(n.deadline_basis)} : {}),
    ...(n.origin === 'lark' ? {origin: 'lark' as const} : {}),
  };
}
function task(value: unknown): AssignmentTask {
  const t = record(value);
  return {id: text(t.id), title: text(t.title), detail: optionalText(t.detail) || '', assignee: optionalPerson(t.assignee),
    assigned_by: optionalPerson(t.assigned_by), department: optionalText(t.department) || '', deadline: optionalText(t.deadline), status: text(t.status), record_id: text(t.id), revision: text(t.revision), done_at: optionalText(t.done_at), created_at: optionalText(t.created_at),
    can: taskPermissions(t.can)};
}
function permissions(value: unknown): NodePermissions {
  const p = record(value);
  return {claim: p.claim === true, assign: p.assign === true, complete: p.complete === true, approve: p.approve === true, reject: p.reject === true, create_task: p.create_task === true};
}
function taskPermissions(value: unknown): AssignmentTask['can'] {
  const p = record(value);
  return {edit_status: p.edit_status === true, cancel: p.cancel === true, assign: p.assign === true, claim: p.claim === true, edit_details: p.edit_details === true};
}
function envelope(result: Record<string, unknown>) {
  const summary = record(result.summary), roster = record(result.roster);
  if (typeof result.writes_enabled !== 'boolean' || typeof roster.available !== 'boolean' || typeof roster.stale !== 'boolean') throw malformed();
  return {summary: {done: count(summary.done), total: count(summary.total), current_node: optionalText(summary.current_node)},
    ...('fetched_at' in result ? {fetched_at: optionalText(result.fetched_at)} : {}),
    ...('stale_reason' in result ? {stale_reason: optionalText(result.stale_reason)} : {}),
    writes_enabled: result.writes_enabled, writes_disabled_reason: optionalText(result.writes_disabled_reason),
    roster: {available: roster.available, stale: roster.stale}, warnings: array(result.warnings, text)};
}
function detailPayload(value: unknown) {
  const d = record(value);
  return {tasks: array(d.tasks, task), assignable_people: array(d.assignable_people, value => {
    const p = record(value); return {...person(p), departments: array(p.departments, text)};
  })};
}
export function overviewDetail(list: NodeAssignmentList, n: AssignmentNode): NodeAssignmentDetail | undefined {
  const payload = list.node_details?.[n.key];
  if (!payload) return undefined;
  const named = (p: AssignmentPerson | null) => p && p.name === '姓名待確認' ? payload.assignable_people.find(candidate => candidate.open_id === p.open_id) || p : p;
  return {...list, ...payload, node: {...n, assigned_by: named(n.assigned_by), approver: named(n.approver)}, record_id: n.record_id, can: list.can[n.key] || {}, tasks: payload.tasks.map(t => ({...t, assignee: named(t.assignee), assigned_by: named(t.assigned_by)}))};
}
const basePath = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}/node-assignments`;
export async function assignmentRequest(url: string, init: RequestInit, isCurrent: () => boolean): Promise<unknown> {
  try {return await api<unknown>(url, {...init, timeoutMs: 20000}, isCurrent)}
  catch (error) {
    if (!(error instanceof ApiError)) throw error;
    const fields: Record<string, string> = {};
    let message = error.message;
    if (error.status === 422) {
      let detail: unknown;
      try {detail = JSON.parse(error.message)} catch {detail = error.message}
      message = typeof detail === 'string' ? detail : '請檢查欄位內容後再試。';
      if (Array.isArray(detail)) for (const item of detail) {
        if (item && typeof item === 'object' && 'loc' in item && Array.isArray(item.loc) && 'msg' in item && typeof item.msg === 'string') {
          const field = item.loc.at(-1); if (typeof field === 'string') fields[field] = item.msg;
        }
      }
      else if (detail && typeof detail === 'object') for (const [field, message] of Object.entries(detail)) if (typeof message === 'string') fields[field] = message;
    }
    throw new NodeAssignmentError(error.status, message, error.code, fields);
  }
}
export async function fetchNodeAssignments(projectId: string, signal: AbortSignal, isCurrent: () => boolean): Promise<NodeAssignmentList> {
  const result = record(await assignmentRequest(basePath(projectId), {signal, cache: 'no-store'}, isCurrent));
  if (result.code === 'disabled') throw new NodeAssignmentError(404, '', 'disabled');
  const actions = record(result.can);
  if (typeof result.stale !== 'boolean') throw malformed();
  const can: Record<string, NodePermissions> = {};
  for (const [key, value] of Object.entries(actions)) can[key] = permissions(value);
  const nodes = array(result.nodes, node);
  if (new Set(nodes.map(n => n.key)).size !== nodes.length) throw malformed();
  return {code: text(result.code), ...envelope(result),
    node_details: result.node_details == null ? undefined : Object.fromEntries(Object.entries(record(result.node_details)).map(([key, value]) => [key, detailPayload(value)])),
    nodes: NODE_ASSIGNMENT_ORDER.flatMap(key => nodes.filter(n => n.key === key)), stale: result.stale, can};
}
export async function fetchNodeAssignmentDetail(projectId: string, key: string, signal: AbortSignal, isCurrent: () => boolean): Promise<NodeAssignmentDetail> {
  const result = record(await assignmentRequest(`${basePath(projectId)}/nodes/${encodeURIComponent(key)}`, {signal, cache: 'no-store'}, isCurrent));
  return parseDetail(result, key);
}
function parseDetail(result: Record<string, unknown>, key: string): NodeAssignmentDetail {
  const parsedNode = node(result.node);
  if (parsedNode.key !== key) throw malformed();
  const people = array(result.assignable_people, value => {
    const p = record(value); return {...person(p), departments: array(p.departments, text)};
  });
  const named = (p: AssignmentPerson | null) => p && p.name === '姓名待確認' ? people.find(candidate => candidate.open_id === p.open_id) || p : p;
  return {...envelope(result), can: permissions(result.can), record_id: optionalText(result.record_id), node: {...parsedNode, assigned_by: named(parsedNode.assigned_by), approver: named(parsedNode.approver)},
    tasks: array(result.tasks, task).map(t => ({...t, assignee: named(t.assignee), assigned_by: named(t.assigned_by)})), assignable_people: people};
}
export function requestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export async function mutateNodeAssignment(projectId: string, mutation: AssignmentMutation, signal: AbortSignal, isCurrent: () => boolean, id = requestId()): Promise<NodeAssignmentDetail> {
  const nodePath = `${basePath(projectId)}/nodes/${encodeURIComponent(mutation.nodeKey)}`;
  let url: string, body: object, method = 'POST';
  switch (mutation.action) {
    case 'assign': url = `${nodePath}/assign`; body = {owner_open_ids: mutation.owner_open_ids}; break;
    case 'reject': url = `${nodePath}/reject`; body = {reason: mutation.reason}; break;
    case 'create_task': url = `${nodePath}/tasks`; body = Object.fromEntries(Object.entries(mutation.task).filter(([key, value]) => key === 'title' || value !== '')); break;
    case 'update_task': url = `${nodePath}/tasks/${encodeURIComponent(mutation.taskId)}`; body = mutation.patch; method = 'PATCH'; break;
    default: url = `${nodePath}/${mutation.action}`; body = {};
  }
  if (mutation.action !== 'create_task') body = {...body, expected_revision: mutation.expected_revision};
  return parseDetail(record(await assignmentRequest(url, {signal, method, body: JSON.stringify({...body, request_id: id})}, isCurrent)), mutation.nodeKey);
}
const ERROR_MESSAGES: Record<string, string> = {
  revision_conflict: '資料已被他人更新，已為你重新載入', illegal_transition: '目前狀態不允許此操作，請重新讀取後再試。',
  forbidden: '目前沒有此操作權限。', writes_disabled: '節點修改已停用，請聯絡管理員。', rate_limited: '操作過於頻繁，請稍後重試。',
  busy: '其他操作尚未完成，請稍後重試。', outcome_unknown: '尚無法確認儲存結果，請重試此操作。', readback_mismatch: '尚無法確認儲存結果，請重試此操作。',
  lark_permission: 'Lark 權限不足，請聯絡管理員', lark_unavailable: 'Lark 暫時無法使用，請稍後重試。', roster_unavailable: '無法確認最新人員名單，請稍後重試。',
};
export const assignmentErrorMessage = (error: unknown) => error instanceof NodeAssignmentError && error.code && ERROR_MESSAGES[error.code]
  ? ERROR_MESSAGES[error.code] : error instanceof Error ? error.message : '節點資料讀取失敗，請稍後重試。';
export const assignmentsDisabled = (error: unknown) => error instanceof NodeAssignmentError && error.code === 'disabled';

export function assignmentTarget(route: {node?: string; task?: string}, nodes: {id: string; key: string}[] = []) {
  const key = NODE_ASSIGNMENT_ORDER.find(key => key === route.node);
  if (key) return {nodeKey: key, taskId: route.task || ''};
  if (route.task && /^rec[A-Za-z0-9]+$/.test(route.task)) {
    const legacyNode = nodes.find(n => n.id === route.node);
    return {nodeKey: legacyNode?.key || '', taskId: route.task};
  }
  return undefined;
}

export function sortAssignmentTasks(tasks: AssignmentTask[], today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date())) {
  const priority: Record<string, number> = {'進行中': 0, '待處理': 1, '已完成': 2, '取消': 3};
  const overdue = (t: AssignmentTask) => !!t.deadline && t.deadline.slice(0, 10) < today && !['已完成', '取消'].includes(t.status);
  return [...tasks].sort((a, b) => Number(overdue(b)) - Number(overdue(a)) || Number(!a.deadline) - Number(!b.deadline)
    || (a.deadline || '').localeCompare(b.deadline || '') || (priority[a.status] ?? 4) - (priority[b.status] ?? 4) || a.id.localeCompare(b.id));
}
