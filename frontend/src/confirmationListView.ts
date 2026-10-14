// VCC-129: pure, unwired projection of build_confirmation_list's JSON body.
// P2-INT: these local FilterSet / SortSpec names mirror drilldownContext.ts
// (a529080). Translate admission -> admission_state and search -> q at the
// transport boundary; never filter, reorder, or paginate this server page here.
import {describeDataState, parseDataState} from './dataState.ts';
import type {DataState} from './dataState.ts';

export type FilterSet = Readonly<Record<string, string>>;
export type SortSpec = {key: string; dir: 'asc' | 'desc'} | null;
export interface ConfirmationListOptions {
 filters?: FilterSet; sort?: SortSpec; cursor?: string | null;
 columns?: readonly string[] | null; selected?: string | null;
 // P2-INT owns this history: only cursors actually used in server requests,
 // including null for page one. Bound to the complete filters (search/q
 // included), sort and current cursor; reset it whenever that query changes.
 cursorHistory?: {filters: FilterSet; sort: SortSpec; current: string | null; stack: readonly (string | null)[]};
}
export interface DisplayValue {label: string; reason: string | null}
export interface ConfirmationListRow {
 key: string; cells: Record<string, DisplayValue>;
 sourceStatusLabel: string; retentionLabel: string;
 caseLink: {state: 'linked' | 'unresolved'; label: string; reason: string | null; verificationLabel: string};
}
export interface ConfirmationListView {
 header: {title: string; asOf: DisplayValue; snapshot: DisplayValue};
 pageState: DataState | null; pageStateLabel: string | null; reason: string | null;
 table: {density: 'dense'; stickyColumns: readonly string[]; rows: ConfirmationListRow[]};
 columns: {key: string; label: string; visible: boolean; default: boolean; technical: boolean;
  sortable: boolean; sortDisabledReason: string | null; sortChoices: readonly ['asc', 'desc', 'clear']}[];
 controls: {filters: FilterSet; sort: SortSpec; cursor: string | null;
  deadline: {disabled: true; reason: string}; resetFilters: {filters: FilterSet; cursor: null}};
 footer: {matching: DisplayValue; loaded: DisplayValue; authorizedSource: DisplayValue; basis: string};
 pagination: {kind: 'server_cursor'; next: {enabled: boolean; cursor: string | null; reason: string | null};
  previous: {enabled: boolean; cursor: string | null; reason: string | null}};
 amounts: {state: 'withheld'; label: '未核准顯示'; reason: string};
 drawer: {open: boolean; selectionOnly: true; row: ConfirmationListRow | null;
  detail: {sourceContext: {baseToken: string; tableId: string}; recordId: string; projectId: string | null} | null};
}

const DEFAULT = ['case_number', 'project_name', 'confirmation_version', 'pm', 'admission_state',
 'effective_due', 'workflow_summary', 'source_modified', 'source_status'] as const;
const TECHNICAL = ['record_id', 'source_context'] as const;
const SORTABLE = ['case_number', 'project_name', 'confirmation_version', 'pm', 'admission_state'];
const LABELS: Record<string, string> = {case_number: '案件編號', project_name: '工程名稱', confirmation_version: '確認單版本',
 pm: '案件負責人', admission_state: '准入狀態', effective_due: '有效期限', workflow_summary: '流程節點摘要',
 source_modified: '來源更新時間', source_status: '來源狀態', record_id: '來源記錄 ID', source_context: '來源脈絡'};
const DEADLINE = 'effective due date is unknown: VCC-123 deadline provenance is unresolved';
const MODIFIED = 'no trustworthy source-modified field survives into confirmation entities';
const AMOUNT = 'contract amounts are hidden pending gate G-AMT';
const FILTERS = ['search', 'source_version', 'pm', 'admission', 'deadline_from', 'deadline_to',
 'execution_state', 'pending_decision', 'blocked', 'stage'];
type R = Record<string, unknown>;
const rec = (v: unknown): v is R => v !== null && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && !!v.trim();
const nullableText = (v: unknown): v is string | null => v === null || text(v);
const count = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const nullableCount = (v: unknown) => v === null || count(v);
const cursor = (v: unknown): v is string | null => v === null || typeof v === 'string' && /^[A-Za-z0-9_-]+$/.test(v);
const inSet = (v: unknown, values: readonly string[]) => typeof v === 'string' && values.includes(v);
const unknown = (reason: string): DisplayValue => ({label: '—', reason});
const display = (v: string | null, reason: string): DisplayValue => v === null ? unknown(reason) : {label: v, reason: null};
const same = (v: unknown, values: readonly string[]) => Array.isArray(v) &&
 v.length === values.length && Array.from(v).every((x, i) => x === values[i]);
function validState(v: unknown): boolean {
 if (!rec(v) || !Array.isArray(v.states)) return false;
 const parsed = parseDataState(v);
 const states: readonly string[] = parsed.states;
 return same(v.states, parsed.states) && (v.count === undefined || v.count === null || count(v.count)) &&
  (states.includes('forbidden') || (v.count ?? null) === ('count' in parsed ? parsed.count : null));
}
const unknownField = (v: unknown) => rec(v) && v.state === 'unknown' && v.value === null && text(v.reason);
function validRow(v: unknown): boolean {
 if (!rec(v) || !text(v.row_key) || !nullableText(v.case_number) || !nullableText(v.project_name)) return false;
 const version = v.confirmation_version, pm = v.pm, admission = v.admission, workflow = v.workflow_summary;
 const link = v.case_link, detail = v.detail;
 if (!rec(version) || !inSet(version.state, ['known', 'unknown']) ||
  !(version.state === 'known' ? text(version.value) : version.value === null)) return false;
 if (!rec(pm) || !nullableText(pm.id) || !nullableText(pm.name) || !inSet(pm.state, ['known', 'unknown']) ||
  (pm.state === 'known') !== (pm.id !== null)) return false;
 if (!rec(admission) || !inSet(admission.state, ['unknown', 'pending', 'workbench', 'meegle']) || !nullableText(admission.label) || !nullableText(admission.readonly_reason)) return false;
 if (admission.state === 'unknown' && admission.label !== null) return false;
 if (!unknownField(v.effective_due) || !unknownField(v.source_modified)) return false;
 if (!rec(workflow)) return false;
 if (workflow.state === 'unknown') {if (!text(workflow.reason)) return false;}
 else if (workflow.state === 'known') {
  if (!count(workflow.total) || !count(workflow.completed) || workflow.completed > workflow.total || !rec(workflow.by_status) ||
   !Object.values(workflow.by_status).every(count) || Object.values(workflow.by_status).reduce<number>((sum, n) => sum + (n as number), 0) !== workflow.total ||
   (workflow.by_status.completed ?? 0) !== workflow.completed) return false;
 } else return false;
 if (!inSet(v.source_status, ['located', 'missing', 'unknown', 'stale']) ||
  v.retention !== (v.source_status === 'located' ? 'current' : 'snapshot')) return false;
 if (!rec(link) || link.verification !== 'receipt_missing' || !inSet(link.state, ['linked', 'unresolved']) ||
  !(link.state === 'linked' ? text(link.project_id) && link.reason === null : link.project_id === null && text(link.reason))) return false;
 if (!rec(detail) || detail.non_default !== true || !text(detail.record_id) || !rec(detail.source_context) ||
  !text(detail.source_context.base_token) || !text(detail.source_context.table_id)) return false;
 return true;
}
interface BackendRow {
 row_key: string; case_number: string | null; project_name: string | null;
 confirmation_version: {state: string; value: string | null}; pm: {id: string | null; name: string | null; state: string};
 admission: {state: string; label: string | null; readonly_reason: string | null};
 effective_due: {reason: string}; source_modified: {reason: string};
 workflow_summary: {state: string; total: number; completed: number; reason: string};
 source_status: string; retention: string;
 case_link: {state: 'linked' | 'unresolved'; project_id: string | null; reason: string | null};
 detail: {record_id: string; source_context: {base_token: string; table_id: string}};
}
interface Body {
 as_of: string | null; page_state: DataState | null; rows: BackendRow[]; next_cursor: string | null;
 totals: {matching: number | null; loaded: number; authorized_source: number | null}; totals_basis: string;
 snapshot: {state: string; last_success_at: string | null} | null;
 filter_status: {deadline: {reason: string}}; amounts: {reason: string};
 sort: {applied: {column: string; direction: 'asc' | 'desc'} | null};
}
function validBody(v: R): boolean {
 if (v.status !== 200 || !nullableText(v.as_of) || !(v.page_state === null || validState(v.page_state)) ||
  !Array.isArray(v.rows) || !Array.from(v.rows).every(validRow) || !cursor(v.next_cursor)) return false;
 const rows = v.rows as BackendRow[], totals = v.totals, filters = v.filter_status, sort = v.sort;
 if (new Set(rows.map(r => r.row_key)).size !== rows.length || !rec(totals) || !nullableCount(totals.matching) ||
  !nullableCount(totals.authorized_source) || totals.loaded !== rows.length ||
  (count(totals.matching) && totals.matching < rows.length) ||
  (count(totals.matching) && count(totals.authorized_source) && totals.matching > totals.authorized_source)) return false;
 if (!inSet(v.totals_basis, ['current', 'partial_snapshot', 'retained_snapshot', 'undetermined'])) return false;
 if (v.totals_basis === 'undetermined' ? totals.matching !== null || totals.authorized_source !== null :
  !count(totals.matching) || !count(totals.authorized_source)) return false;
 if (v.snapshot !== null && (!rec(v.snapshot) || !inSet(v.snapshot.state, ['proven', 'unproven']) ||
  !(v.snapshot.state === 'proven' ? text(v.snapshot.last_success_at) : v.snapshot.last_success_at === null))) return false;
 if ((v.totals_basis === 'current') !== (v.snapshot === null)) return false;
 if (!rec(filters) || !rec(filters.deadline) || filters.deadline.status !== 'unavailable' ||
  !text(filters.deadline.reason) || filters.deadline.hides_rows !== false || !rec(filters.deadline.requested) ||
  !Object.entries(filters.deadline.requested).every(([k, x]) => ['deadline_from', 'deadline_to'].includes(k) && text(x))) return false;
 if (!rec(sort) || sort.source_modified !== 'unavailable' || !text(sort.reason) ||
  !(sort.applied === null || rec(sort.applied) && inSet(sort.applied.column, SORTABLE) && inSet(sort.applied.direction, ['asc', 'desc'])) ||
  sort.order_basis !== (sort.applied === null ? 'source_order_then_row_key' : 'column_then_row_key')) return false;
 if (!rec(v.columns) || !same(v.columns.default, DEFAULT) || !same(v.columns.non_default, TECHNICAL) ||
  !rec(v.amounts) || v.amounts.state !== 'withheld' || !text(v.amounts.reason) || !v.amounts.reason.includes('G-AMT')) return false;
 if (!rec(v.excluded_unknown) || !Object.entries(v.excluded_unknown).every(([k, x]) =>
  ['source_version', 'pm', 'admission_state', 'distinct_rows'].includes(k) && count(x)) || !count(v.excluded_unknown.distinct_rows)) return false;
 if (!rec(v.diagnostics) || !count(v.diagnostics.unkeyed_rows) || !count(v.diagnostics.duplicate_versions_collapsed)) return false;
 if (!rec(v.grouping) || !text(v.grouping.basis) || !count(v.grouping.linked_cases) || !count(v.grouping.unresolved_rows) ||
  !Array.isArray(v.grouping.by_case) || !Array.from(v.grouping.by_case).every(g => rec(g) && text(g.project_id) && count(g.rows))) return false;
 const state: readonly string[] = v.page_state === null ? [] : parseDataState(v.page_state).states;
 if (state.some(s => ['partial', 'stale', 'read_failed', 'unknown'].includes(s)) && rec(v.page_state) && v.page_state.count !== null) return false;
 if (state.some(s => ['forbidden', 'loading', 'unlocated'].includes(s))) return false;
 if (state.includes('complete_empty') && (rows.length !== 0 || totals.authorized_source !== 0 || totals.matching !== 0 || v.totals_basis !== 'current')) return false;
 if (state.includes('filtered_empty') && (rows.length !== 0 || totals.matching !== 0 || !count(totals.authorized_source) || totals.authorized_source === 0 || v.totals_basis !== 'current')) return false;
 if (v.page_state === null && (v.totals_basis !== 'current' || rows.some(r => r.retention !== 'current' && r.source_status !== 'missing'))) return false;
 if (v.page_state === null && (!count(totals.matching) || totals.matching === 0)) return false;
 if (state.includes('unknown') && v.totals_basis !== 'undetermined') return false;
 if (state.includes('read_failed') && (v.totals_basis === 'current' || v.totals_basis !== 'undetermined' &&
  (!rec(v.snapshot) || v.snapshot.state !== 'proven'))) return false;
 if (state.some(s => ['partial', 'stale', 'read_failed', 'unknown'].includes(s)) && rows.some(r => r.retention !== 'snapshot')) return false;
 return v.next_cursor === null || rows.length > 0;
}

export function buildConfirmationListView(input: unknown, options: ConfirmationListOptions = {}): ConfirmationListView {
 const raw = rec(input) ? input : {};
 // Revocation wins before any body metadata or UI selection is read.
 const forbidden = raw.status === 403 || rec(raw.page_state) && Array.isArray(raw.page_state.states) && raw.page_state.states.includes('forbidden');
 const shortState = raw.status === 200 && validState(raw.page_state) ? parseDataState(raw.page_state) : null;
 const validShortBody = Array.isArray(raw.rows) && raw.rows.length === 0 && raw.next_cursor === null && rec(raw.totals) &&
  raw.totals.loaded === 0 && raw.totals.matching === null && raw.totals.authorized_source === null;
 const blocked = forbidden || validShortBody && shortState?.states.some(s => ['loading', 'unlocated'].includes(s));
 const valid = !blocked && validBody(raw);
 const b = valid ? raw as unknown as Body : null;
 const pageState: DataState | null = forbidden ? {states: ['forbidden']} : blocked ? shortState : b ? b.page_state : {states: ['unknown'], count: null};
 const reason = forbidden ? '沒有權限' : blocked ? describeDataState(pageState!) : b ? null : 'confirmation list body is malformed or unavailable';
 const f = rec(options.filters) && Object.entries(options.filters).every(([k, v]) => FILTERS.includes(k) && text(v)) ? {...options.filters} : {};
 const wantedColumns: readonly string[] = Array.isArray(options.columns) && Array.from(options.columns).every(c => [...DEFAULT, ...TECHNICAL].includes(c as typeof DEFAULT[number])) ? options.columns : DEFAULT;
 const columns = [...DEFAULT, ...TECHNICAL].map(key => ({key, label: LABELS[key], visible: wantedColumns.includes(key),
  default: (DEFAULT as readonly string[]).includes(key), technical: (TECHNICAL as readonly string[]).includes(key), sortable: SORTABLE.includes(key),
  sortDisabledReason: SORTABLE.includes(key) ? null : key === 'source_modified' ? MODIFIED : 'server contract does not support sorting this column',
  sortChoices: ['asc', 'desc', 'clear'] as const}));
 const rows: ConfirmationListRow[] = b ? b.rows.map(r => ({key: r.row_key,
  cells: {case_number: display(r.case_number, 'case number absent'), project_name: display(r.project_name, 'project name absent'),
   confirmation_version: display(r.confirmation_version.value, 'source version unknown'),
   pm: r.pm.state === 'known' ? display(r.pm.name, 'PM name absent') : unknown('PM assignment unknown'),
   admission_state: display(r.admission.label, r.admission.readonly_reason ?? 'admission state unknown'),
   effective_due: unknown(r.effective_due.reason), source_modified: unknown(r.source_modified.reason),
   workflow_summary: r.workflow_summary.state === 'known' ? {label: `${r.workflow_summary.completed} / ${r.workflow_summary.total} 節點`, reason: null} : unknown(r.workflow_summary.reason),
   source_status: {label: ({located: '已定位', missing: '來源記錄缺失', stale: '資料待更新', unknown: '狀態未知'} as Record<string, string>)[r.source_status], reason: null}},
  sourceStatusLabel: ({located: '已定位', missing: '來源記錄缺失', stale: '資料待更新', unknown: '狀態未知'} as Record<string, string>)[r.source_status],
  retentionLabel: r.retention === 'snapshot' ? '保留快照' : '目前讀取',
  caseLink: {state: r.case_link.state, label: r.case_link.state === 'linked' ? '案件連結（對應未驗證）' : '案件連結未解決',
   reason: r.case_link.reason, verificationLabel: '對應未驗證'}})) : [];
 const selectedIndex = rows.findIndex(r => r.key === options.selected);
 const detail = b && selectedIndex >= 0 ? b.rows[selectedIndex] : null;
 const total = (n: number | null | undefined): DisplayValue => n === null || n === undefined || n === 0 && b?.totals_basis !== 'current' ?
  unknown(reason ?? `total unknown (${b?.totals_basis ?? 'undetermined'})`) : {label: String(n), reason: null};
 const activeSort: SortSpec = forbidden || options.sort === null ? null : options.sort && SORTABLE.includes(options.sort.key) &&
  ['asc', 'desc'].includes(options.sort.dir) ? {...options.sort} : b?.sort.applied ? {key: b.sort.applied.column, dir: b.sort.applied.direction} : null;
 const activeCursor = !forbidden && cursor(options.cursor) ? options.cursor : null;
 const history = options.cursorHistory;
 const canonicalFilters = (x: FilterSet) => JSON.stringify(Object.entries(x).sort(([a], [z]) => a.localeCompare(z)));
 const historyBound = !!b && !!history && rec(history.filters) && Object.entries(history.filters).every(([k, v]) => FILTERS.includes(k) && text(v)) &&
  canonicalFilters(history.filters) === canonicalFilters(f) &&
  (b.sort.applied === null ? activeSort === null : b.sort.applied.column === activeSort?.key && b.sort.applied.direction === activeSort?.dir) &&
  (history.sort === null ? activeSort === null : rec(history.sort) && history.sort.key === activeSort?.key && history.sort.dir === activeSort?.dir) &&
  history.current === activeCursor && Array.isArray(history.stack) && Array.from(history.stack).every(cursor);
 const hasPrevious = historyBound && history!.stack.length > 0;
 return {
  header: {title: '工程確認單', asOf: b ? display(b.as_of, 'read as-of time absent; this is not source-modified time') : unknown(reason!),
   snapshot: b?.snapshot ? display(b.snapshot.last_success_at, 'retained snapshot time unproven') : unknown(reason ?? 'no retained snapshot supplied')},
  pageState, pageStateLabel: pageState ? describeDataState(pageState) : null, reason,
  table: {density: 'dense', stickyColumns: ['case_number', 'project_name'], rows}, columns,
  controls: {filters: forbidden ? {} : f, sort: activeSort, cursor: activeCursor,
   deadline: {disabled: true, reason: b?.filter_status.deadline.reason ?? DEADLINE}, resetFilters: {filters: {}, cursor: null}},
  footer: {matching: total(b?.totals.matching), loaded: total(b?.totals.loaded), authorizedSource: total(b?.totals.authorized_source), basis: b?.totals_basis ?? 'undetermined'},
  pagination: {kind: 'server_cursor', next: {enabled: !!b?.next_cursor, cursor: b?.next_cursor ?? null, reason: b?.next_cursor ? null : reason ?? 'server supplied no next cursor'},
   previous: {enabled: hasPrevious, cursor: hasPrevious ? history!.stack[history!.stack.length - 1] : null,
    reason: hasPrevious ? null : 'no server cursor history bound to the same filters, sort and current cursor'}},
  amounts: {state: 'withheld', label: '未核准顯示', reason: b?.amounts.reason ?? AMOUNT},
  drawer: {open: !!detail, selectionOnly: true, row: selectedIndex >= 0 ? rows[selectedIndex] : null,
   detail: detail ? {sourceContext: {baseToken: detail.detail.source_context.base_token, tableId: detail.detail.source_context.table_id},
    recordId: detail.detail.record_id, projectId: detail.case_link.project_id} : null},
 };
}
