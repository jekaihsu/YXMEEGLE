// P2-INT-F: pure route / adapter / history / transport logic of the five P2 pages (VCC-128..132), plus wiring checks.
// Run: node test-p2-routes.mjs   (Node >= 22, type stripping; no network, no browser, synthetic keys only)
// The suite runs against the real module, then against each mutant below; every mutant must make at least one test fail.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(root, 'src');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const backendApp = fs.readFileSync(path.join(root, '..', 'backend', 'app.py'), 'utf8');
const D = await import(pathToFileURL(path.join(SRC, 'drilldownContext.ts')).href);

const tuple = name => new Set([...backendApp.match(new RegExp(`${name}=\\(([^)]*)\\)`))[1].matchAll(/'([a-z_]+)'/g)].map(x => x[1]));
const frozen = name => new Set([...backendApp.match(new RegExp(`${name}=frozenset\\(\\{([^}]*)\\}\\)`))[1].matchAll(/'([a-z_]+)'/g)].map(x => x[1]));
const BACKEND = {list: frozen('P2_LIST_PARAMS'), filters: tuple('P2_FILTER_PARAMS'), caseParams: frozen('P2_CASE_PARAMS')};

const hashOf = r => {const q = new URLSearchParams(); for (const [k, v] of Object.entries(r)) if (v) q.set(k, v); return q.toString();};
const ctx = (route, extra = {}) => ({...D.defaultContext(route), ...extra});
const roundTrip = c => {const r = M0.p2RouteOfContext(c); const parsed = D.parseHash('#' + hashOf(r)); assert.equal(parsed.ok, true, parsed.reason); return parsed.value;};
let M0; // the module under test, set per run (hashOf/roundTrip helpers use it)

const TESTS = [];
const test = (name, fn) => TESTS.push([name, fn]);
const params = r => {assert.equal(r.ok, true, JSON.stringify(r)); return new URLSearchParams(r.params.map(([k, v]) => [k, v]));};

test('route parse and serialize: all five routes round-trip through the hash; bare hash is the default context', M => {
 const KEY = 'bT1/tb1/rec1';
 const contexts = {
  overview: ctx('overview', {filters: {pm: 'u-a', execution_state: 'pending'}, sort: {key: 'label', dir: 'asc'}, selected: 'p1'}),
  confirmations: ctx('confirmations', {filters: {search: '橋 & 路 #1', source_version: 'v1,v2', admission: 'pending'}, sort: {key: 'pm', dir: 'desc'}, cursor: 'abc_-9', columns: ['case_number', 'pm'], selected: `${KEY}@s1`}),
  confirmation: ctx('confirmation', {selected: M.caseSelection('p1', KEY)}),
  contract: ctx('contract', {selected: KEY}),
  workitem: ctx('workitem', {selected: KEY}),
 };
 for (const route of D.P2_ROUTES) {
  const c = contexts[route];
  const r = M.p2RouteOfContext(c);
  assert.equal(r.view, route);
  assert.deepEqual(roundTrip(c), c, route);
  assert.equal(D.hashFor(c).value, hashOf(r), 'serialization equals NAV hashFor');
  assert.equal(M.p2ContextOfRoute({view: route, ctx: r.ctx}).ok, true);
  assert.equal(M.isP2View(route), true);
 }
 for (const route of D.P2_ROUTES) {
  assert.deepEqual(M.p2RouteOfContext(ctx(route)), {view: route}, 'default context keeps the bare hash');
  assert.deepEqual(M.p2ContextOfRoute({view: route}), {ok: true, value: ctx(route)});
 }
 // a tampered / wrong-view / unknown ctx is never partially applied
 const good = M.p2RouteOfContext(contexts.contract).ctx;
 for (const [bad, why] of [[{view: 'overview', ctx: good}, 'wrong_route'], [{view: 'contract', ctx: good + 'x'}, 'bad_encoding'], [{view: 'contract', ctx: '%%'}, 'bad_encoding']]) {
  const r = M.p2ContextOfRoute(bad);
  assert.equal(r.ok, false); assert.deepEqual(r.value, ctx(bad.view)); assert.ok(r.reason, why);
 }
 assert.equal(M.p2ContextOfRoute({view: 'work'}).ok, false);
 assert.equal(M.isP2View('work'), false);
 assert.equal(M.p2ActiveNav('contract'), 'confirmations'); assert.equal(M.p2ActiveNav('workitem'), 'confirmations'); assert.equal(M.p2ActiveNav('overview'), 'overview');
});

test('request URLs: one GET per page, built only from the validated context (no technical ids beyond opaque keys)', M => {
 const KEY = 'bT1/tb1/rec1';
 const url = c => {const r = M.p2Request(c); assert.equal(r.ok, true, JSON.stringify(r)); return r.url;};
 assert.equal(url(ctx('overview')), '/api/manager-overview');
 assert.equal(url(ctx('overview', {filters: {pm: 'u-a', execution_state: 'pending'}})), '/api/manager-overview?execution_status=pending&pm_id=u-a');
 assert.equal(url(ctx('confirmations')), '/api/confirmations?limit=50');
 const list = new URL(url(ctx('confirmations', {filters: {search: 'a b', pm: 'p1'}, sort: {key: 'pm', dir: 'desc'}, cursor: 'c_1'})), 'http://x');
 assert.deepEqual([...list.searchParams], [['q', 'a b'], ['pm', 'p1'], ['sort', 'pm'], ['direction', 'desc'], ['cursor', 'c_1'], ['limit', '50']]);
 assert.equal(url(ctx('confirmation', {selected: M.caseSelection('p1')})), '/api/case-detail/p1');
 assert.equal(url(ctx('confirmation', {selected: M.caseSelection('p1', KEY)})), `/api/case-detail/p1?confirmation_key=${encodeURIComponent(KEY)}`);
 assert.equal(url(ctx('contract', {selected: KEY})), `/api/contract-detail?key=${encodeURIComponent(KEY)}`);
 assert.equal(url(ctx('workitem', {selected: KEY})), `/api/work-item-detail?key=${encodeURIComponent(KEY)}`);
 for (const route of ['confirmation', 'contract', 'workitem']) assert.equal(M.p2Request(ctx(route)).ok, false, `${route} without a target is unlocated, not fetched`);
 assert.equal(M.p2Request(ctx('confirmation', {selected: 'p1'})).reason, 'unlocated', 'a bare id is not a case selection');
 // case selection is injective for awkward ids
 for (const [id, key] of [['p?1:x', null], ['p 1', KEY], ['id/with/slash', 'a?b=c&d']]) {
  assert.deepEqual(M.parseCaseSelection(M.caseSelection(id, key)), {projectId: id, confirmationKey: key});
 }
 for (const bad of [null, '', 'case:', 'case:?conf=x', 'case:a?conf=', 'case:a?x=1', 'case:a?conf=1?conf=2', 'p1', 5, 'case:%E0%A4%A']) assert.equal(M.parseCaseSelection(bad), null, String(bad));
});

test('lossless filter adapter: every real backend key is covered and round-trips', M => {
 // Real backend vocabulary read from backend/app.py.
 assert.deepEqual([...BACKEND.filters].sort(), ['admission_state', 'deadline_from', 'deadline_to', 'pm', 'source_version']);
 assert.deepEqual([...BACKEND.caseParams].sort(), ['execution_status', 'pm_id']);
 const nav = {search: 'x', source_version: 'a', pm: 'b', admission: 'c', deadline_from: '2026-01-01', deadline_to: '2026-02-01'};
 const emitted = new Set(params(M.confirmationParams({filters: nav, sort: {key: 'pm', dir: 'asc'}, cursor: 'k', limit: 20})).keys());
 assert.deepEqual([...emitted].sort(), [...BACKEND.list].sort(), 'adapter emits exactly the backend list parameters');
 for (const key of Object.keys(nav)) {
  const one = M.confirmationParams({filters: {[key]: 'v'}});
  assert.equal(one.ok, true, key);
  assert.equal(one.params.length, 2, `${key}: one backend parameter plus limit`);
 }
 // overview: case filters only, backend names pm_id / execution_status, nothing else
 const ov = params(M.overviewParams({pm: 'u-a', execution_state: 'pending'}));
 assert.deepEqual([...ov.keys()].sort(), [...BACKEND.caseParams].sort());
 for (const k of ov.keys()) assert.ok(!BACKEND.filters.has(k), `${k} is a case filter, never a list filter`);
 assert.deepEqual(M.overviewBackendFilters({pm: 'u-a', execution_state: 'pending', other: 'z'}), {pm_id: 'u-a', execution_status: 'pending'});
 assert.equal(M.overviewParams({pm: 'u-a', source_version: 'v1'}).ok, false, 'list vocabulary is not a case filter and is refused, not dropped');
 // round trip: backend object -> NAV -> backend object and -> request parameters
 const samples = [
  {source_version: ['v2', 'v1'], pm: ['p-b', 'p-a'], admission_state: ['pending']},
  {source_version: ['v,1', 'v\\2', 'plain'], deadline_from: '2026-01-01', deadline_to: '2026-12-31'},
  {pm: ['單一 PM'], q: undefined},
 ];
 for (const sample of samples) {
  const clean = Object.fromEntries(Object.entries(sample).filter(([, v]) => v !== undefined));
  const toNav = M.backendFiltersToNav(clean);
  assert.equal(toNav.ok, true, JSON.stringify(clean));
  const back = M.navFiltersToBackend(toNav.filters);
  const sorted = Object.fromEntries(Object.entries(clean).map(([k, v]) => [k, Array.isArray(v) ? [...new Set(v)].sort() : v]));
  assert.deepEqual(back.filters, sorted, 'multi-select sets survive exactly');
  const q = params(M.confirmationParams({filters: toNav.filters}));
  for (const [k, v] of Object.entries(sorted)) assert.deepEqual(q.getAll(k), Array.isArray(v) ? v : [v], k);
 }
 assert.deepEqual(M.decodeSet(M.encodeSet(['b', 'a,b', 'a\\'])), ['a,b', 'a\\', 'b']);
 assert.deepEqual(M.decodeSet(' x , y,,x '), ['x', 'y']);
 assert.equal(M.encodeSet([]), null); assert.equal(M.encodeSet(['']), null); assert.equal(M.encodeSet([' a']), null);
 // search: NAV search is the backend q and survives
 assert.equal(params(M.confirmationParams({filters: {search: '橋 ?&='}})).get('q'), '橋 ?&=');
 // never drop: unknown / provisional NAV keys are reported
 const refused = M.confirmationParams({filters: {...nav, execution_state: 'x', blocked: '1', stage: 's', pending_decision: 'y'}});
 assert.equal(refused.ok, false);
 assert.deepEqual(refused.unsupported, ['blocked', 'execution_state', 'pending_decision', 'stage']);
 assert.deepEqual([...M.NAV_FILTERS_WITHOUT_BACKEND_KEY].sort(), refused.unsupported);
 assert.equal(M.confirmationParams({filters: {pm: ' , '}}).ok, false, 'an empty set is invalid, not silently "no filter"');
 for (const bad of [{pm_id: 'u'}, {source_version: []}, {source_version: [1]}, {q: 'x'.repeat(0)}, {deadline_from: 5}, {unknown: 'x'}, {pm: ['a', ' b']}]) {
  assert.equal(M.backendFiltersToNav(bad).ok, false, JSON.stringify(bad));
 }
 assert.equal(M.backendFiltersToNav(null).ok, false);
 assert.equal(M.navFiltersToBackend({stage: 'x'}).ok, false);
 // deadline is carried (non-hiding is the server's filter_status.hides_rows=false; unavailability is shown by the view model)
 assert.equal(params(M.confirmationParams({filters: {deadline_from: '2026-01-01', deadline_to: '2026-02-01'}})).get('deadline_to'), '2026-02-01');
});

test('KPI drilldown opens Confirmation List with exactly the card drilldown filters', M => {
 const overview = ctx('overview', {filters: {pm: 'u-a'}, selected: 'p1', sort: {key: 'label', dir: 'asc'}});
 const drilldown = {route: 'confirmations', filters: {source_version: ['v2', 'v1'], deadline_from: '2026-01-01'}, group_by: 'row_key'};
 const r = M.kpiDrill(overview, drilldown, 'confirmation_versions');
 assert.equal(r.ok, true, r.reason);
 assert.equal(r.value.route, 'confirmations'); assert.equal(r.value.kpi, 'confirmation_versions');
 assert.deepEqual(r.value.filters, {source_version: 'v1,v2', deadline_from: '2026-01-01'}, 'no overview case filter leaks in; none of the card filters is lost');
 const q = params(M.confirmationParams({filters: r.value.filters}));
 assert.deepEqual(q.getAll('source_version'), ['v1', 'v2']); assert.equal(q.get('deadline_from'), '2026-01-01'); assert.equal(q.has('pm'), false); assert.equal(q.has('pm_id'), false);
 assert.equal(r.value.cursor, null); assert.equal(r.value.sort, null);
 assert.deepEqual(r.value.stack[0], {route: 'overview', filters: {pm: 'u-a'}, sort: {key: 'label', dir: 'asc'}, cursor: null, columns: null, selected: 'p1', period: null, kpi: null});
 // an unfiltered card still opens the unfiltered list
 const none = M.kpiDrill(overview, {route: 'confirmations', filters: {}, group_by: 'project_id'}, 'stable_cases');
 assert.equal(none.ok, true); assert.deepEqual(none.value.filters, {});
 // a card filter that the list cannot represent refuses the drilldown instead of narrowing or widening it
 const refused = M.kpiDrill(overview, {route: 'confirmations', filters: {source_version: ['v1'], pm_id: 'u-a'}, group_by: 'row_key'}, 'x');
 assert.equal(refused.ok, false); assert.equal(refused.reason, 'kpi_filter_not_representable'); assert.deepEqual(refused.value, overview);
 assert.equal(M.kpiDrill(overview, {route: 'contract', filters: {}}, 'x').ok, false);
 assert.equal(M.kpiDrill(ctx('confirmations'), drilldown, 'x').ok, false, 'KPI drilldown only leaves the overview');
});

test('cursor history is the stack of actually used server cursors, bound to the identical query', M => {
 const store = new Map();
 const f = {pm: 'a'}, s = {key: 'pm', dir: 'asc'};
 assert.deepEqual(M.boundHistory(store, f, s, null).stack, []);
 M.recordPage(store, f, s, null, 'c1');
 assert.deepEqual(M.boundHistory(store, f, s, 'c1'), {filters: f, sort: s, current: 'c1', stack: [null]});
 M.recordPage(store, f, s, 'c1', 'c2');
 assert.deepEqual(M.boundHistory(store, f, s, 'c2').stack, [null, 'c1']);
 // different filters, sort, or a cursor that was not the recorded current: nothing is replayed
 assert.deepEqual(M.boundHistory(store, {pm: 'b'}, s, 'c2').stack, []);
 assert.deepEqual(M.boundHistory(store, f, {key: 'pm', dir: 'desc'}, 'c2').stack, []);
 assert.deepEqual(M.boundHistory(store, f, null, 'c2').stack, []);
 assert.deepEqual(M.boundHistory(store, f, s, 'c9').stack, []);
 assert.deepEqual(M.boundHistory(store, f, s, null).stack, [], 'page one has no previous');
 // Prev pops; the cursor it returns is the one that was really requested (null = page one)
 M.recordPage(store, f, s, 'c2', 'c1');
 assert.deepEqual(M.boundHistory(store, f, s, 'c1').stack, [null]);
 M.recordPage(store, f, s, 'c1', null);
 assert.deepEqual(M.boundHistory(store, f, s, null).stack, []);
 // another query's history does not disturb this one; key order of the filter object does not matter
 M.recordPage(store, {pm: 'z'}, null, null, 'zz');
 M.recordPage(store, f, s, null, 'c1');
 assert.deepEqual(M.boundHistory(store, f, s, 'c1').stack, [null]);
 assert.equal(M.queryKey({a: '1', b: '2'}, s), M.queryKey({b: '2', a: '1'}, s));
 assert.notEqual(M.queryKey({a: '1'}, s), M.queryKey({a: '1'}, null));
 for (let i = 0; i < 80; i++) M.recordPage(store, {pm: String(i)}, null, null, 'x');
 assert.ok(store.size <= 50, 'bounded');
});

test('transport mapping: 403 forbidden, detail 404 unlocated without key echo, everything else read_failed with status; 503 retries the same GET', M => {
 const KEY = 'secret-base/secret-table/secret-record';
 for (const route of D.P2_ROUTES) {
  const f403 = M.p2Failure(route, {status: 'error', httpStatus: 403});
  assert.equal(f403.state, 'forbidden'); assert.equal(f403.httpStatus, 403); assert.equal(f403.retry, false);
  const f500 = M.p2Failure(route, {status: 'error', httpStatus: 500});
  assert.equal(f500.state, 'read_failed'); assert.equal(f500.httpStatus, 500);
  const f503 = M.p2Failure(route, {status: 'error', httpStatus: 503});
  assert.equal(f503.state, 'read_failed'); assert.equal(f503.httpStatus, 503); assert.equal(f503.retry, true, 'a retryable read failure keeps a retry affordance');
  const none = M.p2Failure(route, {status: 'error'});
  assert.equal(none.state, 'read_failed'); assert.equal(none.httpStatus, null);
  for (const status of [401, 408, 422, 502]) assert.equal(M.p2Failure(route, {status: 'error', httpStatus: status}).state, 'read_failed', `${route} ${status}`);
 }
 for (const route of ['confirmation', 'contract', 'workitem']) {
  const f404 = M.p2Failure(route, {status: 'error', httpStatus: 404});
  assert.equal(f404.state, 'unlocated'); assert.equal(f404.httpStatus, 404); assert.equal(f404.retry, false);
  assert.match(f404.message, /找不到.*沒有權限/);
  assert.ok(!JSON.stringify(f404).includes(KEY) && !JSON.stringify(f404).includes('secret'));
 }
 for (const route of ['overview', 'confirmations']) assert.equal(M.p2Failure(route, {status: 'error', httpStatus: 404}).state, 'read_failed', 'a missing list endpoint is a failed read, not an empty list');
 // retry repeats the identical request: the request is a pure function of the context
 const c = ctx('confirmations', {filters: {pm: 'a'}, cursor: 'k1'});
 assert.equal(M.p2Request(c).url, M.p2Request(structuredClone(c)).url);
});

test('Back restores filters, cursor, sort, columns and selection after a 3-level drill; breadcrumb follows the parent stack', M => {
 const KEY = 'bT1/tb1/rec1', ITEM = 'bT1/tb2/rec2';
 const store = new Map();
 const overview = ctx('overview', {filters: {pm: 'u-a', execution_state: 'pending'}, sort: {key: 'responsible', dir: 'desc'}, selected: 'p1', period: {start: '2026-09-01', end: '2026-09-07'}});
 const viaHash = c => roundTrip(c);
 // level 1: KPI -> list
 const k = M.kpiDrill(viaHash(overview), {route: 'confirmations', filters: {pm: ['u-b', 'u-a']}, group_by: 'row_key'}, 'stable_cases');
 assert.equal(k.ok, true);
 // the user pages, sorts, picks columns and selects a row on the list
 let list = viaHash({...k.value, sort: {key: 'pm', dir: 'asc'}, columns: ['case_number', 'pm'], selected: `${KEY}@s1`});
 M.recordPage(store, list.filters, list.sort, null, 'c1');
 M.recordPage(store, list.filters, list.sort, 'c1', 'c2');
 list = viaHash({...list, cursor: 'c2'});
 // level 2: list row -> case; level 3: case -> contract; and one more: contract -> work item
 const c2 = D.drill(list, 'confirmation', {selected: M.caseSelection('p1', KEY)});
 assert.equal(c2.ok, true);
 const nav3 = M.caseNavigate(viaHash(c2.value), {route: 'contract', nativeKey: `contract:${ITEM}`});
 assert.equal(nav3.mode, 'push'); assert.equal(nav3.result.ok, true);
 const contract = viaHash(nav3.result.value);
 assert.equal(contract.selected, ITEM, 'prefix stripped: the detail endpoint takes the bare source key');
 const wi = M.detailNavigate(contract, {route: 'workitem', key: ITEM});
 assert.equal(wi.ok, true);
 const workitem = viaHash(wi.value);
 assert.deepEqual(D.breadcrumbs(workitem).map(b => b.route), ['overview', 'confirmations', 'confirmation', 'contract', 'workitem']);
 // contract -> confirmation resolves the case from the parent stack and never guesses
 const back2conf = M.detailNavigate(contract, {route: 'confirmation', key: KEY});
 assert.equal(back2conf.ok, true); assert.equal(M.parseCaseSelection(back2conf.value.selected).projectId, 'p1');
 assert.equal(M.ancestorCase(workitem), 'p1');
 assert.equal(M.detailNavigate(ctx('contract', {selected: KEY}), {route: 'confirmation', key: KEY}), null, 'deep-linked contract has no case: unresolved, not guessed');
 // Back x3 restores each frame exactly (every hop passes through the hash)
 const b1 = M.p2Back(workitem); assert.deepEqual(viaHash(b1.value), contract);
 const b2 = M.p2Back(viaHash(b1.value)); assert.deepEqual(viaHash(b2.value), viaHash(c2.value));
 const b3 = M.p2Back(viaHash(b2.value)); assert.deepEqual(viaHash(b3.value), list);
 assert.deepEqual([b3.value.filters, b3.value.sort, b3.value.cursor, b3.value.columns, b3.value.selected],
  [{pm: 'u-a,u-b'}, {key: 'pm', dir: 'asc'}, 'c2', ['case_number', 'pm'], `${KEY}@s1`]);
 // the used-cursor stack is still bound to the restored query: Prev is available and returns the cursor really used
 assert.deepEqual(M.boundHistory(store, b3.value.filters, b3.value.sort, b3.value.cursor).stack, [null, 'c1']);
 const b4 = M.p2Back(b3.value); assert.deepEqual(viaHash(b4.value), viaHash(overview));
 assert.equal(b4.value.period.end, '2026-09-07'); assert.equal(b4.value.selected, 'p1');
 assert.equal(M.p2Back(b4.value).ok, false); assert.equal(M.p2Back(b4.value).reason, 'no_parent');
 // breadcrumb jump restores the same frame as repeated Back
 assert.deepEqual(D.backTo(workitem, 1).value, b3.value);
 // a version switch inside one case replaces the selection and adds no parent
 const sw = M.caseNavigate(viaHash(c2.value), {route: 'confirmation', nativeKey: 'confirmation:bT1/tb1/rec9'});
 assert.equal(sw.mode, 'replace'); assert.equal(sw.result.value.stack.length, c2.value.stack.length);
 assert.equal(M.parseCaseSelection(sw.result.value.selected).confirmationKey, 'bT1/tb1/rec9');
 // keys that are not source keys do not navigate
 for (const nativeKey of ['task:p1/n1/t1', 'node:p1/n1', 'evidence:x/y/z', '', null, 'a/b']) assert.equal(M.caseNavigate(viaHash(c2.value), {route: 'contract', nativeKey}), null, String(nativeKey));
 assert.equal(M.confirmationKeyOfRow('bT1/tb1/rec1@s2'), 'bT1/tb1/rec1'); assert.equal(M.confirmationKeyOfRow('bT1/tb1/rec1'), null);
 assert.equal(M.sourceKeyOf('contract:bT1/tb2/r'), 'bT1/tb2/r'); assert.equal(M.sourceKeyOf('bT1/tb2/r'), 'bT1/tb2/r');
});

test('existing routes only: Source Health and report entries link through linkOut; no write controls, amounts or technical ids are added', M => {
 assert.deepEqual(D.linkOut('sources'), {ok: true, hash: 'view=sources'});
 assert.equal(D.linkOut('entry_point', '/#view=project&project=p1&tab=data&section=files').ok, true);
 for (const bad of ['https://evil.test/#view=project', '//x/#view=a', 'javascript:1', '/#foo=1', null]) assert.equal(D.linkOut('entry_point', bad).ok, false, String(bad));
 const pages = read('src/P2Pages.tsx');
 assert.match(pages, /linkOut\('sources'\)/); assert.match(pages, /linkOut\('entry_point'/);
 assert.doesNotMatch(pages, /method:\s*'(POST|PUT|PATCH|DELETE)'|\bc\.run\(|\/api\/(audit|projects|actions|workspace)\b/, 'read-only; VCC-125 payloads not reused');
 assert.doesNotMatch(pages, /amount|金額|price|sum\(/i, 'contract amounts never appear');
 assert.match(read('src/api.ts'), /fetchP2=\(url:string,signal\?:AbortSignal\)=>api<unknown>\(url,\{method:'GET'/);
});

test('wiring: five hash views, left navigation entries only for the two list pages, legacy views stay reachable', M => {
 const app = read('src/App.tsx'), shell = read('src/AppShell.tsx'), types = read('src/types.ts');
 for (const view of D.P2_ROUTES) assert.ok(types.includes(`'${view}'`), `View type includes ${view}`);
 assert.match(app, /isP2View\(route\.view\)&&<P2Page c=\{c\}\/>/);
 assert.match(app, /p2ActiveNav\(route\.view\)/);
 for (const legacy of ["route.view==='projects'&&<Projects", "route.view==='work'&&(isLegacyTab(route,'work')", "route.view==='sources'&&(isLegacyTab(route,'sources')", "route.view==='project'&&<Suspense"]) assert.ok(app.includes(legacy), legacy);
 assert.match(shell, /\{view:'overview',label:'管理總覽'/); assert.match(shell, /\{view:'confirmations',label:'工程確認單'/);
 assert.doesNotMatch(shell, /\{view:'(confirmation|contract|workitem)',label/);
 assert.match(shell, /\{view:'projects',label:'案件總覽'/); assert.match(shell, /\{view:'work',label:'我的工作'/);
 const ci = fs.readFileSync(path.join(root, '..', 'scripts', 'local_ci.sh'), 'utf8');
 for (const t of ['drilldown-context', 'confirmation-list-view', 'case-detail-view', 'contract-detail-view', 'work-item-detail-view', 'manager-overview-view', 'p2-routes']) assert.ok(ci.includes(`test-${t}.mjs`), `local_ci runs test-${t}`);
});

test('fetch gate (F2): an invalid or unsupported context is refused with no usable request; only the bare reset route is valid', M => {
 const bad = [{view: 'overview', ctx: hashOf({}) + 'zz'}, {view: 'confirmations', ctx: 'not-a-context'}, {view: 'nope'}];
 const real = M.p2RouteOfContext(ctx('overview', {filters: {pm: 'u-a'}}));
 assert.equal(M.p2Gate(real).ok, true);
 // a list-valued overview filter echo with an unknown key (the reviewer's source_version case) is rejected by NAV
 const unsupported = Buffer.from(Buffer.from(D.encodeContext(ctx('overview', {filters: {pm: 'u-a'}})).value, 'base64url').toString().replace('"pm":"u-a"', '"source_version":"2"')).toString('base64url');
 for (const route of [...bad, {view: 'overview', ctx: unsupported}]) {
  const gate = M.p2Gate(route);
  assert.equal(gate.ok, false, JSON.stringify(route));
  assert.deepEqual(gate.context.filters, {}, 'the fallback context is empty and only feeds the reset action');
 }
 const reset = M.p2RouteOfContext(M.p2Gate({view: 'overview', ctx: 'zz'}).context);
 assert.deepEqual(reset, {view: 'overview'}, 'the reset action navigates to the bare hash');
 assert.equal(M.p2Gate(reset).ok, true, 'and the bare hash is valid, so only then a read is allowed');
 const pages = read('src/P2Pages.tsx');
 assert.match(pages, /parsed\.ok \? p2Request\(context\) : null/, 'the request is built only from a validated context');
 assert.match(pages, /if \(!parsed\.ok\) page = <InvalidContext/, 'invalid context renders the refusal instead of data');
});

test('list edit state (F1): draft vs committed query comparison ignores blanks and order; page keeps the list mounted while reading', M => {
 assert.equal(M.sameFilters({search: 'V'}, {search: 'V'}), true);
 assert.equal(M.sameFilters({search: 'VI'}, {search: 'V'}), false);
 assert.equal(M.sameFilters({search: ' ', pm: 'a'}, {pm: 'a'}), true);
 assert.equal(M.sameFilters({pm: 'a', search: 'x'}, {search: 'x', pm: 'a'}), true);
 assert.equal(M.sameFilters({}, {search: 'x'}), false);
 const pages = read('src/P2Pages.tsx');
 assert.match(pages, /fetched\.status === 'loading' && context\.route !== 'confirmations'/, 'confirmations is not replaced by a loading notice');
 assert.match(pages, /onSearch=\{search => edit\(/); assert.doesNotMatch(pages, /onSearch=\{search => requery/, 'typing does not commit immediately');
});

// ---- runner ------------------------------------------------------------------------------------------------------------
async function run(M) {
 M0 = M;
 const failed = [];
 for (const [name, fn] of TESTS) {try {await fn(M);} catch (error) {failed.push([name, error]);}}
 return failed;
}
const real = await import(pathToFileURL(path.join(SRC, 'p2Routes.ts')).href);
const realFailed = await run(real);
for (const [name, error] of realFailed) console.error(`FAIL ${name}\n  ${String(error.stack || error).split('\n').slice(0, 6).join('\n  ')}`);
if (realFailed.length) process.exit(1);
console.log(`p2 routes: ${TESTS.length} tests passed`);

// Mutants: each edit is a plausible regression of one guard; the suite must fail under every one.
const source = fs.readFileSync(path.join(SRC, 'p2Routes.ts'), 'utf8').replace(/from '\.\/([A-Za-z0-9]+\.ts)'/g, (_m, f) => `from '${pathToFileURL(path.join(SRC, f)).href}'`);
const MUTANTS = [
 ['adapter drops deadline_to', "deadline_from: 'deadline_from', deadline_to: 'deadline_to',\n};\nconst LIST_BACKEND_TO_NAV", "deadline_from: 'deadline_from',\n};\nconst LIST_BACKEND_TO_NAV"],
 ['adapter drops unsupported keys instead of reporting', "if (!backend) {unsupported.push(key); continue;}\n  if (typeof value !== 'string' || !value.trim() || CONTROL.test(value)) {invalid.push(key); continue;}", "if (!backend) {continue;}\n  if (typeof value !== 'string' || !value.trim() || CONTROL.test(value)) {invalid.push(key); continue;}"],
 ['set encoding without escapes', ".map(value => value.replace(/[\\\\,]/g, '\\\\$&'))", ''],
 ['KPI drill drops unmappable backend keys', "if (!nav) {unmapped.push(key); continue;}", "if (!nav) {continue;}"],
 ['KPI drill ignores card filters', "return drill(context, 'confirmations', {kpi: {id: cardId, filters: mapped.filters}});", "return drill(context, 'confirmations', {kpi: {id: cardId, filters: {}}});"],
 ['cursor history not bound to the query', "const known = store.get(queryKey(filters, sort));", "const known = [...store.values()].pop();"],
 ['cursor history ignores the current cursor', "known && known.current === cursor ? [...known.stack] : []", "known ? [...known.stack] : []"],
 ['403 mapped to read_failed', "if (httpStatus === 403) return", "if (httpStatus === 0) return"],
 ['404 on detail route not unlocated', "if (httpStatus === 404 && DETAIL_ROUTES.includes(route))", "if (httpStatus === 0 && DETAIL_ROUTES.includes(route))"],
 ['404 on list route becomes unlocated', "if (httpStatus === 404 && DETAIL_ROUTES.includes(route))", "if (httpStatus === 404)"],
 ['503 loses the retry affordance', "return {state: 'read_failed', httpStatus, retry: true,", "return {state: 'read_failed', httpStatus, retry: httpStatus !== 503,"],
 ['Back does not restore the parent', "export const p2Back = navBack;", "export const p2Back = (c: P2Context) => ({ok: true, value: c} as Result<P2Context>);"],
 ['contract -> confirmation guesses a case', "return projectId ? drill(context, 'confirmation', {selected: caseSelection(projectId, key)}) : null;", "return drill(context, 'confirmation', {selected: caseSelection(projectId ?? 'guess', key)});"],
 ['task keys are navigable', "return SOURCE_KEY.test(bare) && !OTHER_KIND.test(bare) ? bare : null;", "return SOURCE_KEY.test(bare) ? bare : null;"],
 ['gate accepts an invalid context', "return parsed.ok ? {ok: true, context: parsed.value} : {ok: false, context: parsed.value, reason: parsed.reason};", "return {ok: true, context: parsed.value};"],
 ['draft compare is order sensitive', "sort(([p], [q]) => p < q ? -1 : p > q ? 1 : 0)", "sort(() => 0)"],
 ['draft compare counts blanks', ".filter(([, v]) => typeof v === 'string' && v.trim() !== '').sort(", ".sort("],
 ['overview sends list vocabulary as case filter', "const OVERVIEW_NAV_TO_BACKEND: Readonly<Record<string, string>> = {pm: 'pm_id', execution_state: 'execution_status'};", "const OVERVIEW_NAV_TO_BACKEND: Readonly<Record<string, string>> = {pm: 'pm', execution_state: 'execution_status'};"],
];
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'p2-routes-mutants-'));
let escaped = 0;
try {
 for (const [label, from, to] of MUTANTS) {
  assert.ok(source.includes(from), `mutant anchor missing: ${label}`);
  const file = path.join(dir, `${MUTANTS.findIndex(m => m[0] === label)}.ts`);
  fs.writeFileSync(file, source.replace(from, to));
  const failed = await run(await import(pathToFileURL(file).href));
  if (!failed.length) {escaped++; console.error(`MUTANT SURVIVED: ${label}`);} else console.log(`mutant killed (${failed.length} failing): ${label}`);
 }
} finally {fs.rmSync(dir, {recursive: true, force: true});}
if (escaped) process.exit(1);
console.log(`p2 routes: ${MUTANTS.length} mutants killed`);
