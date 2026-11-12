// VCC-130: pure, unwired projection of backend/case_detail.py @ 9747c16.
// P2-INT: FilterSet and SortSpec mirror drilldownContext.ts @ a529080;
// selection uses this model's opaque row key, never a name/case-number join.
import {DATA_STATE_LABELS, parseDataState} from './dataState.ts';
import type {DataStateName} from './dataState.ts';
export type FilterSet = Readonly<Record<string, string>>;
export type SortSpec = {key: string; dir: 'asc' | 'desc'} | null;
export interface CaseDetailOptions {filters?: FilterSet; sort?: SortSpec; selected?: string | null}
type Rec = Record<string, any>;
export interface DisplayField {label: string; text: string; reason: string | null}
export interface StateView {states: DataStateName[]; label: string; reason: string | null}
export interface DetailRow {
 key: string; kind: string; title: DisplayField; status: DisplayField;
 relationship: string; unresolved: boolean; reason: string | null;
 sourceLink: {label: string; url: string | null; reason: string | null};
 amount: DisplayField | null; fields: DisplayField[]; children: DetailRow[];
}
export const PLAN_CATEGORIES = ['外業', '控制', '圖資', '報告'] as const;
export type PlanCategory = typeof PLAN_CATEGORIES[number];
export interface PlanCategoryCounts {
 lines: number; planned_qty: string; items: number; items_native: number; items_derived: number;
 items_ambiguous: number; items_unlinked: number; items_native_unresolved: number; needs_review: number;
}
export interface PlanSummary {
 needsReview: boolean;
 basis: Record<'native' | 'derived' | 'ambiguous' | 'unlinked' | 'native_unresolved', number>;
 lines_basis: {native: number; derived: number};
 categories: Record<PlanCategory, PlanCategoryCounts>;
 truncated: boolean;
}
export interface SectionView extends StateView {
 planSummary: PlanSummary | null | 'unavailable'; key: string; title: string; sourceTime: DisplayField; freshness: string | null; rows: DetailRow[];
}
export interface CaseDetailView {
 page: StateView; header: DisplayField[]; sourceLink: {label: string; url: string | null; reason: string | null}; sections: SectionView[];
 tree: {root: DetailRow | null; children: DetailRow[]; expanded: {key: string; children: DetailRow[]} | null};
 side: {relationshipCompleteness: DisplayField; warnings: DetailRow[]; sourceTimes: {section: string; time: DisplayField; freshness: string | null}[]; responsibility: DisplayField; operations: string};
 drawer: {selectionOnly: true; row: DetailRow; identifiers: Record<string, string | null>; parents: {label: string; verification: string}[]; relationshipCounts: Record<string, number> | null; countBasis: string | null; navigation: {route: 'confirmation' | 'contract' | 'workitem'; nativeKey: string} | null; reportsDocuments: {view: string; project: string; tab: string; section: string} | null; sourceHealth: {view: 'sources'}} | null;
}
const TITLES: Record<string, string> = {overview: '總覽', versions: '確認單版本', contract_lines: '合約明細', work_items: '工項', workflow_nodes: '流程節點／SOP', reports_documents: '報告與文件', history: '歷程'};
const names = Object.keys(TITLES);
const rec = (v: unknown): v is Rec => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0;
const nullable = (v: unknown) => v === null || typeof v === 'string';
const scalar = (v: unknown) => v === null || typeof v === 'string' || typeof v === 'number' && Number.isFinite(v);
const array = (v: unknown, guard: (x: any) => boolean): boolean => Array.isArray(v) && Array.from(v).every(guard);
const optional = (o: Rec, k: string, guard: (v: any) => boolean) => !Object.hasOwn(o, k) || guard(o[k]);
function validStates(v: unknown): boolean {
 if (!Array.isArray(v)) return false;
 if (!v.length) return true; // backend explicitly uses [] for complete, nonempty reads
 const p = parseDataState({states: v});
 const parsed: readonly DataStateName[] = p.states;
 return parsed.length === v.length && v.every(s => parsed.includes(s));
}
const withStates = (v: unknown) => rec(v) && validStates(v.states);
const person = (v: unknown) => rec(v) && nullable(v.name) && optional(v, 'states', validStates) && optional(v, 'reason', nullable);
const withheld = (v: unknown) => rec(v) && v.state === 'withheld' && v.reason === 'G-AMT';
const edge = (v: unknown) => rec(v) && str(v.edge_type) && str(v.parent_key) && nullable(v.child_key) &&
 optional(v, 'cardinality', x => ['one','many','containment'].includes(x)) && optional(v, 'contested', x => typeof x === 'boolean') && str(v.verification) && optional(v, 'reason', nullable);
const parent = (v: unknown) => rec(v) && str(v.edge_type) && str(v.parent_key) && typeof v.contested === 'boolean' && str(v.verification);
function validRow(v: unknown, history = false, depth = 0): boolean {
 if (!rec(v) || depth > 1) return false;
 if (history) return Object.hasOwn(v, 'confirmation_key') ? str(v.confirmation_key) && scalar(v.revision) && nullable(v.replaced_at) :
  nullable(v.event_id) && nullable(v.action) && nullable(v.created_at);
 return str(v.key) && ['confirmation','contract','work_item','node','task','evidence'].includes(v.kind) && nullable(v.label) && array(v.parents, parent) &&
 ['code','source_url','item_number','status','node_id','task_id'].every(k => optional(v, k, nullable)) &&
 optional(v, 'revision', scalar) && optional(v, 'selected', x => typeof x === 'boolean') && optional(v, 'amount', withheld) &&
 optional(v, 'work_item_links', x => ['located','unresolved'].includes(x)) &&
 optional(v, 'unresolved', x => rec(x) && str(x.reason) && str(x.verification)) &&
 optional(v, 'tasks', x => v.kind === 'node' && array(x, r => rec(r) && r.kind === 'task' && validRow(r, false, depth + 1)));
}
const count = (v: unknown) => Number.isSafeInteger(v) && Number(v) >= 0;
function validPlanSummary(v: unknown): v is Omit<PlanSummary, 'needsReview'> {
 return rec(v) && rec(v.basis) &&
 ['native','derived','ambiguous','unlinked','native_unresolved'].every(k => count(v.basis[k])) &&
 rec(v.lines_basis) && count(v.lines_basis.native) && count(v.lines_basis.derived) && rec(v.categories) &&
 PLAN_CATEGORIES.every(k => {
  const c = v.categories[k];
  return rec(c) && typeof c.planned_qty === 'string' && /^\d+(?:\.\d+)?(?:[eE][+-]?\d{1,4})?$/.test(c.planned_qty) &&
   ['lines','items','items_native','items_derived','items_ambiguous','items_unlinked','items_native_unresolved','needs_review'].every(n => count(c[n]));
 }) && typeof v.truncated === 'boolean';
}
function projectPlanSummary(value: unknown): PlanSummary | null | 'unavailable' {
 if (value == null) return null;
 if (!validPlanSummary(value)) return 'unavailable';
 return {
  needsReview: PLAN_CATEGORIES.some(k => value.categories[k].needs_review > 0),
  basis: {native: value.basis.native, derived: value.basis.derived, ambiguous: value.basis.ambiguous, unlinked: value.basis.unlinked, native_unresolved: value.basis.native_unresolved},
  lines_basis: {native: value.lines_basis.native, derived: value.lines_basis.derived},
  categories: Object.fromEntries(PLAN_CATEGORIES.map(k => {
   const c = value.categories[k];
   return [k, {lines: c.lines, planned_qty: c.planned_qty, items: c.items, items_native: c.items_native, items_derived: c.items_derived, items_ambiguous: c.items_ambiguous, items_unlinked: c.items_unlinked, items_native_unresolved: c.items_native_unresolved, needs_review: c.needs_review}];
  })) as Record<PlanCategory, PlanCategoryCounts>,
  truncated: value.truncated,
 };
}
const PLAIN_DECIMAL = /^\d+(?:\.\d+)?(?:[eE][+-]?\d{1,4})?$/;
export const isPlainDecimal = (value: unknown): value is string => typeof value === 'string' && value.length <= 100 && PLAIN_DECIMAL.test(value);
export function formatPlanQuantity(value: string): string {
 if (value.length <= 100 && /^-?0+(?:\.0+)?(?:[eE][+-]?\d{1,4})?$/.test(value)) return '0';
 if (!isPlainDecimal(value)) return '—';
 const [coefficient, exponent = '0'] = value.toLowerCase().split('e');
 const [whole, fraction = ''] = coefficient.split('.');
 const digits = whole + fraction;
 const point = whole.length + Number(exponent);
 const plain = point <= 0 ? '0.' + '0'.repeat(-point) + digits : point >= digits.length ? digits + '0'.repeat(point - digits.length) : digits.slice(0, point) + '.' + digits.slice(point);
 return plain.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '').replace(/^0+(?=\d)/, '') || '0';
}
export function hasPlanDerivation(summary: PlanSummary): boolean {
 return summary.basis.derived > 0 || summary.basis.ambiguous > 0 || summary.lines_basis.derived > 0 ||
  PLAN_CATEGORIES.some(k => {const c = summary.categories[k]; return (c.lines > 0 || c.items > 0) && (c.items_derived > 0 || c.items_ambiguous > 0);});
}
function validSection(v: unknown, name: string): boolean {
 return rec(v) && withStates(v) && (!v.states.some((s: string) => ['complete_empty', 'filtered_empty'].includes(s)) || Array.isArray(v.rows) && v.rows.length === 0) && (v.freshness === null || v.freshness === 'stale') && nullable(v.reason) &&
 rec(v.source_time) && nullable(v.source_time.value) && v.source_time.basis === 'source_sync_completed' && nullable(v.source_time.fetched_at) &&
 array(v.rows, r => validRow(r, name === 'history') && (name === 'history' || r.kind === ({versions: 'confirmation', contract_lines: 'contract', work_items: 'work_item', workflow_nodes: 'node', reports_documents: 'evidence'} as Record<string, string>)[name])) && rec(v.details) &&
 optional(v.details, 'unresolved_edges', x => array(x, edge)) &&
 optional(v.details, 'entry_point', x => rec(x) && x.view === 'project' && str(x.project) && x.tab === 'data' && x.section === 'files') &&
 optional(v.details, 'case_identity', str) && optional(v.details, 'read_only', x => x === true) && optional(v.details, 'note', str);
}
function validBody(v: unknown): v is Rec {
 if (!rec(v) || !str(v.project_id) || !validStates(v.page_state) || !rec(v.sections)) return false;
 if (v.header === null) return v.page_state.length > 0 && Object.keys(v.sections).length === 0 && str(v.reason);
 const h = v.header;
 if (!rec(h) || !names.every(n => validSection(v.sections[n], n)) || Object.keys(v.sections).some(n => !names.includes(n))) return false;
 const d = h.details, dates = h.dates;
 if (v.sections.reports_documents.details.entry_point && v.sections.reports_documents.details.entry_point.project !== v.project_id) return false;
 return nullable(h.project_name) && nullable(h.case_number) && rec(h.selected_confirmation) && nullable(h.selected_confirmation.key) &&
 optional(h.selected_confirmation, 'code', nullable) && optional(h.selected_confirmation, 'reason', nullable) &&
 array(h.other_versions, x => rec(x) && str(x.key) && nullable(x.code)) && person(h.pm) && person(h.responsible_person) &&
 rec(h.admission) && str(h.admission.execution_system) && str(h.admission.execution_system_label) && nullable(h.admission.execution_readonly_reason) && nullable(h.admission.case_visibility) && str(h.admission.explanation) &&
 rec(h.current_stage) && (h.current_stage.state === 'unknown' && str(h.current_stage.reason) || h.current_stage.state === 'verified' && str(h.current_stage.node_id) && nullable(h.current_stage.label)) &&
 rec(dates) && [dates.effective_approved, dates.estimated].every(x => rec(x) && x.state === 'unknown' && str(x.reason)) &&
 array(dates.pending_requested, x => rec(x) && nullable(x.approval_id) && nullable(x.task_key) && nullable(x.requested_due_date) && x.status === 'pending') &&
 withStates(h.blockers) && array(h.blockers.items, str) && rec(h.source_link) && nullable(h.source_link.url) &&
 optional(h.source_link, 'states', validStates) && optional(h.source_link, 'basis', x => x === 'authorized_source_reference') && withheld(h.contract_amounts) &&
 rec(d) && str(d.case_identity) && d.case_identity === v.project_id && nullable(d.confirmation_identity) && rec(d.relationship_counts) &&
 str(d.relationship_counts.basis) && ['confirmations','contracts','work_items','tasks'].every(k => Number.isSafeInteger(d.relationship_counts[k]) && d.relationship_counts[k] >= 0) &&
 rec(d.complete_ids) && array(d.complete_ids.contracts, str) && array(d.complete_ids.work_items, str) && array(d.edges, edge) && str(d.edge_verification);
}
const field = (label: string, value: unknown, reason = 'field_not_supplied'): DisplayField => ({label, text: str(value) ? value : '—', reason: str(value) ? null : reason});
const sourceLink = (v: unknown) => {
 let url: string | null = null;
 if (str(v)) {try {const u = new URL(v); if (['https:', 'http:'].includes(u.protocol) && !u.username && !u.password) url = v;} catch { /* no guessed URL */ }}
 return {label: '授權來源', url, reason: url ? null : 'source_link_unlocated'};
};
const money = (): DisplayField => ({label: '合約金額', text: '未核准顯示', reason: 'G-AMT'});
function state(states: DataStateName[], reason: string | null): StateView {
 const parsed = states.length ? parseDataState({states}) : null;
 const out = parsed ? [...parsed.states] : [];
 return {states: out, label: out.length ? out.map(s => DATA_STATE_LABELS[s]).join('・') : '已讀取', reason};
}
function blank(reason: string, states: DataStateName[] = ['unknown']): CaseDetailView {
 return {page: state(states, reason), header: [], sourceLink: sourceLink(null), sections: [], tree: {root: null, children: [], expanded: null},
 side: {relationshipCompleteness: field('關係完整性', null, reason), warnings: [], sourceTimes: [], responsibility: field('負責人', null, reason), operations: '唯讀'}, drawer: null};
}

export function buildCaseDetailView(input: unknown, options: CaseDetailOptions = {}): CaseDetailView {
 // Validate the entire read body before projecting any fact. Unknown extra keys
 // are never copied (including injected money/formulas/actions/receipt strings).
 if (!validBody(input)) return blank('malformed_case_detail_body');
 const b = input, h = b.header;
 if (b.page_state.length || !h) return blank(b.reason ?? 'page_unavailable', b.page_state);
 const rawByKey = new Map<string, Rec>(), viewByKey = new Map<string, DetailRow>();
 const rawByOpaque = new Map<string, Rec>();
 let serial = 0;
 const opaque = (identity: string): string => {
  let hash = 14695981039346656037n;
  for (const byte of new TextEncoder().encode(identity)) hash = BigInt.asUintN(64, (hash ^ BigInt(byte)) * 1099511628211n);
  return `row:${hash.toString(16)}`;
 };
 const row = (r: Rec): DetailRow => {
  const key = opaque(r.key ?? JSON.stringify(r.confirmation_key ? [r.confirmation_key, r.revision, r.replaced_at] : [r.event_id, r.action, r.created_at]));
  if (rawByOpaque.has(key)) throw new Error('duplicate_identity');
  const unresolved = !!r.unresolved || r.work_item_links === 'unresolved';
  const out: DetailRow = {key, kind: r.kind ?? 'history', title: field('名稱', r.label ?? r.action ?? r.revision?.toString()),
   status: field('狀態', r.status), relationship: r.parents?.length || unresolved ? '對應未驗證' : '—', unresolved,
   sourceLink: sourceLink(r.source_url), reason: r.unresolved?.reason ?? (unresolved ? 'edge_not_located' : null), amount: r.kind === 'contract' ? money() : null,
   fields: [], children: []};
  if (r.kind === 'confirmation') out.fields.push(field('版本', r.code), field('修訂', r.revision?.toString()));
  if (r.kind === 'contract') out.fields.push(field('項次', r.item_number));
  if (!r.kind) out.fields.push(field('取代時間', r.replaced_at), field('事件時間', r.created_at));
  if (r.key) {
   if (rawByKey.has(r.key)) throw new Error('duplicate_identity');
   rawByKey.set(r.key, r); viewByKey.set(r.key, out);
  }
  rawByOpaque.set(key, r);
  out.children = (r.tasks ?? []).map(row);
  return out;
 };
 const warning = (reason: string): DetailRow => ({key: `edge:${serial++}`, kind: 'unresolved_edge', title: field('關係', null, reason), status: field('狀態', '對應未驗證'), relationship: '對應未驗證', unresolved: true, reason, sourceLink: sourceLink(null), amount: null, fields: [], children: []});
 let sections: SectionView[];
 try {
  sections = names.map(n => {
   const s = b.sections[n], blocked = s.states.some((x: string) => ['forbidden','loading','read_failed','unlocated'].includes(x));
   return {planSummary: n === 'work_items' && !blocked ? projectPlanSummary(s.details.plan_summary) : null, key: n, title: TITLES[n], ...state(s.states, s.reason), sourceTime: blocked && s.states.includes('forbidden') ? field('來源同步完成時間', null, 'forbidden') : field('來源同步完成時間', s.source_time.value, 'source_time_unknown'), freshness: s.freshness === 'stale' || s.states.includes('stale') ? DATA_STATE_LABELS.stale : null, rows: blocked ? [] : s.rows.map((r: Rec) => row(n === 'history' ? str(r.confirmation_key) ? {confirmation_key: r.confirmation_key, revision: r.revision, replaced_at: r.replaced_at} : {event_id: r.event_id, action: r.action, created_at: r.created_at} : r))};
  });
 } catch {return blank('duplicate_identity');}
 const warnings: DetailRow[] = [];
 for (const s of sections) {
  const raw = b.sections[s.key];
  if (s.states.some(x => ['forbidden','loading','read_failed','unlocated'].includes(x))) continue;
  for (const e of raw.details.unresolved_edges ?? []) {const w = warning(e.reason ?? 'edge_not_located'); s.rows.push(w); warnings.push(w);}
  const collect = (r: DetailRow) => {if (r.unresolved) warnings.push(r); r.children.forEach(collect);};
  s.rows.filter(r => r.kind !== 'unresolved_edge').forEach(collect);
 }
 const root: DetailRow = {key: 'case', kind: 'case', title: field('案件', h.project_name), status: field('狀態', null), relationship: '對應未驗證', unresolved: false, reason: null, sourceLink: sourceLink(h.source_link.url), amount: null, fields: [], children: []};
 const caseKey = `case:${b.project_id}`;
 const suppressedKeys = new Set<string>();
 for (const n of names) if (b.sections[n].states.includes('forbidden')) {
  for (const r of b.sections[n].rows) {if (r.key) suppressedKeys.add(r.key); for (const t of r.tasks ?? []) suppressedKeys.add(t.key);}
 }
 const childrenOf = (native: string): DetailRow[] => b.header.details.edges.filter((e: Rec) => e.parent_key === native && !suppressedKeys.has(e.parent_key) && !suppressedKeys.has(e.child_key)).map((e: Rec) => {const found = viewByKey.get(e.child_key); return found ? {...found, children: []} : warning('no_authorized_edge_target');});
 for (const e of h.details.edges) if (!suppressedKeys.has(e.parent_key) && !suppressedKeys.has(e.child_key) && !viewByKey.has(e.child_key)) warnings.push(warning('no_authorized_edge_target'));
 const treeChildren = childrenOf(caseKey);
 const selectedRow = options.selected === 'case' ? root : Array.from(viewByKey.values()).find(r => r.key === options.selected) ?? sections.flatMap(s => s.rows).find(r => r.key === options.selected);
 const selectedRaw: Rec | undefined = selectedRow?.key === 'case' ? {key: caseKey, parents: []} : selectedRow ? rawByOpaque.get(selectedRow.key) : undefined;
 const versionForbidden = b.sections.versions.states.includes('forbidden');
 const workflowForbidden = b.sections.workflow_nodes.states.includes('forbidden');
 const sourceForbidden = versionForbidden || h.source_link.states?.includes('forbidden');
 root.sourceLink = sourceForbidden ? sourceLink(null) : sourceLink(h.source_link.url);
 const personField = (label: string, p: Rec, forbidden = false) => field(label, forbidden || p.states?.length ? null : p.name, forbidden || p.states?.includes('forbidden') ? 'forbidden' : p.reason);
 const responsibility = personField('負責人', h.responsible_person, workflowForbidden);
 const header = [field('專案', h.project_name), field('案件編號', h.case_number), field('確認單版本', versionForbidden ? null : h.selected_confirmation.code, versionForbidden ? 'forbidden' : h.selected_confirmation.reason),
  field('納入狀態', h.admission.execution_system_label), field('納入說明', h.admission.execution_readonly_reason ?? h.admission.explanation), personField('PM', h.pm), responsibility,
  field('目前階段', !workflowForbidden && h.current_stage.state === 'verified' ? h.current_stage.label : null, workflowForbidden ? 'forbidden' : h.current_stage.reason),
  field('生效核准日期', null, h.dates.effective_approved.reason), ...h.dates.pending_requested.map((d: Rec) => field('待核准申請日期', d.requested_due_date, 'requested_date_unknown')),
  field('預估日期', null, h.dates.estimated.reason), field('阻礙', workflowForbidden || h.blockers.states.length ? null : h.blockers.items.join('、'), 'blockers_unknown'), money()];
 const search = options.filters?.search?.trim().toLowerCase();
 for (const s of sections) {
  if (search) s.rows = s.rows.filter(r => r.unresolved || r.title.text.toLowerCase().includes(search));
  if (options.sort?.key === 'title') s.rows.sort((a,b) => (a.title.text < b.title.text ? -1 : a.title.text > b.title.text ? 1 : 0) * (options.sort?.dir === 'desc' ? -1 : 1));
 }
 const suppressed = sections.some(s => s.states.some(x => ['forbidden','unknown','loading','read_failed','unlocated'].includes(x)));
 const counts = h.details.relationship_counts;
 return {page: state([], null), header, sourceLink: sourceForbidden ? sourceLink(null) : sourceLink(h.source_link.url), sections,
  tree: {root, children: treeChildren, expanded: options.selected === 'case' ? {key: 'case', children: treeChildren} : selectedRaw?.key ? {key: selectedRow!.key, children: childrenOf(selectedRaw.key)} : null},
  side: {relationshipCompleteness: field('關係完整性', null, 'receipt_missing'), warnings, sourceTimes: sections.map(s => ({section: s.title, time: s.sourceTime, freshness: s.freshness})), responsibility, operations: '唯讀'},
  drawer: selectedRow && selectedRaw ? {selectionOnly: true, row: selectedRow, identifiers: {case_identity: b.project_id, record_key: selectedRaw.key ?? null, node_id: selectedRaw.node_id ?? null, task_id: selectedRaw.task_id ?? null, confirmation_key: viewByKey.has(selectedRaw.confirmation_key) ? selectedRaw.confirmation_key : null, event_id: selectedRaw.event_id ?? null},
   parents: (selectedRaw.parents ?? []).map((p: Rec) => ({label: viewByKey.get(p.parent_key)?.title.text ?? (p.parent_key === caseKey ? root.title.text : '—'), verification: '對應未驗證'})),
   relationshipCounts: suppressed ? null : {confirmations: counts.confirmations, contracts: counts.contracts, work_items: counts.work_items, tasks: counts.tasks}, countBasis: suppressed ? null : counts.basis,
   navigation: selectedRaw.key && ['confirmation','contract','work_item'].includes(selectedRow.kind) ? {route: selectedRow.kind === 'work_item' ? 'workitem' : selectedRow.kind as 'confirmation' | 'contract', nativeKey: selectedRaw.key} : null,
   reportsDocuments: b.sections.reports_documents.states.includes('forbidden') ? null : b.sections.reports_documents.details.entry_point ? {view: 'project', project: b.sections.reports_documents.details.entry_point.project, tab: 'data', section: 'files'} : null, sourceHealth: {view: 'sources'}} : null};
}
