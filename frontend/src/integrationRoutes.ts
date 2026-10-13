// P1-INT glue (pure, framework-free): hash routing, return context and fetched-payload adapters for the
// #work and #sources pages. No fetch here; App/page components own transport. Unknown stays unknown.
import {decodeReturnContext, encodeReturnContext} from './myWorkView.ts';
import type {MyWorkFilters, MyWorkInput} from './myWorkView.ts';

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
  canSeeAwaitingConfirmation: body.canSeeAwaitingConfirmation === true};
}

export function sourceHealthInput(fetched: Fetched): {page_state: unknown; sources: unknown} {
 if (fetched.status === 'loading') return {page_state: {states: ['loading'], count: null}, sources: []};
 if (fetched.status === 'error') return {page_state: failureState(fetched), sources: []};
 const body = record(fetched.body);
 // A missing page_state key is unknown; only an explicit null is the clean-read fact (see sourceHealthView).
 if (!body || !('page_state' in body)) return {page_state: {states: ['unknown'], count: null}, sources: []};
 return {page_state: body.page_state, sources: body.sources};
}
