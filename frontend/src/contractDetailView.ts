// Contract Detail view-model (VCC-131). Pure and framework-free: no React, fetch or routing; unwired.
// Input is the JSON body of backend/contract_detail.py build_contract_detail (reviewed @ 07443f4c in worktree
// p2-131b). The body is untrusted: it is validated as a whole (exact keys, shapes, cross-section identity
// consistency) and any violation fails closed to an unknown page with a static reason. Nothing is partially
// trusted. Unknown is an em dash plus a reason, never 0. Amounts are always withheld (gate G-AMT): this module
// never reads, derives, sums or compares an amount value. There are no write actions; links are read-only
// navigation targets for P2-INT.
import {describeDataState, parseDataState} from './dataState.ts';
import type {DataState, DataStateName} from './dataState.ts';

// ---- route context (mirrors P2-NAV frontend/src/drilldownContext.ts @ a529080; not imported) ----------------
// P2-INT passes {sort, selected, filters} from the decoded P2Context for route 'contract'.
// FILTER_KEYS.contract is [] there, so filters are accepted for shape parity and always ignored.
export type SortSpec = {key: string; dir: 'asc' | 'desc'} | null;
export interface ContractDetailOptions {
 sort?: SortSpec;
 selected?: string | null;
 filters?: Readonly<Record<string, string>>;
}
// Navigation targets use P2Route names from drilldownContext: 'confirmation' | 'contract' | 'workitem'.
export type NavRoute = 'confirmation' | 'contract' | 'workitem';
export interface NavTarget {route: NavRoute; key: string}
// Only the category column carries data today; every other child column is unknown for every row.
export const SORTABLE_COLUMNS = ['category'] as const;

export const CONTRACT_LABELS = {
 unknownDash: '—',
 withheld: '未核准顯示',
 withheldReason: 'G-AMT：合約金額尚未核准顯示',
 unmapped: '對應未驗證',
 breadcrumbConfirmation: '確認單',
 breadcrumbContract: '合約明細',
 parentUnresolved: '上層確認單未解析（不自動指派）',
 parentUnlocatedRecord: '無法定位的確認單紀錄',
 siblingUnlocatedRecord: '無法定位的合約明細紀錄',
 sourceVersion: '來源版本',
 versionUnknown: '版本未提供',
 observation: '觀測快照（非正式修訂）',
 formalRevisions: '正式修訂紀錄',
 effectiveVersion: '生效版本',
 sourceUpdated: '來源更新時間',
 missingValue: '來源未提供此欄位值',
 retained: '來源紀錄目前缺失，顯示的是保留快照；快照時間未提供',
 malformed: '回應格式不符，已視為狀態未知',
 order: '排序：依穩定來源識別碼；原始來源順序尚未定位',
 orderSorted: '排序：依所選欄位，相同者依穩定來源識別碼；原始來源順序尚未定位',
 selectedCurrent: '目前選取',
 columns: {name: '工項名稱', category: '類別', quantity: '數量', unit: '單位', state: '狀態', person: '負責人', deliverables: '交付物數量'},
 pageUnlocated: '找不到此合約明細',
} as const;

const UNKNOWN_REASONS: Record<string, string> = {
 'quantity field unlocated': '數量欄位尚未定位',
 'unit field unlocated': '單位欄位尚未定位',
 'formal revision reason unlocated': '正式修訂原因尚未定位',
 'work-item name unlocated': '工項名稱欄位尚未定位',
 'work-item state unlocated': '工項狀態欄位尚未定位',
 'responsible person unlocated': '負責人欄位尚未定位',
 'deliverable population unlocated': '交付物母體尚未定位',
 'effective-version rule unlocated': '生效版本規則尚未定位',
};
const WARNING_LABELS: Record<string, string> = {
 receipt_missing: '對應未驗證（尚無對應收據）',
 separate_contract_header_unlocated: '獨立的合約表頭尚未定位',
 quantity_unit_unlocated: '數量與單位欄位尚未定位',
 formal_revision_semantics_unlocated: '正式修訂語意尚未定位',
 original_source_order_unlocated: '原始來源順序尚未定位',
 parent_unresolved: '上層確認單未解析',
 retained_source_missing: '來源紀錄目前缺失（保留快照）',
};
const UNKNOWN_WARNING = '未列於已知清單的警示';

// ---- output types ------------------------------------------------------------------------------------------
export type Cell =
 | {kind: 'text'; text: string}
 | {kind: 'unknown'; text: '—'; reason: string}
 | {kind: 'withheld'; text: '未核准顯示'; reason: string};
export interface StateLabel {states: DataStateName[]; label: string}
// Full native identity: for the drawer only. Rows carry just `navKey`, which is never rendered as text.
export interface IdentityView {sourceKey: string; base: string; table: string; view: string; recordId: string; version: string | null}
export interface WarningView {code: string; label: string}
export interface LineBlock {
 state: StateLabel;
 lineNumber: Cell;
 name: Cell;
 quantity: Cell;
 unit: Cell;
 originalAmount: Cell;
 currentRevisedAmount: Cell;
 revisionReason: Cell;
 versionLabel: string;
}
export interface DirectoryEntry {
 navKey: string | null;
 nav: NavTarget | null;
 selected: boolean;
 lineNumber: Cell;
 name: Cell;
 unresolvedLabel: string | null;
}
export interface Crumb {kind: 'confirmation' | 'unresolved' | 'contract'; label: string; nav: NavTarget | null}
export interface WorkItemRow {
 navKey: string;
 nav: NavTarget;
 name: Cell;
 category: Cell;
 quantity: Cell;
 unit: Cell;
 state: Cell;
 person: Cell;
 deliverables: Cell;
}
export interface ObservationView {label: string; versionLabel: string; line: LineBlock; sourceFields: {field: string; value: string}[]}
export interface DrawerView {
 kind: 'contract_line' | 'work_item';
 identity: IdentityView;
 sourceFields: {field: string; value: string}[];
 relationship: StateLabel | null;
 mapping: StateLabel | null;
 edgeVerification: string;
 amountNote: string;
 warnings: WarningView[];
}
export interface ContractDetailView {
 kind: 'ready' | 'state';
 page: StateLabel & {needsAttention: boolean; note: string | null; reason: string | null};
 breadcrumb: Crumb[];
 header: null | {title: Cell; lineNumber: Cell; versionLabel: string; sourceLabel: string; sourceUpdated: Cell; edgeLabel: string};
 directory: null | {state: StateLabel; entries: DirectoryEntry[]; note: string | null};
 main: LineBlock | null;
 workItems: null | {
  state: StateLabel;
  columns: string[];
  rows: WorkItemRow[];
  orderDisclosure: string;
  edgeLabel: string;
  emptyMessage: string | null;
  sort: SortSpec;
 };
 versionHistory: null | {
  state: StateLabel;
  currentVersionLabel: string;
  effectiveVersion: Cell;
  observations: ObservationView[];
  formalRevisions: StateLabel;
 };
 summary: null | {parents: Crumb[]; relationship: StateLabel; warnings: WarningView[]};
 // Selection-only: null unless `selected` names this line or one of its listed work items.
 drawer: DrawerView | null;
 // Read-only navigation only. No complete / approve / SOP write action exists in this view.
 actions: NavTarget[];
}

// ---- strict validation helpers -----------------------------------------------------------------------------
class Malformed extends Error {}
const bad = (path: string): never => { throw new Malformed(path); };
const isRec = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const rec = (v: unknown, keys: readonly string[], path: string): Record<string, unknown> => {
 if (!isRec(v)) return bad(path);
 const own = Object.keys(v);
 if (own.length !== keys.length || !keys.every(key => Object.hasOwn(v, key))) return bad(path);
 return v;
};
const arr = (v: unknown, path: string): unknown[] => Array.isArray(v) ? Array.from(v) : bad(path);
const MAX_TEXT = 500;
const CTRL = /[\u0000-\u001f\u007f]/;
const textOrNull = (v: unknown, path: string): string | null => {
 if (v === null) return null;
 if (typeof v !== 'string' || !v || v.length > MAX_TEXT || CTRL.test(v)) return bad(path);
 return v;
};
const component = (v: unknown, path: string): string => {
 if (typeof v !== 'string' || !v || v !== v.trim() || v.includes('/') || v.length > MAX_TEXT) return bad(path);
 return v;
};

// A state is trusted only if it parses to exactly what was sent: C-STATE collapses malformed input to unknown,
// so an unknown result is accepted only when the body literally said {states:['unknown'], count:null}.
function strictState(v: unknown, path: string): DataState {
 if (!isRec(v)) return bad(path);
 if (!Object.keys(v).every(key => key === 'states' || key === 'count' || key === 'name')) return bad(path);
 const parsed = parseDataState(v);
 const sent = Array.isArray(v.states) ? v.states : [];
 if (names(parsed).includes('unknown') && !(sent.length === 1 && sent[0] === 'unknown' && (v.count === undefined || v.count === null))) return bad(path);
 return parsed;
}
const names = (state: DataState): readonly DataStateName[] => state.states;
const label = (state: DataState): StateLabel => ({states: [...state.states], label: describeDataState(state)});
const isPartialStale = (state: DataState) => state.states.every(name => name === 'partial' || name === 'stale');
const sameState = (a: DataState, b: DataState) => JSON.stringify([a.states, 'count' in a ? a.count : null]) === JSON.stringify([b.states, 'count' in b ? b.count : null]);

function unknownBody(v: unknown, path: string): string {
 const o = rec(v, ['state', 'reason'], path);
 if (o.state !== 'unknown' || typeof o.reason !== 'string' || !o.reason || o.reason.length > 200 || CTRL.test(o.reason)) return bad(path);
 return UNKNOWN_REASONS[o.reason] ?? o.reason;
}
const unknownCell = (reason: string): Cell => ({kind: 'unknown', text: '—', reason});
const textCell = (value: string | null): Cell => value === null ? unknownCell(CONTRACT_LABELS.missingValue) : {kind: 'text', text: value};
// Only the withheld shape is accepted: any extra key (e.g. a value) or other state is malformed.
function withheldBody(v: unknown, path: string): Cell {
 const o = rec(v, ['state', 'reason'], path);
 if (o.state !== 'withheld' || typeof o.reason !== 'string' || !o.reason.startsWith('G-AMT')) return bad(path);
 return {kind: 'withheld', text: CONTRACT_LABELS.withheld, reason: CONTRACT_LABELS.withheldReason};
}

interface Identity {view: IdentityView; versionKey: string}
function identityBody(v: unknown, path: string, nullable: boolean): Identity | null {
 if (v === null) return nullable ? null : bad(path);
 const o = rec(v, ['source_key', 'base', 'table', 'view', 'record_id', 'version', 'version_key'], path);
 const base = component(o.base, path), table = component(o.table, path), recordId = component(o.record_id, path);
 if (o.source_key !== `${base}/${table}/${recordId}` || typeof o.view !== 'string') return bad(path);
 const version = o.version;
 const okVersion = version === null || (typeof version === 'number' && Number.isSafeInteger(version)) ||
  (typeof version === 'string' && version !== '' && version === version.trim() && version.length <= MAX_TEXT);
 if (!okVersion) return bad(path);
 const key = arr(o.version_key, path);
 if (key.length !== 4 || key[0] !== base || key[1] !== table || key[2] !== recordId || key[3] !== version) return bad(path);
 return {
  view: {sourceKey: o.source_key, base, table, view: o.view, recordId, version: version === null ? null : String(version)},
  versionKey: JSON.stringify(key),
 };
}
const versionLabel = (id: Identity): string =>
 id.view.version === null ? CONTRACT_LABELS.versionUnknown : `${CONTRACT_LABELS.sourceVersion} ${id.view.version}`;

// Amount-like native fields are dropped from the drawer even if a body carries them; the backend allowlist
// already excludes them, this is the second guard so no amount value can render from an altered body.
const AMOUNT_KEY = /金額|價|費|amount|price|cost|fee|total|sum/i;
function sourceFields(v: unknown, path: string): {field: string; value: string}[] {
 if (!isRec(v)) return bad(path);
 const out: {field: string; value: string}[] = [];
 for (const [field, value] of Object.entries(v)) {
  if (!field || field.length > MAX_TEXT || CTRL.test(field)) return bad(path);
  const t = typeof value;
  if (!(t === 'string' || t === 'boolean' || (t === 'number' && Number.isFinite(value as number)))) return bad(path);
  if (typeof value === 'string' && (value.length > MAX_TEXT || CTRL.test(value))) return bad(path);
  if (AMOUNT_KEY.test(field)) continue;
  out.push({field, value: String(value)});
 }
 return out;
}

const LINE_KEYS = ['section_state', 'identity', 'line_number', 'name', 'quantity', 'unit', 'original_amount', 'current_revised_amount', 'revision_reason'] as const;
function lineBody(v: unknown, path: string): {block: LineBlock; identity: Identity} {
 const o = rec(v, LINE_KEYS, path);
 const state = strictState(o.section_state, `${path}.section_state`);
 if (!isPartialStale(state)) bad(`${path}.section_state`);
 const identity = identityBody(o.identity, `${path}.identity`, false) as Identity;
 return {
  identity,
  block: {
   state: label(state),
   lineNumber: textCell(textOrNull(o.line_number, `${path}.line_number`)),
   name: textCell(textOrNull(o.name, `${path}.name`)),
   quantity: unknownCell(unknownBody(o.quantity, `${path}.quantity`)),
   unit: unknownCell(unknownBody(o.unit, `${path}.unit`)),
   originalAmount: withheldBody(o.original_amount, `${path}.original_amount`),
   currentRevisedAmount: withheldBody(o.current_revised_amount, `${path}.current_revised_amount`),
   revisionReason: unknownCell(unknownBody(o.revision_reason, `${path}.revision_reason`)),
   versionLabel: versionLabel(identity),
  },
 };
}

const compareKey = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;

function failed(reason: string): ContractDetailView {
 const unknown = parseDataState({states: ['unknown']});
 return stateView(unknown, CONTRACT_LABELS.malformed, reason);
}
function stateView(state: DataState, note: string | null, reason: string | null = null): ContractDetailView {
 return {
  kind: 'state',
  page: {...label(state), needsAttention: true, note, reason},
  breadcrumb: [], header: null, directory: null, main: null, workItems: null, versionHistory: null,
  summary: null, drawer: null, actions: [],
 };
}

const READY_KEYS = ['page_state', 'header', 'siblings', 'main', 'work_items', 'version_history', 'details'] as const;
const STATE_ONLY: ReadonlySet<DataStateName> = new Set(['loading', 'unlocated', 'read_failed', 'unknown']);

export function buildContractDetailView(body: unknown, options: ContractDetailOptions = {}): ContractDetailView {
 try {
  return build(body, options);
 } catch (error) {
  // Static path only; the offending value is never echoed.
  return failed(error instanceof Malformed ? `malformed:${error.message}` : 'malformed:unexpected');
 }
}

function build(body: unknown, options: ContractDetailOptions): ContractDetailView {
 if (!isRec(body) || !Object.hasOwn(body, 'page_state')) return bad('body');
 const pageState = strictState(body.page_state, 'page_state');
 // Forbidden wins and exposes nothing else (no name, count or sections).
 if (names(pageState).includes('forbidden')) return stateView({states: ['forbidden']}, null);
 if (STATE_ONLY.has(pageState.states[0])) {
  if (Object.keys(body).length !== 1) return bad('body');
  if (pageState.states[0] === 'unlocated') return stateView(pageState, CONTRACT_LABELS.pageUnlocated);
  return stateView(pageState, null);
 }
 if (!isPartialStale(pageState)) return bad('page_state');
 const o = rec(body, READY_KEYS, 'body');

 // header
 const h = rec(o.header, ['identity', 'line_number', 'name', 'section_state', 'source', 'parent_confirmations', 'parent_state', 'edge_verification'], 'header');
 const headerState = strictState(h.section_state, 'header.section_state');
 if (!isPartialStale(headerState)) bad('header.section_state');
 if (h.edge_verification !== 'receipt_missing') bad('header.edge_verification');
 const self = identityBody(h.source, 'header.source', false) as Identity;
 const dir = identityBody(h.identity, 'header.identity', false) as Identity;
 if (dir.versionKey !== self.versionKey) bad('header.identity');
 const parentState = strictState(h.parent_state, 'header.parent_state');
 const parents: Crumb[] = [];
 const parentRows = arr(h.parent_confirmations, 'header.parent_confirmations');
 const seenParents = new Set<string>();
 for (const [i, raw] of parentRows.entries()) {
  const p = rec(raw, ['identity', 'reference'], `header.parent_confirmations[${i}]`);
  const id = identityBody(p.identity, `header.parent_confirmations[${i}].identity`, true);
  const ref = textOrNull(p.reference, `header.parent_confirmations[${i}].reference`);
  if (id) { if (seenParents.has(id.view.sourceKey)) bad('header.parent_confirmations'); seenParents.add(id.view.sourceKey); }
  parents.push(id
   ? {kind: 'confirmation', label: ref ?? CONTRACT_LABELS.missingValue, nav: {route: 'confirmation', key: id.view.sourceKey}}
   : {kind: 'unresolved', label: CONTRACT_LABELS.parentUnlocatedRecord, nav: null});
 }
 if (parents.length ? !isPartialStale(parentState) : !names(parentState).includes('unlocated')) bad('header.parent_state');
 const lineNumber = textOrNull(h.line_number, 'header.line_number');
 const name = textOrNull(h.name, 'header.name');

 // main
 const main = lineBody(o.main, 'main');
 if (main.identity.versionKey !== self.versionKey) bad('main.identity');
 const mainKey = self.view.sourceKey;
 if (main.block.lineNumber.text !== textCell(lineNumber).text || main.block.name.text !== textCell(name).text) bad('main.header_mismatch');

 // siblings: equal display names stay separate entries; identity is source key only.
 const sib = rec(o.siblings, ['state', 'rows'], 'siblings');
 const sibState = strictState(sib.state, 'siblings.state');
 const sibRows = arr(sib.rows, 'siblings.rows');
 if (sibRows.length && !isPartialStale(sibState)) bad('siblings.state');
 const entries: DirectoryEntry[] = [{
  navKey: mainKey, nav: {route: 'contract', key: mainKey}, selected: true,
  lineNumber: textCell(lineNumber), name: textCell(name), unresolvedLabel: null,
 }];
 const seenSiblings = new Set<string>([mainKey]);
 for (const [i, raw] of sibRows.entries()) {
  const s = rec(raw, ['identity', 'line_number', 'name'], `siblings.rows[${i}]`);
  const id = identityBody(s.identity, `siblings.rows[${i}].identity`, true);
  if (id) { if (seenSiblings.has(id.view.sourceKey)) bad('siblings.rows'); seenSiblings.add(id.view.sourceKey); }
  entries.push({
   navKey: id ? id.view.sourceKey : null,
   nav: id ? {route: 'contract', key: id.view.sourceKey} : null,
   selected: false,
   lineNumber: textCell(textOrNull(s.line_number, `siblings.rows[${i}].line_number`)),
   name: textCell(textOrNull(s.name, `siblings.rows[${i}].name`)),
   unresolvedLabel: id ? null : CONTRACT_LABELS.siblingUnlocatedRecord,
  });
 }
 // Directory in stable source-key order (matches the backend); unlocated entries keep body order, last.
 const located = entries.filter(e => e.navKey !== null).sort((a, b) => compareKey(a.navKey as string, b.navKey as string));
 const directory = {
  state: label(sibState),
  entries: [...located, ...entries.filter(e => e.navKey === null)],
  // Never imply "no siblings": with no rows the other lines' state is whatever the body said.
  note: sibRows.length ? null : `同確認單下其他合約明細：${describeDataState(sibState)}`,
 };

 // work items
 const wi = rec(o.work_items, ['state', 'rows', 'order', 'edge_verification'], 'work_items');
 const wiState = strictState(wi.state, 'work_items.state');
 if (wi.edge_verification !== 'receipt_missing') bad('work_items.edge_verification');
 if (typeof wi.order !== 'string' || !wi.order.includes('original_source_order_unlocated')) bad('work_items.order');
 const wiRaw = arr(wi.rows, 'work_items.rows');
 if (wiRaw.length && !isPartialStale(wiState)) bad('work_items.state');
 // A known child count must equal the rows actually present, including zero rows.
 if ('count' in wiState && wiState.count !== null && wiState.count !== wiRaw.length) bad('work_items.state');
 interface Child {row: WorkItemRow; categoryRaw: string | null; child: Identity}
 const children: Child[] = [];
 const seenChildren = new Set<string>();
 for (const [i, raw] of wiRaw.entries()) {
  const p = `work_items.rows[${i}]`;
  const c = rec(raw, ['identity', 'name', 'category', 'quantity', 'unit', 'state', 'responsible_person', 'deliverable_count'], p);
  const id = identityBody(c.identity, `${p}.identity`, false) as Identity;
  if (seenChildren.has(id.view.sourceKey)) bad('work_items.rows');
  seenChildren.add(id.view.sourceKey);
  const category = textOrNull(c.category, `${p}.category`);
  children.push({
   child: id, categoryRaw: category,
   row: {
    navKey: id.view.sourceKey, nav: {route: 'workitem', key: id.view.sourceKey},
    name: unknownCell(unknownBody(c.name, `${p}.name`)),
    category: textCell(category),
    quantity: unknownCell(unknownBody(c.quantity, `${p}.quantity`)),
    unit: unknownCell(unknownBody(c.unit, `${p}.unit`)),
    state: unknownCell(unknownBody(c.state, `${p}.state`)),
    person: unknownCell(unknownBody(c.responsible_person, `${p}.responsible_person`)),
    deliverables: unknownCell(unknownBody(c.deliverable_count, `${p}.deliverable_count`)),
   },
  });
 }
 const sort = options.sort && isRec(options.sort) && (SORTABLE_COLUMNS as readonly string[]).includes(options.sort.key) &&
  (options.sort.dir === 'asc' || options.sort.dir === 'desc') ? {key: options.sort.key, dir: options.sort.dir} : null;
 const factor = sort?.dir === 'desc' ? -1 : 1;
 children.sort((a, b) => {
  if (sort) {
   // Missing categories sort last in either direction; ties fall back to the stable source key.
   if ((a.categoryRaw === null) !== (b.categoryRaw === null)) return a.categoryRaw === null ? 1 : -1;
   if (a.categoryRaw !== null && b.categoryRaw !== null && a.categoryRaw !== b.categoryRaw) return factor * compareKey(a.categoryRaw, b.categoryRaw);
  }
  return compareKey(a.row.navKey, b.row.navKey);
 });
 const workItems = {
  state: label(wiState),
  columns: Object.values(CONTRACT_LABELS.columns),
  rows: children.map(c => c.row),
  orderDisclosure: sort ? CONTRACT_LABELS.orderSorted : CONTRACT_LABELS.order,
  edgeLabel: CONTRACT_LABELS.unmapped,
  // An empty-message is only for a complete authorized empty set; unknown and the rest show their state label.
  emptyMessage: children.length ? null : describeDataState(wiState),
  sort,
 };

 // version history
 const vh = rec(o.version_history, ['state', 'current', 'effective_business_version', 'historical_observations', 'formal_revisions'], 'version_history');
 const vhState = strictState(vh.state, 'version_history.state');
 const current = identityBody(vh.current, 'version_history.current', false) as Identity;
 if (current.versionKey !== self.versionKey) bad('version_history.current');
 const formal = rec(vh.formal_revisions, ['state'], 'version_history.formal_revisions');
 const formalState = strictState(formal.state, 'version_history.formal_revisions.state');
 if (formalState.states.length !== 1 || formalState.states[0] !== 'unlocated') bad('version_history.formal_revisions');
 const obsRaw = arr(vh.historical_observations, 'version_history.historical_observations');
 if (obsRaw.length && !isPartialStale(vhState)) bad('version_history.state');
 const observations: ObservationView[] = obsRaw.map((raw, i) => {
  const p = `version_history.historical_observations[${i}]`;
  const ob = rec(raw, ['kind', 'line', 'source_fields'], p);
  if (ob.kind !== 'observed_source_snapshot') bad(`${p}.kind`);
  const line = lineBody(ob.line, `${p}.line`);
  // A snapshot of any other record must not be shown as this line's history.
  if (line.identity.view.sourceKey !== mainKey) bad(`${p}.line.identity`);
  return {label: CONTRACT_LABELS.observation, versionLabel: line.block.versionLabel, line: line.block, sourceFields: sourceFields(ob.source_fields, `${p}.source_fields`)};
 });
 const versionHistory = {
  state: label(vhState),
  currentVersionLabel: versionLabel(current),
  effectiveVersion: unknownCell(unknownBody(vh.effective_business_version, 'version_history.effective_business_version')),
  observations,
  formalRevisions: {...label(formalState), label: `${CONTRACT_LABELS.formalRevisions}：${describeDataState(formalState)}`},
 };

 // details / warnings
 const d = rec(o.details, ['section_state', 'identity', 'source_fields', 'relationship_count', 'mapping_state', 'warnings'], 'details');
 const dState = strictState(d.section_state, 'details.section_state');
 if (!isPartialStale(dState)) bad('details.section_state');
 const dIdentity = identityBody(d.identity, 'details.identity', false) as Identity;
 if (dIdentity.versionKey !== self.versionKey) bad('details.identity');
 const relationship = strictState(d.relationship_count, 'details.relationship_count');
 if (!sameState(relationship, wiState)) bad('details.relationship_count');
 const mapping = strictState(d.mapping_state, 'details.mapping_state');
 // No receipt authority: a mapping can only be unlocated here, whatever the body says.
 if (mapping.states.length !== 1 || mapping.states[0] !== 'unlocated') bad('details.mapping_state');
 const warnings: WarningView[] = [];
 const seenWarnings = new Set<string>();
 for (const code of arr(d.warnings, 'details.warnings')) {
  if (typeof code !== 'string' || !/^[a-z][a-z_]{0,63}$/.test(code) || seenWarnings.has(code)) bad('details.warnings');
  seenWarnings.add(code as string);
  warnings.push({code: code as string, label: WARNING_LABELS[code as string] ?? UNKNOWN_WARNING});
 }
 // Derived from the body's own structure, so they hold even if the warnings list omitted them.
 const derive = (code: string) => { if (!seenWarnings.has(code)) { seenWarnings.add(code); warnings.push({code, label: WARNING_LABELS[code]}); } };
 derive('receipt_missing');
 if (!parents.length) derive('parent_unresolved');
 const stale = names(pageState).includes('stale');
 if (stale) derive('retained_source_missing');
 const fields = sourceFields(d.source_fields, 'details.source_fields');

 // breadcrumb: Confirmation(s) -> Contract Line. Missing parent is explicit and never auto-assigned.
 const breadcrumb: Crumb[] = [
  ...(parents.length ? parents : [{kind: 'unresolved' as const, label: CONTRACT_LABELS.parentUnresolved, nav: null}]),
  {kind: 'contract', label: lineNumber !== null && name !== null ? `${lineNumber} ${name}` : name ?? lineNumber ?? CONTRACT_LABELS.missingValue, nav: null},
 ];

 // selection-only drawer
 let drawer: DrawerView | null = null;
 const selected = typeof options.selected === 'string' && options.selected ? options.selected : null;
 if (selected === mainKey) {
  drawer = {
   kind: 'contract_line', identity: dIdentity.view, sourceFields: fields, relationship: label(relationship), mapping: label(mapping),
   edgeVerification: CONTRACT_LABELS.unmapped, amountNote: CONTRACT_LABELS.withheldReason, warnings,
  };
 } else if (selected !== null) {
  const hit = children.find(c => c.row.navKey === selected);
  if (hit) {
   drawer = {
    kind: 'work_item', identity: hit.child.view, sourceFields: [], relationship: null, mapping: null,
    edgeVerification: CONTRACT_LABELS.unmapped, amountNote: CONTRACT_LABELS.withheldReason,
    warnings: [{code: 'receipt_missing', label: WARNING_LABELS.receipt_missing}],
   };
  }
 }

 const page = {
  ...label(pageState), needsAttention: true,
  note: stale ? CONTRACT_LABELS.retained : null, reason: null,
 };
 const actions: NavTarget[] = [
  ...parents.flatMap(p => p.nav ? [p.nav] : []),
  ...directory.entries.flatMap(e => e.nav && !e.selected ? [e.nav] : []),
  ...workItems.rows.map(r => r.nav),
 ];
 return {
  kind: 'ready', page, breadcrumb,
  header: {
   title: textCell(name), lineNumber: textCell(lineNumber), versionLabel: versionLabel(self),
   sourceLabel: `原生合約明細・${versionLabel(self)}`,
   // Fetch time is never source-updated time; the body carries no source timestamp.
   sourceUpdated: unknownCell('來源更新時間未提供'),
   edgeLabel: CONTRACT_LABELS.unmapped,
  },
  directory,
  main: main.block,
  workItems, versionHistory,
  summary: {parents: breadcrumb.filter(c => c.kind !== 'contract'), relationship: label(relationship), warnings},
  drawer, actions,
 };
}
