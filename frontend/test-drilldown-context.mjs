// P2-NAV drilldown/return-context (pure logic, Node type stripping). Synthetic fixtures only.
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const mi = process.argv.indexOf('--mutant');
const SRC = mi > 0 ? process.argv[mi + 1] : resolve('src/drilldownContext.ts');
const ONLY = process.env.DRILL_ONLY ? process.env.DRILL_ONLY.split(',') : null;
const load = async (path) => import(pathToFileURL(path).href);
const M = await load(SRC);
const {P2_ROUTES, defaultContext, encodeContext, decodeContext, parseHash, hashFor, drill, back, backTo, breadcrumbs, linkOut, sameFilterSet, validateContext, LIMITS} = M;

let checks = 0;
const eq = (a, b, m) => { assert.deepEqual(a, b, m); checks++; };
const ok = (v, m) => { assert.ok(v, m); checks++; };
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const base = (route, extra = {}) => ({...defaultContext(route), ...extra});
const rich = {
  overview: base('overview', {filters: {pm: 'pm-a', execution_state: 'blocked'}, period: {start: '2026-10-05', end: '2026-10-11'}, selected: 'row:一', columns: ['case_no', 'pm'], sort: {key: 'due', dir: 'desc'}, cursor: 'c_AbC-1.2='}),
  confirmations: base('confirmations', {filters: {search: '測試 case', source_version: 'v4', admission: 'open', deadline_from: '2026-01-01'}, sort: {key: 'case_no', dir: 'asc'}, cursor: 'opaque~cursor/with+chars==', columns: ['case_no', 'title', 'version'], selected: 'srcA:rec001'}),
  confirmation: base('confirmation', {selected: 'srcA:rec001', cursor: null}),
  contract: base('contract', {selected: 'srcA:line9', columns: ['unit']}),
  workitem: base('workitem', {selected: 'srcA:wi3'}),
};
const unwrap = r => { assert.ok(r.ok, `expected ok, got ${r.reason}`); return r.value; };
const flip = (enc, fn) => { // tamper with decoded JSON, re-encode non-canonically-safe
  const j = JSON.parse(Buffer.from(enc, 'base64url').toString('utf8')); fn(j);
  return Buffer.from(JSON.stringify(j), 'utf8').toString('base64url');
};
const reasonOf = (enc, route) => { const r = decodeContext(enc, route); ok(!r.ok, 'must be rejected'); eq(r.value, defaultContext(route), 'safe default'); return r.reason; };

test('1. round-trip is exact for every P2 route (hash and ctx)', () => {
  for (const r of P2_ROUTES) {
    const c = rich[r], enc = unwrap(encodeContext(c));
    eq(unwrap(decodeContext(enc, r)), c, `ctx ${r}`);
    eq(unwrap(parseHash(unwrap(hashFor(c)))), c, `hash ${r}`);
    eq(unwrap(encodeContext(unwrap(decodeContext(enc, r)))), enc, `stable ${r}`);
  }
  eq(unwrap(parseHash('view=confirmations')), defaultContext('confirmations'), 'bare hash is default');
});

const l1 = () => drill(rich.overview, 'confirmations', {kpi: {id: 'blocked_cases', filters: {execution_state: 'blocked', pm: 'pm-a'}}, columns: ['case_no']});
test('2. back after 3-level drilldown restores each level exactly; breadcrumbs follow', () => {
  const a = rich.overview;
  const b0 = unwrap(l1());
  const b = {...b0, cursor: 'page2', sort: {key: 'case_no', dir: 'desc'}, selected: 'srcA:rec001'};          // user paged/sorted in 129
  const c0 = unwrap(drill(b, 'confirmation', {selected: 'srcA:rec001'}));
  const c = {...c0, selected: 'srcA:line9'};
  const d = unwrap(drill(c, 'contract', {selected: 'srcA:line9'}));
  const e = unwrap(drill(d, 'workitem', {selected: 'srcA:wi3'}));
  eq(breadcrumbs(e).map(x => x.issue), [128, 129, 130, 131, 132], 'breadcrumb chain');
  const d2 = unwrap(back(e)); eq(d2, d, 'workitem -> contract');
  const c2 = unwrap(back(d2)); eq(c2, c, 'contract -> confirmation');
  const b2 = unwrap(back(c2)); eq(b2, b, '130 -> 129 keeps cursor/sort/columns/selection');
  const a2 = unwrap(back(b2)); eq(a2, a, '129 -> 128 keeps filters, period, sort, cursor');
  eq(unwrap(backTo(e, 1)), b, 'breadcrumb jump to level 1');
  // both directions: forward again from restored state gives the same result
  eq(unwrap(drill(unwrap(back(c2)), 'confirmation', {selected: 'srcA:rec001'})), c0, 'drill after back is deterministic');
  eq(back(a2).reason, 'no_parent');
});

test('3. restored context survives the hash round trip at every depth', () => {
  let s = unwrap(l1()); s = unwrap(drill({...s, cursor: 'pg7'}, 'confirmation', {selected: 'k'}));
  s = unwrap(drill(s, 'workitem', {selected: 'w'}));
  const viaUrl = unwrap(parseHash(unwrap(hashFor(s))));
  eq(viaUrl, s);
  eq(unwrap(back(unwrap(back(viaUrl)))).cursor, 'pg7', 'cursor survives');
});

test('4. tampered / oversized / unknown-version / wrong-route contexts are rejected to a safe default', () => {
  const enc = unwrap(encodeContext(rich.confirmations));
  eq(reasonOf(flip(enc, j => { j.v = 2; }), 'confirmations'), 'unknown_version');
  eq(reasonOf(flip(enc, j => { j.extra = 1; }), 'confirmations'), 'unknown_key');
  eq(reasonOf(flip(enc, j => { j.filters.pm = 5; }), 'confirmations'), 'bad_filter');
  eq(reasonOf(flip(enc, j => { j.filters.color = 'x'; }), 'confirmations'), 'unknown_key');
  eq(reasonOf(flip(enc, j => { j.sort = {key: 'Bad Key', dir: 'asc'}; }), 'confirmations'), 'bad_sort');
  eq(reasonOf(flip(enc, j => { j.sort.dir = 'up'; }), 'confirmations'), 'bad_sort');
  eq(reasonOf(flip(enc, j => { j.cursor = 'has space'; }), 'confirmations'), 'bad_cursor');
  eq(reasonOf(flip(enc, j => { j.columns = ['a', 'a']; }), 'confirmations'), 'bad_columns');
  eq(reasonOf(flip(enc, j => { j.selected = 'a\u0000b'; }), 'confirmations'), 'bad_selected');
  eq(reasonOf(enc, 'contract'), 'wrong_route');
  eq(reasonOf('%%%', 'overview'), 'bad_encoding');
  eq(reasonOf(Buffer.from('{not json', 'utf8').toString('base64url'), 'overview'), 'bad_json');
  eq(reasonOf('A'.repeat(LIMITS.encodedLen + 1), 'overview'), 'oversize');
  eq(decodeContext(42, 'overview').reason, 'not_string');
  eq(reasonOf(flip(enc, j => { j.stack = [{route: 'overview'}]; }), 'confirmations'), 'bad_stack');
  eq(reasonOf(flip(enc, j => { j.stack = [{...j, route: 'workitem', filters: {}, stack: undefined}]; }), 'confirmations'), 'bad_stack');
  eq(parseHash('view=nonsense&ctx=x').reason, 'bad_route');
  // non-canonical (reordered keys) encodings are refused
  const reordered = Buffer.from(JSON.stringify(Object.fromEntries(Object.entries(JSON.parse(Buffer.from(enc, 'base64url').toString())).reverse())), 'utf8').toString('base64url');
  eq(reasonOf(reordered, 'confirmations'), 'bad_encoding');
  // oversize on encode: refused, never truncated
  const huge = base('confirmations', {columns: Array.from({length: 30}, (_, i) => `col_${i}_${'x'.repeat(30)}`.slice(0, 40)), filters: Object.fromEntries(['search', 'source_version', 'pm', 'admission', 'deadline_from', 'deadline_to', 'execution_state', 'stage'].map(k => [k, '測'.repeat(200)]))});
  const r = encodeContext(huge); ok(!r.ok && r.reason === 'oversize', 'oversize encode refused');
  ok(!validateContext({...defaultContext('overview'), stack: new Array(7).fill(emptyFrame())}).ok, 'stack depth bound');
});
function emptyFrame() { return M.emptyFrame('overview'); }

test('5. KPI drilldown carries exactly the KPI filter set (no extra, no missing)', () => {
  const kpiFilters = {execution_state: 'blocked', pm: 'pm-a'};
  const ov = base('overview', {filters: {pm: 'pm-a', execution_state: 'blocked'}, selected: 'ignored'});
  const to = unwrap(drill(ov, 'confirmations', {kpi: {id: 'blocked_cases', filters: kpiFilters}}));
  ok(sameFilterSet(to.filters, kpiFilters), 'identical set');
  eq(Object.keys(to.filters).sort(), Object.keys(kpiFilters).sort());
  eq(to.kpi, 'blocked_cases');
  // a KPI narrower than the overview filter does not inherit overview filters
  const narrow = unwrap(drill(ov, 'confirmations', {kpi: {id: 'all_open', filters: {}}}));
  eq(narrow.filters, {}, 'no extra filter inherited');
  // unrepresentable KPI filter is refused, not silently dropped
  eq(drill(ov, 'confirmations', {kpi: {id: 'x', filters: {color: 'red'}}}).reason, 'kpi_filter_not_representable');
  eq(drill(ov, 'confirmations', {kpi: {id: 'x', filters: kpiFilters}, filters: {pm: 'pm-a'}}).reason, 'kpi_filter_conflict');
  eq(drill(ov, 'confirmation', {kpi: {id: 'x', filters: {}}}).reason, 'bad_kpi');
  // after hash round trip + back/forward the set is still identical
  const rt = unwrap(parseHash(unwrap(hashFor(to))));
  ok(sameFilterSet(rt.filters, kpiFilters));
  ok(sameFilterSet(unwrap(back(rt)).filters, ov.filters), 'overview filters restored');
});

test('6. period control never leaks into case filters or other routes', () => {
  const ov = base('overview', {period: {start: '2026-10-05', end: '2026-10-11'}, filters: {pm: 'pm-a'}});
  const to = unwrap(drill(ov, 'confirmations', {kpi: {id: 'k', filters: {pm: 'pm-a'}}}));
  eq(to.period, null); ok(!JSON.stringify(to.filters).includes('2026-10'), 'no period in filters');
  eq(unwrap(back(to)).period, ov.period, 'period restored on return');
  ok(!validateContext({...rich.confirmations, period: {start: '2026-10-05', end: '2026-10-11'}}).ok, 'period rejected on 129');
  eq(decodeContext(flip(unwrap(encodeContext(rich.confirmations)), j => { j.period = {start: '2026-10-05', end: '2026-10-11'}; }), 'confirmations').reason, 'period_not_allowed');
  eq(decodeContext(flip(unwrap(encodeContext(rich.overview)), j => { j.filters.period = '2026-10-05'; }), 'overview').reason, 'unknown_key', 'period as filter key rejected');
  eq(decodeContext(flip(unwrap(encodeContext(rich.overview)), j => { j.period = {start: '2026-10-11', end: '2026-10-05'}; }), 'overview').reason, 'bad_period');
  eq(decodeContext(flip(unwrap(encodeContext(rich.overview)), j => { j.period = {start: '2026-02-30', end: '2026-03-01'}; }), 'overview').reason, 'bad_period');
});

test('7. cursor is opaque: preserved byte for byte, never decoded, not carried across routes', () => {
  const cur = 'eyJvZmZzZXQiOjk5fQ==';   // looks like base64 JSON; must not be interpreted
  const c = base('confirmations', {cursor: cur});
  eq(unwrap(parseHash(unwrap(hashFor(c)))).cursor, cur);
  const child = unwrap(drill(c, 'confirmation', {selected: 'k'}));
  eq(child.cursor, null, 'child has no inherited cursor');
  eq(unwrap(back(child)).cursor, cur, 'cursor restored verbatim');
  ok(!validateContext({...c, cursor: 'x'.repeat(LIMITS.cursorLen + 1)}).ok, 'cursor bound');
  ok(!validateContext({...c, cursor: 'a\nb'}).ok);
});

test('8. no amount / hidden-id keys are accepted anywhere in the context', () => {
  for (const k of ['amount', 'original_amount', 'revised_amount', 'sum', 'total', 'hidden_id', 'record_id_hidden', 'forbidden_count', '金額']) {
    for (const r of ['overview', 'confirmations']) {
      const enc = unwrap(encodeContext(rich[r]));
      eq(decodeContext(flip(enc, j => { j.filters[k] = '1'; }), r).reason, 'unknown_key', `${k} in filters`);
      eq(decodeContext(flip(enc, j => { j[k] = 1; }), r).reason, 'unknown_key', `${k} top-level`);
    }
    const enc = unwrap(encodeContext(rich.contract));
    eq(decodeContext(flip(enc, j => { j.filters[k] = '1'; }), 'contract').reason, 'unknown_key', `${k} on contract`);
    eq(decodeContext(flip(enc, j => { j.stack = [{...j, route: 'confirmation', stack: undefined, [k]: 1}]; }), 'contract').reason, 'bad_stack', `${k} in stack`);
  }
  const hash = unwrap(hashFor(unwrap(drill(rich.confirmation, 'contract', {selected: 'srcA:line9'}))));
  ok(!/amount|金額/i.test(Buffer.from(hash.split('ctx=')[1], 'base64url').toString()), 'encoded payload has no amount key');
});

test('9. drill edges: only declared P2 transitions; link-only targets validated', () => {
  eq(drill(rich.confirmations, 'contract').reason, 'edge_not_allowed');
  eq(drill(rich.overview, 'workitem').reason, 'edge_not_allowed');
  ok(drill(rich.confirmation, 'workitem').ok && drill(rich.contract, 'workitem').ok && drill(rich.workitem, 'contract').ok);
  eq(linkOut('sources'), {ok: true, hash: 'view=sources'});
  eq(linkOut('entry_point', '/#view=project&project=p1&tab=flow'), {ok: true, hash: 'view=project&project=p1&tab=flow'});
  eq(linkOut('entry_point', 'https://evil.example/#view=x').reason, 'bad_link');
  eq(linkOut('entry_point', '/#view=project&x=a b').reason, 'bad_link');
});

test('10. drill/back never alias caller objects (later edits cannot change a stored parent)', () => {
  const from = base('confirmations', {filters: {pm: 'pm-a'}, columns: ['a', 'b'], selected: 'k'});
  const child = unwrap(drill(from, 'confirmation', {selected: 'k'}));
  from.filters.pm = 'changed'; from.columns.push('z');
  const restored = unwrap(back(child));
  eq(restored.filters, {pm: 'pm-a'}); eq(restored.columns, ['a', 'b']);
  restored.filters.pm = 'x';
  eq(unwrap(back(child)).filters, {pm: 'pm-a'}, 'second back unaffected');
});

test('11. corrupt return frame is refused at back()', () => {
  const child = unwrap(drill(rich.overview, 'confirmations', {kpi: {id: 'k', filters: {pm: 'pm-a'}}}));
  const bad = {...child, stack: [{...child.stack[0], sort: {key: 'BAD', dir: 'asc'}}]};
  eq(back(bad).reason, 'corrupt_return_frame');
  const wrongParent = {...child, route: 'contract', filters: {}, kpi: null, stack: [child.stack[0]]};
  eq(back(wrongParent).reason, 'corrupt_return_frame', 'overview is not a valid parent of contract');
});

test('12. hash envelope: unknown or duplicated parameters reject the whole hash to the safe default', () => {
  const c = base('confirmations', {filters: {pm: 'pm-a'}, cursor: 'opaque'});
  const good = unwrap(hashFor(c)), ctx = good.split('ctx=')[1], other = unwrap(encodeContext(rich.confirmations));
  eq(unwrap(parseHash(good)), c, 'valid hash still applies');
  eq(unwrap(parseHash('#/' + good)), c, 'leading # accepted');
  const rejected = (h, reason) => {
    const r = parseHash(h); ok(!r.ok, `must reject ${h.slice(0, 40)}`);
    eq(r.reason, reason, h.slice(0, 40)); eq(r.value, defaultContext(r.value.route), 'safe default');
    ok(Object.keys(r.value.filters).length === 0 && r.value.cursor === null, 'nothing partially applied');
  };
  for (const k of ['hidden_id', 'amount', '金額', 'foo', 'View', 'ctx2']) rejected(`${good}&${k}=1`, 'unknown_param');
  rejected(`${good}&hidden_id=restricted&amount=123`, 'unknown_param');
  rejected(`amount=1&${good}`, 'unknown_param');
  rejected('view=confirmations&amount=1', 'unknown_param');   // bare view plus unknown key
  rejected(`${good}&ctx=bogus`, 'duplicate_param');
  rejected(`${good}&ctx=${ctx}`, 'duplicate_param');
  rejected(`view=contract&${good}`, 'duplicate_param');
  rejected(`${good}&vie%77=contract`, 'duplicate_param');   // percent-encoded alias of view
  rejected(`${good}&view=confirmations`, 'duplicate_param');
  rejected(`${good}&%61mount=1`, 'unknown_param');
  eq(parseHash(`view=confirmations&ctx=${other}`).ok, true, 'control: exactly view+ctx ok');
});

// ---- runner + mutation checks --------------------------------------------
let failed = 0;
for (const [name, fn] of tests) {
  if (ONLY && !ONLY.includes(name.split('.')[0])) continue;
  try { await fn(); if (!ONLY) console.log('ok  ', name); } catch (e) { failed++; if (!ONLY) console.error('FAIL', name, '\n', e.message); }
}
if (ONLY) process.exit(failed ? 1 : 0); // mutant child: non-zero means the mutation was caught

// Mutation checks: break one guard in a copy of the module, re-run the matching tests against it; they must fail.
const original = readFileSync(SRC, 'utf8');
const dir = mkdtempSync(join(tmpdir(), 'drill-mut-'));
writeFileSync(join(dir, 'integrationRoutes.ts'), readFileSync(resolve('src/integrationRoutes.ts'), 'utf8').replace("'./myWorkView.ts'", JSON.stringify(pathToFileURL(resolve('src/myWorkView.ts')).href)));
const mutate = async (label, from, to, expectTests) => {
  assert.ok(original.includes(from), `mutation anchor missing: ${label}`);
  const p = join(dir, `m_${label}.ts`); writeFileSync(p, original.replace(from, to));
  const {execFileSync} = await import('node:child_process');
  let failedUnderMutation = false;
  try { execFileSync(process.execPath, [new URL(import.meta.url).pathname, '--mutant', p], {stdio: 'pipe', env: {...process.env, DRILL_ONLY: expectTests.join(',')}}); }
  catch { failedUnderMutation = true; }
  assert.ok(failedUnderMutation, `mutation ${label} survived (tests ${expectTests} still pass)`);
  console.log(`mut ok: ${label} -> tests ${expectTests.join(',')} fail`);
  checks++;
};
{
  await mutate('unknown_key_filters', "if (!FILTER_KEYS[r].includes(k)) return {reason: 'unknown_key'};", '', ['4', '8']);
  await mutate('unknown_key_toplevel', "if (!onlyKeys(x, FRAME_KEYS)) return {reason: 'unknown_key'};", '', ['4', '8']);
  await mutate('version_check', 'if (x.v !== CONTEXT_VERSION) return bad', 'if (false) return bad', ['4']);
  await mutate('period_scope', "if (r !== 'overview') return {reason: 'period_not_allowed'};", '', ['6']);
  await mutate('kpi_drop_guard', "if (!Object.keys(target.kpi.filters).every(k => FILTER_KEYS.confirmations.includes(k))) return {ok: false, reason: 'kpi_filter_not_representable', value: f.value};", '', ['5']);
  await mutate('kpi_exact_set', 'filters = target.kpi.filters;', 'filters = {...f.value.filters, ...target.kpi.filters};', ['5']);
  await mutate('back_exact_restore', 'return {ok: true, value: {v: 1, ...clone(parent), stack: clone(stack.slice(0, -1) as Frame[])}};', 'return {ok: true, value: {v: 1, ...clone(parent), cursor: null, stack: clone(stack.slice(0, -1) as Frame[])}};', ['2', '7']);
  await mutate('stack_edge_chain', "if (!EDGES[chain[i - 1]].includes(chain[i])) return bad('bad_stack');", '', ['4', '11']);
  await mutate('stack_frame_validation', "if ('reason' in p) return bad('bad_stack');", '', ['11']);
  await mutate('drill_cursor_reset', 'sort: target.sort ?? null, cursor: null,', 'sort: target.sort ?? null, cursor: f.value.cursor,', ['7']);
  // Aliasing is prevented in depth (validateContext rebuilds every object, clone() copies again), so no single-line mutation breaks test 10; it stays as a behavior check.
  await mutate('canonical_check', "if (encodeContext(v.value).value !== encoded) return safe('bad_encoding');", '', ['4']);
  await mutate('hash_unknown_param', "if (!['view', 'ctx'].includes(k)) return {ok: false, reason: 'unknown_param', value: defaultContext('overview')};", '', ['12']);
  await mutate('hash_duplicate_param', "if (p.getAll(k).length > 1) return {ok: false, reason: 'duplicate_param', value: defaultContext('overview')};", '', ['12']);
  await mutate('oversize_bound', 'if (out.length > LIMITS.encodedLen) return', 'if (false) return', ['4']);
}
if (failed) { console.error(`${failed} FAILED`); process.exit(1); }
console.log(`drilldown-context: ${tests.length} tests, ${checks} checks passed`);
