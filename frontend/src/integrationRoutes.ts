// P1-INT glue (pure, framework-free): hash routing, return context and fetched-payload adapters for the
// #work and #sources pages. No fetch here; App/page components own transport. Unknown stays unknown.
import {decodeReturnContext, encodeReturnContext} from './myWorkView.ts';
import type {MyWorkFilters, MyWorkInput} from './myWorkView.ts';
import {back as navBack, decodeContext, defaultContext, drill, encodeContext, P2_ROUTES} from './drilldownContext.ts';
import type {FilterSet, P2Context, P2Route, Result, SortSpec} from './drilldownContext.ts';

export interface HashRoute {view: string; tab?: string; ctx?: string; [key: string]: string | undefined}

// The legacy MyWork (scope 'all' lives there too) and Sources (sync button, record browser) stay reachable.
export const isLegacyTab = (route: {tab?: string}, view: 'work' | 'sources'): boolean =>
 route.tab === 'legacy' || (view === 'work' && route.tab === 'all');

// Selection and filters live in the hash (ctx), so reload, navigation and Back restore them.
export const filtersFromRoute = (route: {ctx?: string}): MyWorkFilters => decodeReturnContext(route.ctx);
export const withFilters = <R extends {ctx?: string}>(route: R, filters: Partial<MyWorkFilters>): R => {
 const next = {...route};
 const encoded = encodeReturnContext(filters);
 // The default context carries no information; keep the canonical bare hash.
 if (encoded === encodeReturnContext({})) delete next.ctx; else next.ctx = encoded;
 return next;
};

// onNavigate receives backend routes such as '/#view=project&project=p1&tab=flow'. Same-origin hash only.
export function hashOfRoute(route: unknown): string | null {
 if (typeof route !== 'string' || !route.startsWith('/#') || /[\s\\]/.test(route) || route.length > 2048) return null;
 const hash = route.slice(2);
 return new URLSearchParams(hash).get('view') ? hash : null;
}

type Fetched = {status: 'loading'} | {status: 'ok'; body: unknown} | {status: 'error'; httpStatus?: number};
const record = (value: unknown): Record<string, unknown> | null =>
 value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
const failureState = (fetched: Fetched) => ({states: [fetched.status === 'error' && fetched.httpStatus === 403 ? 'forbidden' : 'read_failed']});

export function myWorkInput(fetched: Fetched, filters: MyWorkFilters): MyWorkInput {
 if (fetched.status === 'loading') return {filters};  // readState undefined renders loading
 if (fetched.status === 'error') return {filters, readState: failureState(fetched)};
 const body = record(fetched.body);
 if (!body) return {filters, readState: {states: ['unknown'], count: null}};
 // weeklyActivity stays absent: /api/my-work/activity is not built (126B2).
 return {filters, rows: body.rows, readState: body.readState, assignment: body.assignment as MyWorkInput['assignment'],
  canSeeAwaitingConfirmation: body.canSeeAwaitingConfirmation === true, asOf: body.as_of};
}

export function sourceHealthInput(fetched: Fetched): {page_state: unknown; sources: unknown} {
 if (fetched.status === 'loading') return {page_state: {states: ['loading'], count: null}, sources: []};
 if (fetched.status === 'error') return {page_state: failureState(fetched), sources: []};
 const body = record(fetched.body);
 // A missing page_state key is unknown; an explicit null is passed through and also renders unknown (no per-request complete-read evidence exists).
 if (!body || !('page_state' in body)) return {page_state: {states: ['unknown'], count: null}, sources: []};
 return {page_state: body.page_state, sources: body.sources};
}

// ---- P2-INT-F: hash routes for VCC-128..132 --------------------------------------------------------------------
// Pure helpers only (no fetch, no React). drilldownContext.ts owns every context/Back/breadcrumb rule; this file
// binds it to the backend vocabulary. drilldownContext imports hashOfRoute from here, so nothing below runs at import time.
export type P2View = P2Route;
export const isP2View = (view: unknown): view is P2Route => typeof view === 'string' && (P2_ROUTES as readonly string[]).includes(view);
// The three detail routes have no own left-navigation entry; they highlight the list they were opened from.
export const p2ActiveNav = (view: string): string => view === 'confirmation' || view === 'contract' || view === 'workitem' ? 'confirmations' : view;

export interface P2HashRoute {view: P2Route; ctx?: string}
/** A bare hash is the default context; a ctx that fails strict validation is reported and replaced by the default (never partially applied). */
export const p2ContextOfRoute = (route: {view: string; ctx?: string}): Result<P2Context> =>
 !isP2View(route.view) ? {ok: false, reason: 'bad_route', value: defaultContext('overview')}
  : route.ctx === undefined ? {ok: true, value: defaultContext(route.view)} : decodeContext(route.ctx, route.view);
/** Fetch gate (F2): a hash whose context fails validation is refused. The default context in the result is only for the refusal
 *  page's own reset action; nothing may be read or rendered from it. Only that reset (a navigation to the bare hash) may start a read. */
export type P2Gate = {ok: true; context: P2Context} | {ok: false; context: P2Context; reason: string};
export function p2Gate(route: {view: string; ctx?: string}): P2Gate {
 const parsed = p2ContextOfRoute(route);
 return parsed.ok ? {ok: true, context: parsed.value} : {ok: false, context: parsed.value, reason: parsed.reason};
}
/** Same query? Blank values count as absent, key order is irrelevant (F1: draft edits vs the committed query). */
export const sameFilters = (a: Readonly<Record<string, string>>, b: Readonly<Record<string, string>>): boolean => {
 const norm = (x: Readonly<Record<string, string>>) => JSON.stringify(Object.entries(x).filter(([, v]) => typeof v === 'string' && v.trim() !== '').sort(([p], [q]) => p < q ? -1 : p > q ? 1 : 0));
 return norm(a) === norm(b);
};
export function p2RouteOfContext(context: P2Context): P2HashRoute | null {
 const encoded = encodeContext(context);
 if (!encoded.ok) return null;
 // The default context carries no information; keep the canonical bare hash.
 return encoded.value === encodeContext(defaultContext(context.route)).value ? {view: context.route} : {view: context.route, ctx: encoded.value};
}

// ---- filter adapter: NAV vocabulary <-> backend keys (NAV-REV F2) ----------------------------------------------
// One table, both directions, no filter dropped: a key that has no backend equivalent is reported, never ignored.
// Multi-select sets (source_version, pm, admission_state) travel in NAV's single-string FilterSet value as a sorted,
// de-duplicated list joined by "," with "\\" and "," escaped, so decode(encode(set)) is the same set.
export const BACKEND_MULTI_KEYS = ['source_version', 'pm', 'admission_state'] as const;
const LIST_NAV_TO_BACKEND: Readonly<Record<string, string>> = {
 search: 'q', source_version: 'source_version', pm: 'pm', admission: 'admission_state', deadline_from: 'deadline_from', deadline_to: 'deadline_to',
};
const LIST_BACKEND_TO_NAV: Readonly<Record<string, string>> = Object.fromEntries(Object.entries(LIST_NAV_TO_BACKEND).map(([nav, backend]) => [backend, nav]));
// Overview keys are case filters (project fields), sent only as pm_id / execution_status.
const OVERVIEW_NAV_TO_BACKEND: Readonly<Record<string, string>> = {pm: 'pm_id', execution_state: 'execution_status'};
export const NAV_FILTERS_WITHOUT_BACKEND_KEY = ['execution_state', 'pending_decision', 'blocked', 'stage'] as const;
const CONTROL = /[\u0000-\u001f\u007f]/;

export function encodeSet(values: readonly unknown[]): string | null {
 if (!values.length) return null;
 const clean: string[] = [];
 for (const value of values) {
  if (typeof value !== 'string' || !value || value !== value.trim() || CONTROL.test(value)) return null;
  clean.push(value);
 }
 return [...new Set(clean)].sort().map(value => value.replace(/[\\,]/g, '\\$&')).join(',');
}
export function decodeSet(text: string): string[] {
 const out: string[] = [];
 let current = '';
 for (let i = 0; i < text.length; i++) {
  const ch = text[i];
  if (ch === '\\' && i + 1 < text.length && (text[i + 1] === ',' || text[i + 1] === '\\')) current += text[++i];
  else if (ch === ',') {out.push(current.trim()); current = '';}
  else current += ch;
 }
 out.push(current.trim());
 return [...new Set(out.filter(Boolean))].sort();
}
/** Canonical text for a typed multi-select value (what the UI commits); null when nothing usable was typed. */
export const normalizeSetText = (text: string): string | null => encodeSet(decodeSet(text));

export type QueryParams = readonly (readonly [string, string])[];
export type AdapterResult = {ok: true; params: QueryParams} | {ok: false; unsupported: string[]; invalid: string[]};
const isMulti = (backendKey: string) => (BACKEND_MULTI_KEYS as readonly string[]).includes(backendKey);

/** Confirmation List request (GET /api/confirmations). Order is fixed so equal queries give equal URLs. */
export function confirmationParams(query: {filters: FilterSet; sort?: SortSpec; cursor?: string | null; limit?: number}): AdapterResult {
 const unsupported: string[] = [], invalid: string[] = [];
 const byBackend = new Map<string, string[]>();
 for (const [key, value] of Object.entries(query.filters)) {
  const backend = LIST_NAV_TO_BACKEND[key];
  if (!backend) {unsupported.push(key); continue;}
  if (typeof value !== 'string' || !value.trim() || CONTROL.test(value)) {invalid.push(key); continue;}
  if (isMulti(backend)) {
   const set = decodeSet(value);
   if (!set.length) {invalid.push(key); continue;}
   byBackend.set(backend, set);
  } else byBackend.set(backend, [value]);
 }
 if (unsupported.length || invalid.length) return {ok: false, unsupported: unsupported.sort(), invalid: invalid.sort()};
 const params: [string, string][] = [];
 for (const backend of ['q', 'source_version', 'pm', 'admission_state', 'deadline_from', 'deadline_to']) for (const value of byBackend.get(backend) ?? []) params.push([backend, value]);
 if (query.sort) params.push(['sort', query.sort.key], ['direction', query.sort.dir]);
 if (query.cursor) params.push(['cursor', query.cursor]);
 params.push(['limit', String(query.limit ?? 50)]);
 return {ok: true, params};
}
/** Manager Overview request (GET /api/manager-overview). NAV pm/execution_state are case filters only. */
export function overviewParams(filters: FilterSet): AdapterResult {
 const unsupported: string[] = [], invalid: string[] = [];
 const params: [string, string][] = [];
 for (const [key, value] of Object.entries(filters).sort(([a], [b]) => a.localeCompare(b))) {
  const backend = OVERVIEW_NAV_TO_BACKEND[key];
  if (!backend) unsupported.push(key);
  else if (typeof value !== 'string' || !value.trim() || CONTROL.test(value)) invalid.push(key);
  else params.push([backend, value]);
 }
 return unsupported.length || invalid.length ? {ok: false, unsupported, invalid} : {ok: true, params: params.sort(([a], [b]) => a.localeCompare(b))};
}
/** The same filters in the backend vocabulary, for the echo comparison inside the overview view model. */
export const overviewBackendFilters = (filters: FilterSet): Record<string, string> =>
 Object.fromEntries(Object.entries(filters).filter(([key]) => OVERVIEW_NAV_TO_BACKEND[key]).map(([key, value]) => [OVERVIEW_NAV_TO_BACKEND[key], value]));
export const queryString = (params: QueryParams): string => {
 const query = new URLSearchParams();
 for (const [key, value] of params) query.append(key, value);
 const text = query.toString();
 return text ? `?${text}` : '';
};

export type BackToNav = {ok: true; filters: FilterSet} | {ok: false; unmapped: string[]};
/** Backend filter object (e.g. a KPI card drilldown) -> NAV confirmations filters. A key or value that cannot be represented is refused, never dropped. */
export function backendFiltersToNav(filters: unknown): BackToNav {
 if (filters === null || typeof filters !== 'object' || Array.isArray(filters)) return {ok: false, unmapped: ['filters']};
 const out: Record<string, string> = {};
 const unmapped: string[] = [];
 for (const [key, value] of Object.entries(filters as Record<string, unknown>)) {
  const nav = LIST_BACKEND_TO_NAV[key];
  if (!nav) {unmapped.push(key); continue;}
  if (isMulti(key)) {
   const encoded = Array.isArray(value) ? encodeSet(value) : typeof value === 'string' ? encodeSet([value]) : null;
   if (encoded === null) unmapped.push(key); else out[nav] = encoded;
  } else if (typeof value === 'string' && value && !CONTROL.test(value)) out[nav] = value;
  else unmapped.push(key);
 }
 return unmapped.length ? {ok: false, unmapped: unmapped.sort()} : {ok: true, filters: out};
}
/** NAV confirmations filters -> the backend object the same request would carry (round-trip counterpart of backendFiltersToNav). */
export function navFiltersToBackend(filters: FilterSet): {ok: true; filters: Record<string, string | string[]>} | {ok: false; unsupported: string[]} {
 const out: Record<string, string | string[]> = {};
 const unsupported: string[] = [];
 for (const [key, value] of Object.entries(filters)) {
  const backend = LIST_NAV_TO_BACKEND[key];
  if (!backend) unsupported.push(key); else out[backend] = isMulti(backend) ? decodeSet(value) : value;
 }
 return unsupported.length ? {ok: false, unsupported: unsupported.sort()} : {ok: true, filters: out};
}

// ---- server cursor history, bound to the identical query ---------------------------------------------------------
// Only cursors that were actually requested are stacked (null = page one). History belongs to one (filters, sort) query:
// any other query starts from nothing, so Prev can never replay a cursor minted for different filters or sorting.
export interface CursorHistory {filters: FilterSet; sort: SortSpec; current: string | null; stack: readonly (string | null)[]}
export type HistoryStore = Map<string, {current: string | null; stack: readonly (string | null)[]}>;
export const queryKey = (filters: FilterSet, sort: SortSpec): string =>
 JSON.stringify([Object.entries(filters).sort(([a], [b]) => a.localeCompare(b)), sort ? [sort.key, sort.dir] : null]);
export function boundHistory(store: HistoryStore, filters: FilterSet, sort: SortSpec, cursor: string | null): CursorHistory {
 const known = store.get(queryKey(filters, sort));
 return {filters: {...filters}, sort: sort ? {...sort} : null, current: cursor, stack: known && known.current === cursor ? [...known.stack] : []};
}
export function recordPage(store: HistoryStore, filters: FilterSet, sort: SortSpec, from: string | null, to: string | null): void {
 const here = boundHistory(store, filters, sort, from);
 const last = here.stack.length - 1;
 const stack = last >= 0 && here.stack[last] === to ? here.stack.slice(0, last) : [...here.stack, from];
 const key = queryKey(filters, sort);
 store.delete(key);
 store.set(key, {current: to, stack});
 if (store.size > 50) store.delete(store.keys().next().value!);
}

// ---- case identity (opaque, inside NAV's `selected`) ------------------------------------------------------------
// Case and Confirmation Detail is addressed by the existing stable project_id, optionally with a confirmation key.
export const caseSelection = (projectId: string, confirmationKey?: string | null): string =>
 `case:${encodeURIComponent(projectId)}${confirmationKey ? `?conf=${encodeURIComponent(confirmationKey)}` : ''}`;
export function parseCaseSelection(selected: unknown): {projectId: string; confirmationKey: string | null} | null {
 if (typeof selected !== 'string' || !selected.startsWith('case:')) return null;
 const [id, query, ...rest] = selected.slice(5).split('?');
 if (rest.length || !id || (query !== undefined && !query.startsWith('conf='))) return null;
 try {
  const projectId = decodeURIComponent(id), key = query === undefined ? null : decodeURIComponent(query.slice(5));
  return projectId && key !== '' ? {projectId, confirmationKey: key} : null;
 } catch {return null;}
}

// Case Detail row keys are `<kind>:<source key>` (confirmation:, contract:, work_item:); the detail endpoints take the bare
// `base/table/record` source key. Confirmation List row keys are `<source key>@<version tag>`. Anything else is not navigable.
const SOURCE_KEY = /^[^/\s]+\/[^/\s]+\/[^/\s]+$/;
const OTHER_KIND = /^(task|node|evidence|case|history):/;
export function sourceKeyOf(nativeKey: unknown): string | null {
 if (typeof nativeKey !== 'string') return null;
 const bare = nativeKey.replace(/^(confirmation|contract|work_item|workitem):/, '');
 return SOURCE_KEY.test(bare) && !OTHER_KIND.test(bare) ? bare : null;
}
export function confirmationKeyOfRow(rowKey: unknown): string | null {
 if (typeof rowKey !== 'string') return null;
 const at = rowKey.lastIndexOf('@');
 return at > 0 ? sourceKeyOf(rowKey.slice(0, at)) : null;
}

// ---- request URLs ----------------------------------------------------------------------------------------------
export type P2Request = {ok: true; url: string} | {ok: false; reason: 'unsupported_filter' | 'invalid_filter' | 'unlocated'; unsupported: string[]; invalid: string[]};
const failed = (result: Extract<AdapterResult, {ok: false}>): P2Request =>
 ({ok: false, reason: result.unsupported.length ? 'unsupported_filter' : 'invalid_filter', unsupported: result.unsupported, invalid: result.invalid});
export function p2Request(context: P2Context): P2Request {
 if (context.route === 'overview') {
  const result = overviewParams(context.filters);
  return result.ok ? {ok: true, url: `/api/manager-overview${queryString(result.params)}`} : failed(result);
 }
 if (context.route === 'confirmations') {
  const result = confirmationParams({filters: context.filters, sort: context.sort, cursor: context.cursor});
  return result.ok ? {ok: true, url: `/api/confirmations${queryString(result.params)}`} : failed(result);
 }
 if (context.route === 'confirmation') {
  const target = parseCaseSelection(context.selected);
  if (!target) return {ok: false, reason: 'unlocated', unsupported: [], invalid: []};
  const query = target.confirmationKey ? `?confirmation_key=${encodeURIComponent(target.confirmationKey)}` : '';
  return {ok: true, url: `/api/case-detail/${encodeURIComponent(target.projectId)}${query}`};
 }
 if (!context.selected) return {ok: false, reason: 'unlocated', unsupported: [], invalid: []};
 return {ok: true, url: `/api/${context.route === 'contract' ? 'contract-detail' : 'work-item-detail'}?key=${encodeURIComponent(context.selected)}`};
}

// ---- transport -> state --------------------------------------------------------------------------------------------
export type P2State = 'forbidden' | 'unlocated' | 'read_failed';
export interface P2Failure {state: P2State; httpStatus: number | null; retry: boolean; message: string}
const DETAIL_ROUTES: readonly string[] = ['confirmation', 'contract', 'workitem'];
/** 403 -> forbidden; 404 on a detail route -> unlocated (the key is never echoed); anything else -> read_failed.
 *  The HTTP status is kept for diagnosis. A read failure may be retried with the identical GET (no other request is made). */
export function p2Failure(route: P2Route, fetched: {status: 'error'; httpStatus?: number}): P2Failure {
 const httpStatus = fetched.httpStatus ?? null;
 if (httpStatus === 403) return {state: 'forbidden', httpStatus, retry: false, message: '沒有權限檢視此頁面。'};
 if (httpStatus === 404 && DETAIL_ROUTES.includes(route)) return {state: 'unlocated', httpStatus, retry: false, message: '找不到此項目，或你沒有權限檢視。'};
 return {state: 'read_failed', httpStatus, retry: true, message: '讀取失敗，目前無法確認資料內容。'};
}

// ---- navigation built only from drilldownContext --------------------------------------------------------------
/** KPI card -> Confirmation List with exactly the card's drilldown filters; refused (never narrowed) when one is not representable. */
export function kpiDrill(context: P2Context, drilldown: {route: unknown; filters: unknown}, cardId: string): Result<P2Context> {
 if (drilldown.route !== 'confirmations') return {ok: false, reason: 'edge_not_allowed', value: context};
 const mapped = backendFiltersToNav(drilldown.filters);
 if (!mapped.ok) return {ok: false, reason: 'kpi_filter_not_representable', value: context};
 return drill(context, 'confirmations', {kpi: {id: cardId, filters: mapped.filters}});
}
/** The case a contract / work item was reached from: the nearest Case Detail ancestor. Without one the case is unlocated, never guessed. */
export function ancestorCase(context: P2Context): string | null {
 for (let i = context.stack.length - 1; i >= 0; i--) {
  const frame = context.stack[i];
  const target = frame.route === 'confirmation' ? parseCaseSelection(frame.selected) : null;
  if (target) return target.projectId;
 }
 return context.route === 'confirmation' ? parseCaseSelection(context.selected)?.projectId ?? null : null;
}
/** Case Detail row navigation. A confirmation of the same case switches the version in place (no new parent); contract / work item push. */
export function caseNavigate(context: P2Context, target: {route?: unknown; nativeKey?: unknown}): {mode: 'push' | 'replace'; result: Result<P2Context>} | null {
 const key = sourceKeyOf(target.nativeKey);
 if (!key) return null;
 if (target.route === 'confirmation') {
  const current = parseCaseSelection(context.selected);
  if (context.route !== 'confirmation' || !current) return null;
  return {mode: 'replace', result: {ok: true, value: {...context, selected: caseSelection(current.projectId, key)}}};
 }
 if (target.route === 'contract' || target.route === 'workitem') return {mode: 'push', result: drill(context, target.route, {selected: key})};
 return null;
}
/** Contract / Work Item row navigation (route + opaque key). A confirmation target needs the case from the parent stack. */
export function detailNavigate(context: P2Context, target: {route: P2Route; key: string}): Result<P2Context> | null {
 const key = sourceKeyOf(target.key);
 if (!key) return null;
 if (target.route === 'confirmation') {
  const projectId = ancestorCase(context);
  return projectId ? drill(context, 'confirmation', {selected: caseSelection(projectId, key)}) : null;
 }
 return drill(context, target.route, {selected: key});
}
export const p2Back = navBack;
