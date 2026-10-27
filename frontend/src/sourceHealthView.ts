import {DATA_STATE_LABELS, parseDataState} from './dataState.ts';
import type {DataState, DataStateName} from './dataState.ts';

// A local adapter contract, not an API response contract. No backend endpoint or
// diagnostic grant is inferred here. Only an existing caller capability enables it.
export interface SourceHealthInput {
 page_state: unknown;
 sources: unknown;
}
export interface SourceHealthOptions {
 diagnosticCapability: boolean;
 selectedKey?: string | null;
 search?: string;
 sort?: {column: SortColumn; direction: 'asc' | 'desc' | 'clear'};
}
export type SortColumn = 'name' | 'key' | 'last_attempt' | 'last_success' | 'source_updated';
// Caller receipt metadata is untrusted and grants no mapping authority.
export interface SourceReceipt {source_key: string; reference: string}
export interface SourceInput {
 key: string;
 authorized: boolean;
 name?: string;
 version?: string;
 data_state?: unknown;
 // C-STATE has no complete-nonempty state. Healthy is an explicit adapter fact;
 // it never follows from a configured definition, count, timestamp or read attempt.
 health?: 'healthy';
 located?: boolean;
 readable?: boolean;
 mapped?: boolean;
 presented?: boolean;
 accepted?: boolean;
 receipt?: SourceReceipt;
 relevant?: boolean;
 last_attempt?: string;
 last_success?: string;
 source_updated?: string;
 whole_table_count?: number;
 view_count?: number;
 loaded_count?: number;
 excluded_count?: number;
 base_id?: string;
 table_id?: string;
 view_id?: string;
 cutoff_rule?: string;
 fields?: {name?: string; type?: string; field_id?: string; yx_mapping?: string; receipt?: SourceReceipt}[];
 read_authorized?: boolean;
 retry_handle?: unknown;
}
export interface Timestamp {value: string | null; label: string}
export interface SourceRow {
 key: string;
 name: string | null;
 lastErrorSummary: string | null;
 version: string | null;
 dataState: DataState | null;
 statusLabel: string;
 needsAttention: boolean;
 partial: boolean;
 stale: boolean;
 located: boolean | null;
 readable: boolean | null;
 mapped: false;
 presented: boolean | null;
 accepted: false;
 mappingLabel: string;
 receiptReference: null;
 last_attempt: Timestamp;
 last_success: Timestamp;
 source_updated: Timestamp;
 counts: {whole_table: number | null; view: number | null; loaded: number | null; excluded: number | null};
 identifiers: {base: string | null; table: string | null; view: string | null};
 cutoffRule: string | null;
 fields: {name: string | null; type: string | null; fieldId: string | null; yxMapping: null; mappingLabel: string}[];
 retry: {handle: unknown} | null;
}
export interface PageHealth {
 reported: boolean;
 states: DataStateName[];
 statusLabel: string;
 explanation: string;
}
export type SourceHealthView = {page: PageHealth; diagnostic: null} | {
 page: PageHealth;
 diagnostic: {
  rows: SourceRow[];
  summary: {last_success: Timestamp};
  selectedKey: string | null;
  drawer: SourceRow | null;
 };
};

const record = (value: unknown): Record<string, unknown> =>
 value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value : null;
const flag = (value: unknown): boolean | null => typeof value === 'boolean' ? value : null;
const count = (value: unknown): number | null => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
const compare = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;
const unknownTime = (): Timestamp => ({value: null, label: DATA_STATE_LABELS.unknown});
function timestamp(value: unknown): Timestamp {
 // Require an explicit timezone. Native Date.parse's local/time-only/date-only
 // coercions would manufacture an instant. Reject calendar rollover as well.
 if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return unknownTime();
 const [year, month, day] = value.slice(0, 10).split('-').map(Number);
 const maxDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
 const [hour, minute, second] = value.slice(11, 19).split(':').map(Number);
 if (month < 1 || month > 12 || day < 1 || day > maxDay || hour > 23 || minute > 59 || second > 59 || !Number.isFinite(Date.parse(value))) return unknownTime();
 return {value, label: value};
}
function permitsSourceState(value: unknown): boolean {
 if (value === undefined) return true;
 const raw = record(value);
 const parsed = parseDataState(value);
 const states: readonly DataStateName[] = parsed.states;
 if (raw.state === 'forbidden' || states.includes('forbidden')) return false;
 // The parser deliberately collapses malformed input to unknown. Only the
 // explicit valid unknown shape may expose metadata after that collapse.
 if (states.includes('unknown')) return Array.isArray(raw.states) && raw.states.length === 1 &&
  raw.states[0] === 'unknown' && (raw.count === undefined || raw.count === null);
 return true;
}
const guidance: Record<DataStateName, string> = {
 loading: '請等待目前的讀取完成。',
 complete_empty: '目前已完成讀取，尚無資料。',
 filtered_empty: '請調整或清除篩選條件。',
 unlocated: '請聯絡管理員確認既有來源與對應證據。',
 forbidden: '請聯絡管理員確認既有存取權限。',
 read_failed: '請聯絡管理員確認既有授權讀取的失敗原因。',
 partial: '目前只顯示部分資料，請確認既有來源的讀取狀態。',
 stale: '目前資料待更新，請確認最近成功讀取時間。',
 unknown: '目前無法確認資料狀態，請聯絡管理員。',
};

function sourceRow(raw: Record<string, unknown>, key: string): SourceRow {
 // Missing flags permit the explicit adapter fact; present malformed flags
 // contradict it and any supplied state, so fail closed to unknown.
 const contradictoryStage = ['located', 'readable', 'presented'].some(stage => Object.hasOwn(raw, stage) && typeof raw[stage] !== 'boolean');
 const state = contradictoryStage ? parseDataState({states: ['unknown']})
  : raw.data_state === undefined && raw.located === false ? parseDataState({states: ['unlocated']})
  : raw.data_state === undefined && raw.health === 'healthy' && raw.readable !== false && raw.presented !== false && raw.located !== false ? null : parseDataState(raw.data_state);
 const states: readonly DataStateName[] = state?.states ?? [];
 // VCC-117 evidence and verifier authority do not exist yet. No caller value
 // can grant mapped/accepted status or expose receipt references/YX bindings.
 const mapped = false;
 const accepted = false;
 // Empty-state scope counts are withheld until their consistency is verified.
 const hasKnownCounts = !states.some(s => ['unknown', 'loading', 'unlocated', 'read_failed'].includes(s)) &&
  !states.some(s => ['complete_empty', 'filtered_empty'].includes(s));
 return {
  key, name: text(raw.name), lastErrorSummary: text(raw.last_error_summary), version: text(raw.version), dataState: state === null ? null : parseDataState({states, count: null}),
  statusLabel: state === null ? '資料正常' : states.map(s => DATA_STATE_LABELS[s]).join('・'),
  needsAttention: states.some(s => ['read_failed', 'unlocated', 'partial', 'stale', 'unknown'].includes(s)),
  partial: states.includes('partial'), stale: states.includes('stale'),
  located: flag(raw.located), readable: flag(raw.readable), mapped,
  presented: flag(raw.presented), accepted,
  mappingLabel: '對應未驗證',
  receiptReference: null,
  last_attempt: timestamp(raw.last_attempt), last_success: timestamp(raw.last_success), source_updated: timestamp(raw.source_updated),
  counts: {whole_table: hasKnownCounts ? count(raw.whole_table_count) : null, view: hasKnownCounts ? count(raw.view_count) : null,
   loaded: hasKnownCounts ? count(raw.loaded_count) : null, excluded: hasKnownCounts ? count(raw.excluded_count) : null},
  identifiers: {base: text(raw.base_id), table: text(raw.table_id), view: text(raw.view_id)},
  cutoffRule: text(raw.cutoff_rule),
  fields: Array.isArray(raw.fields) ? Array.from(raw.fields, value => {
   const field = record(value);
   const mapping = null;
   return {name: text(field.name), type: text(field.type), fieldId: text(field.field_id), yxMapping: mapping,
    mappingLabel: '對應未驗證'};
  }) : [],
  // An opaque handle is returned verbatim. The adapter must execute that same
  // authorized read; this module constructs no URL, scope or transport action.
  retry: raw.read_authorized === true && raw.retry_handle !== undefined && raw.retry_handle !== null ? {handle: raw.retry_handle} : null,
 };
}

export function buildSourceHealthView(input: unknown, options: SourceHealthOptions): SourceHealthView {
 const raw = record(input);
 const pageState = parseDataState(raw.page_state);
 const page: PageHealth = {reported: raw.page_state != null, states: [...pageState.states], statusLabel: pageState.states.map(s => DATA_STATE_LABELS[s]).join('・'),
  explanation: pageState.states.map(s => guidance[s]).join(' ')};
 if (options.diagnosticCapability !== true) return {page, diagnostic: null};
 const candidates = Array.isArray(raw.sources) ? Array.from(raw.sources, record) : [];
 // Drop forbidden or malformed explicit states BEFORE metadata projection,
 // selection, search or summaries. Missing state still supports adapter facts.
 const permitted = candidates.filter(source => source.authorized === true &&
  permitsSourceState(source.data_state));
 const keyed = permitted.filter(source => text(source.key) !== null);
 // Ambiguous duplicate keys have no stable selection/receipt identity; omit all
 // copies rather than choosing a potentially different permission scope.
 const frequencies = new Map<string, number>();
 for (const source of keyed) frequencies.set(source.key as string, (frequencies.get(source.key as string) ?? 0) + 1);
 const unique = keyed.filter(source => frequencies.get(source.key as string) === 1);
 const allRows = unique.map(source => sourceRow(source, source.key as string));
 const relevant = allRows.filter((_, index) => unique[index].relevant !== false);
 let oldest = unknownTime();
 const relevantInputs = permitted.filter(source => source.relevant !== false);
 if (relevant.length && relevant.length === relevantInputs.length && relevant.every(row => row.last_success.value !== null)) {
  oldest = relevant.reduce((a, b) => Date.parse(a.last_success.value!) <= Date.parse(b.last_success.value!) ? a : b).last_success;
 }
 const query = typeof options.search === 'string' ? options.search.trim().toLowerCase() : '';
 const rows = allRows.filter(row => !query || [row.key, row.name, row.version].some(value => value?.toLowerCase().includes(query)));
 const sort = options.sort;
 rows.sort((a, b) => {
  if (a.needsAttention !== b.needsAttention) return a.needsAttention ? -1 : 1;
  if (sort && sort.direction !== 'clear') {
   const column = sort.column;
   let result = 0;
   if (column === 'name' || column === 'key') result = compare(a[column] ?? '', b[column] ?? '');
   else if (column === 'last_attempt' || column === 'last_success' || column === 'source_updated') {
    const av = a[column].value, bv = b[column].value;
    // Unknown stays last in either direction; no fallback to another timestamp.
    if (av === null || bv === null) {if (av !== bv) return av === null ? 1 : -1;}
    else result = Date.parse(av) - Date.parse(bv);
   }
   if (result) return sort.direction === 'desc' ? -result : result;
  }
  return compare(a.key, b.key);
 });
 const drawer = allRows.find(row => row.key === options.selectedKey) ?? null;
 return {page, diagnostic: {rows, summary: {last_success: oldest}, selectedKey: drawer?.key ?? null, drawer}};
}
