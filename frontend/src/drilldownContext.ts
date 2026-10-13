// P2 drilldown / return-context module (pure, unwired; P2-INT registers routes later).
// Routes: 128 overview, 129 confirmations, 130 confirmation, 131 contract, 132 workitem.
// A context is everything Back must restore: filters, sort, server cursor, columns, selection, period (128 only),
// plus the parent stack for breadcrumbs. It is encoded into one versioned, bounded, strictly validated hash value.
//
// Why myWorkView.encodeReturnContext is not reused: it is a lenient, fixed-shape (search/mode/selectedId) codec that
// silently falls back field by field; P2 needs per-route shapes, unknown-key rejection and all-or-nothing decoding.
// Reuse is by import only for integrationRoutes.hashOfRoute (same-origin hash check of backend entry-point routes).
//
// Privacy: the URL holds only filter values the user chose, opaque row keys and the opaque server cursor (never decoded).
// No contract amounts, sums, hidden IDs or labels of unauthorized objects: unknown keys are rejected, never ignored.
import {hashOfRoute} from './integrationRoutes.ts';

export type P2Route = 'overview' | 'confirmations' | 'confirmation' | 'contract' | 'workitem';
export const P2_ROUTES: readonly P2Route[] = ['overview', 'confirmations', 'confirmation', 'contract', 'workitem'];
export const P2_ROUTE_ISSUE: Readonly<Record<P2Route, number>> = {overview: 128, confirmations: 129, confirmation: 130, contract: 131, workitem: 132};
export const CONTEXT_VERSION = 1;
export const LIMITS = {filterKeys: 8, valueLen: 200, columns: 30, keyLen: 200, cursorLen: 512, stackDepth: 6, encodedLen: 4096} as const;

export type FilterSet = Readonly<Record<string, string>>;
export type SortSpec = {key: string; dir: 'asc' | 'desc'} | null; // null = cleared
export type Period = {start: string; end: string};
export interface Frame {
  route: P2Route; filters: FilterSet; sort: SortSpec; cursor: string | null; columns: readonly string[] | null;
  selected: string | null; period: Period | null; kpi: string | null;
}
export interface P2Context extends Frame {v: 1; stack: readonly Frame[]}

// Filter keys per route. Anything else (amounts, hidden ids, names of forbidden objects) is rejected.
export const FILTER_KEYS: Readonly<Record<P2Route, readonly string[]>> = {
  overview: ['pm', 'execution_state'],
  confirmations: ['search', 'source_version', 'pm', 'admission', 'deadline_from', 'deadline_to', 'execution_state', 'pending_decision', 'blocked', 'stage'],
  confirmation: [], contract: [], workitem: [],
};
// Which routes may drill to which. Reports/Documents/Source Health are link-only (linkOut), not P2 routes.
const EDGES: Readonly<Record<P2Route, readonly P2Route[]>> = {
  overview: ['confirmations', 'confirmation'],
  confirmations: ['confirmation'],
  confirmation: ['contract', 'workitem'],
  contract: ['workitem', 'confirmation'],
  workitem: ['contract', 'confirmation'],
};

export type Reason =
  | 'not_string' | 'oversize' | 'bad_encoding' | 'bad_json' | 'bad_shape' | 'unknown_key' | 'unknown_version' | 'wrong_route'
  | 'bad_filter' | 'bad_sort' | 'bad_cursor' | 'bad_columns' | 'bad_selected' | 'bad_period' | 'period_not_allowed' | 'bad_kpi' | 'bad_stack'
  | 'edge_not_allowed' | 'no_parent' | 'kpi_filter_not_representable' | 'kpi_filter_conflict' | 'corrupt_return_frame' | 'bad_link' | 'bad_route';
export type Result<T> = {ok: true; value: T} | {ok: false; reason: Reason; value: P2Context};

export const emptyFrame = (route: P2Route): Frame => ({route, filters: {}, sort: null, cursor: null, columns: null, selected: null, period: null, kpi: null});
export const defaultContext = (route: P2Route): P2Context => ({v: 1, ...emptyFrame(route), stack: []});

// ---- strict validation: all or nothing -------------------------------------
const isRec = (x: unknown): x is Record<string, unknown> => x !== null && typeof x === 'object' && !Array.isArray(x);
const onlyKeys = (o: Record<string, unknown>, allowed: readonly string[]) => Object.keys(o).every(k => allowed.includes(k));
const CTRL = /[\u0000-\u001f\u007f]/;
const text = (x: unknown, max: number, nonEmpty = true): x is string => typeof x === 'string' && x.length <= max && (!nonEmpty || x.length > 0) && !CTRL.test(x);
const NAME = /^[a-z][a-z0-9_]{0,39}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const CURSOR = /^[\x21-\x7e]+$/; // printable ASCII, no whitespace; never decoded or interpreted
const validDay = (s: string) => DAY.test(s) && !Number.isNaN(Date.parse(s + 'T00:00:00Z')) && new Date(s + 'T00:00:00Z').toISOString().slice(0, 10) === s;
const FRAME_KEYS = ['route', 'filters', 'sort', 'cursor', 'columns', 'selected', 'period', 'kpi'];

function parseFrame(x: unknown): {frame: Frame} | {reason: Reason} {
  if (!isRec(x)) return {reason: 'bad_shape'};
  if (!onlyKeys(x, FRAME_KEYS)) return {reason: 'unknown_key'};
  const route = x.route;
  if (typeof route !== 'string' || !(P2_ROUTES as readonly string[]).includes(route)) return {reason: 'wrong_route'};
  const r = route as P2Route;
  // filters
  if (!isRec(x.filters)) return {reason: 'bad_filter'};
  const fk = Object.keys(x.filters);
  if (fk.length > LIMITS.filterKeys) return {reason: 'oversize'};
  const filters: Record<string, string> = {};
  for (const k of fk) {
    if (!FILTER_KEYS[r].includes(k)) return {reason: 'unknown_key'};
    const val = x.filters[k];
    if (!text(val, LIMITS.valueLen)) return {reason: 'bad_filter'};
    filters[k] = val;
  }
  // sort
  let sort: SortSpec = null;
  if (x.sort !== null) {
    if (!isRec(x.sort) || !onlyKeys(x.sort, ['key', 'dir'])) return {reason: 'bad_sort'};
    if (typeof x.sort.key !== 'string' || !NAME.test(x.sort.key) || (x.sort.dir !== 'asc' && x.sort.dir !== 'desc')) return {reason: 'bad_sort'};
    sort = {key: x.sort.key, dir: x.sort.dir};
  }
  // cursor
  let cursor: string | null = null;
  if (x.cursor !== null) {
    if (typeof x.cursor !== 'string' || x.cursor.length > LIMITS.cursorLen || !CURSOR.test(x.cursor)) return {reason: 'bad_cursor'};
    cursor = x.cursor;
  }
  // columns
  let columns: string[] | null = null;
  if (x.columns !== null) {
    if (!Array.isArray(x.columns) || x.columns.length > LIMITS.columns) return {reason: 'bad_columns'};
    if (!x.columns.every(c => typeof c === 'string' && NAME.test(c)) || new Set(x.columns).size !== x.columns.length) return {reason: 'bad_columns'};
    columns = [...x.columns as string[]];
  }
  // selected (opaque row key)
  let selected: string | null = null;
  if (x.selected !== null) {
    if (!text(x.selected, LIMITS.keyLen)) return {reason: 'bad_selected'};
    selected = x.selected;
  }
  // period: Manager Overview weekly activity only
  let period: Period | null = null;
  if (x.period !== null) {
    if (r !== 'overview') return {reason: 'period_not_allowed'};
    if (!isRec(x.period) || !onlyKeys(x.period, ['start', 'end'])) return {reason: 'bad_period'};
    const {start, end} = x.period;
    if (typeof start !== 'string' || typeof end !== 'string' || !validDay(start) || !validDay(end) || start > end) return {reason: 'bad_period'};
    period = {start, end};
  }
  let kpi: string | null = null;
  if (x.kpi !== null) {
    if (typeof x.kpi !== 'string' || !NAME.test(x.kpi)) return {reason: 'bad_kpi'};
    kpi = x.kpi;
  }
  return {frame: {route: r, filters, sort, cursor, columns, selected, period, kpi}};
}

export function validateContext(x: unknown): Result<P2Context> {
  const bad = (reason: Reason): Result<P2Context> => ({ok: false, reason, value: defaultContext('overview')});
  if (!isRec(x)) return bad('bad_shape');
  if (x.v !== CONTEXT_VERSION) return bad('unknown_version');
  if (!onlyKeys(x, ['v', 'stack', ...FRAME_KEYS])) return bad('unknown_key');
  if (!Array.isArray(x.stack)) return bad('bad_stack');
  if (x.stack.length > LIMITS.stackDepth) return bad('oversize');
  const {stack: rawStack, v: _v, ...rawFrame} = x;
  const top = parseFrame(rawFrame);
  if ('reason' in top) return bad(top.reason);
  const stack: Frame[] = [];
  for (const f of rawStack as unknown[]) {
    const p = parseFrame(f);
    if ('reason' in p) return bad('bad_stack');
    stack.push(p.frame);
  }
  // Every adjacent pair, ending at the current route, must be a permitted drill edge.
  const chain = [...stack.map(f => f.route), top.frame.route];
  for (let i = 1; i < chain.length; i++) if (!EDGES[chain[i - 1]].includes(chain[i])) return bad('bad_stack');
  return {ok: true, value: {v: 1, ...top.frame, stack}};
}

// ---- hash codec -----------------------------------------------------------
// Key order is fixed so encode(decode(h)) === h and equal contexts always give equal hashes.
const canonical = (c: P2Context) => {
  const f = (fr: Frame) => ({
    route: fr.route, filters: Object.fromEntries(Object.keys(fr.filters).sort().map(k => [k, fr.filters[k]])),
    sort: fr.sort ? {key: fr.sort.key, dir: fr.sort.dir} : null, cursor: fr.cursor, columns: fr.columns ? [...fr.columns] : null,
    selected: fr.selected, period: fr.period ? {start: fr.period.start, end: fr.period.end} : null, kpi: fr.kpi,
  });
  return {v: 1, ...f(c), stack: c.stack.map(f)};
};
const b64 = (s: string) => { const b = new TextEncoder().encode(s); let t = ''; for (const x of b) t += String.fromCharCode(x); return btoa(t).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
const unb64 = (s: string) => { const t = atob(s.replace(/-/g, '+').replace(/_/g, '/')); return new TextDecoder('utf-8', {fatal: true}).decode(Uint8Array.from(t, ch => ch.charCodeAt(0))); };

/** Encodes to the value of the `ctx` hash parameter. Invalid or oversize input is refused, never truncated. */
export function encodeContext(c: P2Context): Result<string> {
  const v = validateContext(c);
  if (!v.ok) return {ok: false, reason: v.reason, value: defaultContext('overview')};
  const out = b64(JSON.stringify(canonical(v.value)));
  if (out.length > LIMITS.encodedLen) return {ok: false, reason: 'oversize', value: defaultContext(c.route)};
  return {ok: true, value: out};
}

/** Decodes a `ctx` value. Any problem returns the safe default for `expected` with a reason; nothing is partially applied. */
export function decodeContext(encoded: unknown, expected: P2Route): Result<P2Context> {
  const safe = (reason: Reason): Result<P2Context> => ({ok: false, reason, value: defaultContext(expected)});
  if (typeof encoded !== 'string') return safe('not_string');
  if (encoded.length > LIMITS.encodedLen) return safe('oversize');
  if (!/^[A-Za-z0-9_-]+$/.test(encoded)) return safe('bad_encoding');
  let json: string;
  try { json = unb64(encoded); } catch { return safe('bad_encoding'); }
  let parsed: unknown;
  try { parsed = JSON.parse(json); } catch { return safe('bad_json'); }
  const v = validateContext(parsed);
  if (!v.ok) return safe(v.reason);
  if (v.value.route !== expected) return safe('wrong_route');
  // Reject non-canonical encodings (e.g. reordered keys) so a tampered-but-valid payload cannot alias another hash.
  if (encodeContext(v.value).value !== encoded) return safe('bad_encoding');
  return v;
}

export const hashFor = (c: P2Context): Result<string> => {
  const e = encodeContext(c);
  return e.ok ? {ok: true, value: `view=${c.route}&ctx=${e.value}`} : e;
};
/** Parses `view=<route>&ctx=<value>`. Unknown view -> bad_route with the Manager Overview default. */
export function parseHash(hash: unknown): Result<P2Context> {
  if (typeof hash !== 'string') return {ok: false, reason: 'not_string', value: defaultContext('overview')};
  if (hash.length > LIMITS.encodedLen + 64) return {ok: false, reason: 'oversize', value: defaultContext('overview')};
  const p = new URLSearchParams(hash.replace(/^#\/?/, ''));
  const view = p.get('view');
  if (!view || !(P2_ROUTES as readonly string[]).includes(view)) return {ok: false, reason: 'bad_route', value: defaultContext('overview')};
  const ctx = p.get('ctx');
  if (ctx === null) return {ok: true, value: defaultContext(view as P2Route)}; // bare hash = default context
  return decodeContext(ctx, view as P2Route);
}

// ---- navigation -------------------------------------------------------------
const clone = <T>(x: T): T => structuredClone(x);
const frameOf = (c: P2Context): Frame => { const {v: _v, stack: _s, ...f} = clone(c); return f; };

export interface DrillTarget {
  route: P2Route;
  filters?: FilterSet;
  selected?: string | null;
  columns?: readonly string[] | null;
  sort?: SortSpec;
  /** KPI drilldown 128 -> 129: `filters` is the exact filter set that defines the KPI population. */
  kpi?: {id: string; filters: FilterSet};
}
const sameFilters = (a: FilterSet, b: FilterSet) => {
  const ak = Object.keys(a), bk = Object.keys(b);
  return ak.length === bk.length && ak.every(k => Object.prototype.hasOwnProperty.call(b, k) && a[k] === b[k]);
};
export const sameFilterSet = sameFilters;

/** Push `from` (full state, exactly as shown) as a parent frame and open `to`. Cursor/sort never cross routes; period never leaves 128. */
export function drill(from: P2Context, to: P2Route, target: Omit<DrillTarget, 'route'> = {}): Result<P2Context> {
  const f = validateContext(from);
  if (!f.ok) return f;
  if (!EDGES[f.value.route].includes(to)) return {ok: false, reason: 'edge_not_allowed', value: f.value};
  if (f.value.stack.length + 1 > LIMITS.stackDepth - 1) return {ok: false, reason: 'oversize', value: f.value};
  let filters: FilterSet = target.filters ?? {};
  let kpi: string | null = null;
  if (target.kpi) {
    if (f.value.route !== 'overview' || to !== 'confirmations') return {ok: false, reason: 'bad_kpi', value: f.value};
    if (target.filters && !sameFilters(target.filters, target.kpi.filters)) return {ok: false, reason: 'kpi_filter_conflict', value: f.value};
    // Every KPI filter must be representable on 129; refuse rather than drop one (a dropped filter changes the population).
    if (!Object.keys(target.kpi.filters).every(k => FILTER_KEYS.confirmations.includes(k))) return {ok: false, reason: 'kpi_filter_not_representable', value: f.value};
    filters = target.kpi.filters;
    kpi = target.kpi.id;
  }
  const next: P2Context = {
    v: 1, ...clone({route: to, filters: {...filters}, sort: target.sort ?? null, cursor: null,
      columns: target.columns ? [...target.columns] : null, selected: target.selected ?? null, period: null, kpi}),
    stack: [...clone(f.value.stack as Frame[]), frameOf(f.value)],
  };
  const v = validateContext(next);
  return v.ok ? v : {ok: false, reason: v.reason, value: f.value};
}

/** Restore exactly the previous context (filters, sort, cursor, columns, selection, period) and its own stack. */
export function back(current: P2Context): Result<P2Context> {
  const c = validateContext(current);
  if (!c.ok) return c.reason === 'bad_stack' ? {...c, reason: 'corrupt_return_frame'} : c;
  const stack = c.value.stack;
  if (stack.length === 0) return {ok: false, reason: 'no_parent', value: c.value};
  const parent = stack[stack.length - 1];
  // validateContext above already proved every stored frame is valid and each parent->child pair is a permitted edge.
  // A tampered stack therefore arrives here only as 'bad_stack'; map it to the clearer return-specific reason.
  return {ok: true, value: {v: 1, ...clone(parent), stack: clone(stack.slice(0, -1) as Frame[])}};
}

/** Breadcrumb jump: restore the ancestor at `depth` (0 = root). Equivalent to repeated back(). */
export function backTo(current: P2Context, depth: number): Result<P2Context> {
  let c: Result<P2Context> = {ok: true, value: current};
  if (!Number.isInteger(depth) || depth < 0) return {ok: false, reason: 'bad_stack', value: current};
  while (c.ok && c.value.stack.length > depth) c = back(c.value);
  return c;
}

export interface Crumb {route: P2Route; issue: number; depth: number; selected: string | null}
export const breadcrumbs = (c: P2Context): Crumb[] =>
  [...c.stack, c].map((f, depth) => ({route: f.route, issue: P2_ROUTE_ISSUE[f.route], depth, selected: f.selected}));

// ---- link-only existing routes ---------------------------------------------
/** Source Health is an existing view; Reports/Documents/R-report links must be same-origin entry-point routes the backend already
 *  authorised for the caller (hashOfRoute). Nothing is invented here; the return context is not appended to foreign views. */
export function linkOut(kind: 'sources' | 'entry_point', route?: unknown): {ok: true; hash: string} | {ok: false; reason: Reason} {
  if (kind === 'sources') return {ok: true, hash: 'view=sources'};
  const h = hashOfRoute(route);
  return h ? {ok: true, hash: h} : {ok: false, reason: 'bad_link'};
}
