import {SOP_NODE_KEYS, type Applicability, type ImportPreview, type Lifecycle, type PreviewOutcome, type SopCounts, type SopNodeKey, type SopTask} from './sopTaskApi';

export const STATE_LABEL: Record<Lifecycle, string> = {pending: '待處理', in_progress: '進行中', blocked: '受阻', done: '已完成', archived: '已封存'};
export const APPLICABILITY_LABEL: Record<Applicability, string> = {applicable: '適用', not_applicable: '不適用', unresolved: '適用待確認'};
export const ROLE_LABEL = {executor: '執行', checker: '檢核', confirmer: '確認'} as const;
export const stateLabel = (t: SopTask) => t.applicability === 'not_applicable' && t.state !== 'archived' ? '不適用' : STATE_LABEL[t.state];
export const dueLabel = (t: SopTask) => t.dueDate || '期限待確認';

const nodeIndex = (key: SopNodeKey) => SOP_NODE_KEYS.indexOf(key);
// Canonical node order, then source order inside the node; manual tasks after template tasks.
function sortKey(t: SopTask, scope?: SopNodeKey): [number, number, number] {
 const links = scope ? t.nodes.filter(n => n.node_key === scope) : t.nodes;
 const first = links.reduce<[number, number]>((best, n) => {const k: [number, number] = [nodeIndex(n.node_key), n.order]; return k[0] < best[0] || (k[0] === best[0] && k[1] < best[1]) ? k : best}, [99, Number.MAX_SAFE_INTEGER]);
 return [t.manual ? 1 : 0, ...first];
}
export function orderTasks(tasks: SopTask[], scope?: SopNodeKey): SopTask[] {
 const keyed = tasks.map(t => ({t, k: sortKey(t, scope)}));
 keyed.sort((a, b) => a.k[0] - b.k[0] || a.k[1] - b.k[1] || a.k[2] - b.k[2] || (a.t.id < b.t.id ? -1 : a.t.id > b.t.id ? 1 : 0));
 return keyed.map(x => x.t);
}

export type SopFilter = 'mine'|'unassigned'|'overdue'|'pending';
export const FILTERS: [SopFilter, string][] = [['mine','我的任務'],['unassigned','未指派'],['overdue','逾期'],['pending','待確認']];
const MATCH: Record<SopFilter, (t: SopTask, me: string) => boolean> = {
 mine: (t, me) => !!me && t.participants.executor === me,
 unassigned: t => !t.participants.executor,
 overdue: t => t.overdue,
 pending: t => t.applicability === 'unresolved',
};
export interface ListView {scope?: SopNodeKey; filters: SopFilter[]; history: boolean}
export function visibleTasks(tasks: SopTask[], view: ListView, me: string): SopTask[] {
 const scoped = view.scope ? tasks.filter(t => t.nodes.some(n => n.node_key === view.scope)) : tasks;
 return orderTasks(scoped.filter(t => (t.state === 'archived') === view.history && view.filters.every(f => MATCH[f](t, me))), view.scope);
}

// Mirrors the server rule so filtered views can label their own count.
export function countTasks(tasks: SopTask[]): SopCounts {
 const active = tasks.filter(t => t.state !== 'archived');
 const applicable = active.filter(t => t.applicability === 'applicable');
 return {done: applicable.filter(t => t.state === 'done').length, total: applicable.length,
  unresolved: active.filter(t => t.applicability === 'unresolved').length,
  not_applicable: active.filter(t => t.applicability === 'not_applicable').length, archived: tasks.length - active.length};
}
const OPEN_STATES: Lifecycle[] = ['pending','in_progress','blocked'];
// Tasks the server will close for a node the data proves done: open, applicable and linked only to proven nodes.
export const closableTasks = (tasks: SopTask[], node: SopNodeKey, proven: Partial<Record<SopNodeKey, unknown>>) =>
 tasks.filter(t => OPEN_STATES.includes(t.state) && t.applicability === 'applicable' && t.nodes.some(n => n.node_key === node) && t.nodes.every(n => proven[n.node_key]));
export const progressLabel = (c: SopCounts) => c.total ? `${c.done}/${c.total}` : '無適用任務';
export const checklistComplete = (c: SopCounts) => c.total > 0 && c.done === c.total && c.unresolved === 0;

export type ImportGroup = 'new'|'imported'|'pending'|'excluded'|'review';
export const GROUP_LABEL: [ImportGroup, string][] = [['new','新增'],['imported','已匯入'],['pending','待確認'],['excluded','已排除'],['review','需範本審核']];
export const selectable = (o: PreviewOutcome) => o.disposition === 'task';
export function outcomeGroup(o: PreviewOutcome): ImportGroup|null {
 if (o.disposition === 'review_required') return 'review';
 if (o.disposition === 'routing_reference') return null;
 if (!selectable(o)) return 'excluded';
 if (o.existing_task_id) return 'imported';
 if (o.applicability === 'unresolved') return 'pending';
 return o.selected ? 'new' : 'excluded';
}
export function groupOutcomes(preview: ImportPreview) {
 const groups = GROUP_LABEL.map(([key, label]) => ({key, label, rows: preview.outcomes.filter(o => outcomeGroup(o) === key)}));
 return {groups: groups.filter(g => g.rows.length), references: preview.outcomes.filter(o => outcomeGroup(o) === null).length};
}
export type Decisions = Record<string, string>;
// The default plan leaves only subcontract rows unselected, and the server requires an applicable decision to select one, even when its task already exists.
export const needsDecision = (o: PreviewOutcome, defaults: ReadonlySet<string>) => selectable(o) && !defaults.has(o.source_row_key);
export function selectionBlockers(preview: ImportPreview, selected: ReadonlySet<string>, decisions: Decisions, defaults: ReadonlySet<string>): Record<string, string> {
 const blocked: Record<string, string> = {};
 for (const o of preview.outcomes) {
  if (!selected.has(o.source_row_key)) continue;
  if (!selectable(o)) blocked[o.source_row_key] = '此列不可匯入';
  else if (needsDecision(o, defaults) && !decisions[o.source_row_key]?.trim()) blocked[o.source_row_key] = '需填寫適用原因';
 }
 return blocked;
}
export function previewBody(preview: ImportPreview, selected: ReadonlySet<string>, decisions: Decisions, defaults: ReadonlySet<string>) {
 const rows = preview.outcomes.filter(o => selected.has(o.source_row_key)).map(o => o.source_row_key);
 const applicability_decisions = Object.fromEntries(preview.outcomes.filter(o => selected.has(o.source_row_key) && needsDecision(o, defaults)).map(o => [o.source_row_key, {value: 'applicable' as const, reason: decisions[o.source_row_key].trim()}]));
 return {template_version_id: preview.template.version_id, node_keys: preview.nodeKeys, row_keys: rows, ...(Object.keys(applicability_decisions).length ? {applicability_decisions} : {})};
}
export const sameSelection = (preview: ImportPreview, selected: ReadonlySet<string>) => preview.rowKeys.length === selected.size && preview.rowKeys.every(k => selected.has(k));

export type TaskAction = 'start'|'block'|'resume'|'reset'|'complete'|'reopen'|'archive'|'restore';
export const ACTIONS: {action: TaskAction; label: string; reason: boolean}[] = [
 {action:'start',label:'開始',reason:false}, {action:'complete',label:'完成',reason:false},
 {action:'block',label:'標記受阻',reason:true}, {action:'resume',label:'繼續',reason:true},
 {action:'reset',label:'退回待處理',reason:true}, {action:'reopen',label:'重新開啟',reason:true},
 {action:'archive',label:'封存',reason:true}, {action:'restore',label:'還原',reason:true},
];
export function taskActions(t: SopTask) {return ACTIONS.filter(a => t.allowedActions.includes(a.action))}
export const suggestionLabel = (s: NonNullable<SopTask['suggestion']>) => s.state === 'done' ? '建議完成' : '建議進行中';
export const suggestionTier = (s: NonNullable<SopTask['suggestion']>) => s.tier === 'proof' ? '佐證' : '指標';
export const suggestionSelection = (tasks: SopTask[]) => tasks.filter(t => t.suggestion && t.allowedActions.includes('accept_suggestion'));
export function suggestionBody(tasks: SopTask[], confirm: boolean, reason: string, confirmedTaskIds: string[] = []) {
 return {tasks: tasks.flatMap(t => t.suggestion ? [{task_id:t.id,facts_hash:t.suggestion.hash,expected_revision:t.revision}] : []),confirm,reason:reason.trim(),confirmed_task_ids:confirmedTaskIds};
}
export const requiresSuggestionConfirmation = (tasks: SopTask[]) => tasks.some(t => t.suggestion?.tier === 'indicator');

export const canOperateTestTasks = (user: {role?:string;active?:boolean}|null|undefined) => !!user && user.active !== false && ['manager','admin'].includes(user.role || '');
