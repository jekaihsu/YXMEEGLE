import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, writeFileSync, copyFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';

const srcDir = new URL('./src/', import.meta.url);
const real = await import(new URL('contractDetailView.ts', srcDir).href);

// ---- synthetic fixture mirroring backend/contract_detail.py output (07443f4c) ----
const ref = (record, version = null, table = 'tblC') => ({
 source_key: `bas/${table}/${record}`, base: 'bas', table, view: '', record_id: record, version,
 version_key: ['bas', table, record, version],
});
const unk = reason => ({state: 'unknown', reason});
const wd = () => ({state: 'withheld', reason: 'G-AMT: contract amount display is not approved'});
const st = (states, count = null) => ({states, count});
const line = (record, version, extra = {}) => ({
 section_state: st(['partial']), identity: ref(record, version), line_number: 'L-01', name: '合成明細',
 quantity: unk('quantity field unlocated'), unit: unk('unit field unlocated'),
 original_amount: wd(), current_revised_amount: wd(), revision_reason: unk('formal revision reason unlocated'), ...extra,
});
const child = (record, category = '測量') => ({
 identity: ref(record, null, 'tblW'), name: unk('work-item name unlocated'), category,
 quantity: unk('quantity field unlocated'), unit: unk('unit field unlocated'), state: unk('work-item state unlocated'),
 responsible_person: unk('responsible person unlocated'), deliverable_count: unk('deliverable population unlocated'),
});
const body = (over = {}) => ({
 page_state: st(['partial']),
 header: {
  identity: ref('c1', 3), line_number: 'L-01', name: '合成明細', section_state: st(['partial']), source: ref('c1', 3),
  parent_confirmations: [{identity: ref('k1', 1, 'tblK'), reference: 'CF-001'}], parent_state: st(['partial']),
  edge_verification: 'receipt_missing',
 },
 siblings: {state: st(['partial']), rows: [
  {identity: ref('c2', 1), line_number: 'L-02', name: '同名明細'}, {identity: ref('c3', 1), line_number: 'L-03', name: '同名明細'}]},
 main: line('c1', 3),
 work_items: {state: st(['partial'], 3), rows: [child('w1', '設計'), child('w2', '測量'), child('w3', null)],
  order: 'stable_source_id; original_source_order_unlocated', edge_verification: 'receipt_missing'},
 version_history: {state: st(['partial']), current: ref('c1', 3), effective_business_version: unk('effective-version rule unlocated'),
  historical_observations: [{kind: 'observed_source_snapshot', line: line('c1', 2), source_fields: {'備註': '合成備註'}}],
  formal_revisions: {state: st(['unlocated'])}},
 details: {section_state: st(['partial']), identity: ref('c1', 3), source_fields: {'備註': '合成備註', '分項金額(原始)': 999999},
  relationship_count: st(['partial'], 3), mapping_state: st(['unlocated']),
  warnings: ['receipt_missing', 'separate_contract_header_unlocated', 'quantity_unit_unlocated', 'formal_revision_semantics_unlocated', 'original_source_order_unlocated']},
 ...over,
});
const clone = x => structuredClone(x);
const mutated = (b, fn) => { const c = clone(b); fn(c); return c; };
const displayJson = view => JSON.stringify(view, (k, v) => (k === 'navKey' || k === 'nav' || k === 'drawer' || k === 'actions') ? undefined : v);

// ---- guards (each takes a module so it can be re-run against a mutant) ----
const guards = {
 unknownNotZero(m) {
  const v = m.buildContractDetailView(body());
  const cells = [v.main.quantity, v.main.unit, v.main.revisionReason, v.versionHistory.effectiveVersion, ...v.workItems.rows.flatMap(r => [r.name, r.quantity, r.unit, r.state, r.person, r.deliverables])];
  for (const c of cells) { assert.equal(c.kind, 'unknown'); assert.equal(c.text, '—'); assert.ok(c.reason.length > 0); }
  assert.equal(v.workItems.rows[0].deliverables.reason, '交付物母體尚未定位');
  // unknown child population is not an empty list or a 0
  const u = m.buildContractDetailView(body({work_items: {...body().work_items, state: st(['unknown']), rows: []}, details: {...body().details, relationship_count: st(['unknown'])}}));
  assert.equal(u.workItems.state.label, '狀態未知');
  assert.doesNotMatch(u.workItems.emptyMessage, /尚無資料|0/);
  assert.doesNotMatch(displayJson(v), /":0[,}]|"0"/);
 },
 amountWithheld(m) {
  const v = m.buildContractDetailView(body());
  for (const c of [v.main.originalAmount, v.main.currentRevisedAmount]) {
   assert.deepEqual(c, {kind: 'withheld', text: '未核准顯示', reason: 'G-AMT：合約金額尚未核准顯示'});
  }
  for (const o of v.versionHistory.observations) assert.equal(o.line.originalAmount.kind, 'withheld');
  const all = JSON.stringify(v);
  assert.doesNotMatch(all, /999999|分項金額/);
  assert.equal('difference' in v.main || 'total' in v.main || 'sum' in v.main, false);
  // an altered body carrying a value or a non-withheld state is malformed, whole page unknown
  for (const patch of [{state: 'withheld', reason: 'G-AMT: x', value: 123456}, {state: 'known', value: 123456}, {state: 'withheld', reason: 'x'}, 123456]) {
   const r = m.buildContractDetailView(mutated(body(), b => { b.main.original_amount = patch; }));
   assert.equal(r.kind, 'state'); assert.equal(r.main, null); assert.doesNotMatch(JSON.stringify(r), /123456/);
  }
  // amount-like drawer field from an altered body never renders
  const d = m.buildContractDetailView(mutated(body(), b => { b.details.source_fields['合約金額'] = 777777; }), {selected: 'bas/tblC/c1'});
  assert.doesNotMatch(JSON.stringify(d), /777777/);
 },
 forbiddenAbsent(m) {
  const v = m.buildContractDetailView(body(), {selected: 'bas/tblC/c1'});
  const text = JSON.stringify(v);
  assert.doesNotMatch(text.replaceAll('未核准顯示', ''), /完成|Complete|Approve|核准|SOP|送出|標記|Submit/);
  assert.deepEqual([...new Set(v.actions.map(a => a.route))].sort(), ['confirmation', 'contract', 'workitem']);
  assert.deepEqual(Object.keys(v.actions[0]).sort(), ['key', 'route']);
  assert.equal(Object.keys(v).some(k => /write|submit|approve|complete|sop/i.test(k)), false);
 },
 malformedFailClosed(m) {
  const cases = {
   notObject: null, array: [], missingSection: (() => { const b = body(); delete b.work_items; return b; })(),
   extraKey: body({leak: {amount: 5}}),
   badIdentity: mutated(body(), b => { b.work_items.rows[0].identity.source_key = 'bas/tblW/other'; }),
   badVersionKey: mutated(body(), b => { b.main.identity.version_key = ['bas', 'tblC', 'c1', 99]; }),
   mixedHistory: mutated(body(), b => { b.version_history.historical_observations[0].line.identity = ref('zzz', 1); }),
   mappedClaim: mutated(body(), b => { b.details.mapping_state = st(['partial']); }),
   verifiedClaim: mutated(body(), b => { b.work_items.edge_verification = 'verified'; }),
   quantityClaim: mutated(body(), b => { b.main.quantity = {state: 'known', value: 0}; }),
   badState: mutated(body(), b => { b.work_items.state = {states: ['complete_empty', 'partial'], count: 0}; }),
   emptyWithRows: mutated(body(), b => { b.work_items.state = st(['complete_empty']); }),
   countMismatch: mutated(body(), b => { b.work_items.state = st(['partial'], 7); }),
   dupChild: mutated(body(), b => { b.work_items.rows[1] = b.work_items.rows[0]; }),
   siblingIsSelf: mutated(body(), b => { b.siblings.rows[0].identity = ref('c1', 1); }),
   orderClaim: mutated(body(), b => { b.work_items.order = 'verified_source_order'; }),
   relationshipMismatch: mutated(body(), b => { b.details.relationship_count = st(['unknown']); }),
   unknownBadPage: {page_state: {states: ['bogus']}},
  };
  for (const [name, input] of Object.entries(cases)) {
   const v = m.buildContractDetailView(input);
   assert.equal(v.kind, 'state', name);
   assert.deepEqual(v.page.states, ['unknown'], name);
   assert.equal(v.main, null, name); assert.equal(v.workItems, null, name); assert.equal(v.drawer, null, name);
   assert.match(v.page.note, /狀態未知/, name);
  }
 },
};

const tests = [];
const test = (name, run) => tests.push([name, run]);

test('1 unknown quantity/unit/reason/children render em dash plus reason, never 0', () => guards.unknownNotZero(real));
test('2 both amounts withheld with G-AMT reason; no value, sum or difference; altered amounts fail closed', () => guards.amountWithheld(real));
test('3 no Complete/Approve/SOP write action; links are read-only navigation', () => guards.forbiddenAbsent(real));
test('4 malformed bodies fail closed to unknown (whole page, no partial trust)', () => guards.malformedFailClosed(real));

test('5 breadcrumb Confirmation -> Contract Line; missing parent is explicit, not auto-assigned', () => {
 const v = real.buildContractDetailView(body());
 assert.deepEqual(v.breadcrumb.map(c => [c.kind, c.label]), [['confirmation', 'CF-001'], ['contract', 'L-01 合成明細']]);
 assert.deepEqual(v.breadcrumb[0].nav, {route: 'confirmation', key: 'bas/tblK/k1'});
 assert.equal(v.header.edgeLabel, '對應未驗證');
 const none = real.buildContractDetailView(mutated(body(), b => { b.header.parent_confirmations = []; b.header.parent_state = st(['unlocated']); }), {selected: 'bas/tblC/c1'});
 assert.equal(none.breadcrumb[0].kind, 'unresolved');
 assert.match(none.breadcrumb[0].label, /未解析/);
 assert.ok(none.drawer.warnings.some(w => w.code === 'parent_unresolved'));
 // parent state must agree with the parents present
 assert.equal(real.buildContractDetailView(mutated(body(), b => { b.header.parent_state = st(['unlocated']); })).kind, 'state');
});

test('6 sibling directory keeps equal names as separate entries, current selected, stable key order', () => {
 const v = real.buildContractDetailView(body());
 assert.deepEqual(v.directory.entries.map(e => [e.navKey, e.selected]), [['bas/tblC/c1', true], ['bas/tblC/c2', false], ['bas/tblC/c3', false]]);
 assert.equal(v.directory.entries[1].name.text, v.directory.entries[2].name.text);
 const lone = real.buildContractDetailView(mutated(body(), b => { b.siblings = {state: st(['unknown']), rows: []}; }));
 assert.equal(lone.directory.entries.length, 1);
 assert.match(lone.directory.note, /狀態未知/);
 const unlocated = real.buildContractDetailView(mutated(body(), b => { b.siblings.rows[0].identity = null; }));
 assert.equal(unlocated.directory.entries.at(-1).unresolvedLabel, '無法定位的合約明細紀錄');
 assert.equal(unlocated.directory.entries.at(-1).nav, null);
});

test('7 main line block: number/name/version; quantity+unit unknown; revision reason unknown', () => {
 const m = real.buildContractDetailView(body()).main;
 assert.equal(m.lineNumber.text, 'L-01'); assert.equal(m.name.text, '合成明細');
 assert.equal(m.versionLabel, '來源版本 3');
 assert.equal(m.state.label, '部分資料');
 const nameless = real.buildContractDetailView(mutated(body(), b => { b.main.name = null; b.header.name = null; }));
 assert.equal(nameless.main.name.kind, 'unknown');
});

test('8 child table: stable id order with disclosure; sort by category falls back to stable id; unsortable column ignored', () => {
 const shuffled = mutated(body(), b => { b.work_items.rows.reverse(); });
 const v = real.buildContractDetailView(shuffled);
 assert.deepEqual(v.workItems.rows.map(r => r.navKey), ['bas/tblW/w1', 'bas/tblW/w2', 'bas/tblW/w3']);
 assert.match(v.workItems.orderDisclosure, /原始來源順序尚未定位/);
 assert.equal(v.workItems.edgeLabel, '對應未驗證');
 assert.deepEqual(v.workItems.columns, ['工項名稱', '類別', '數量', '單位', '狀態', '負責人', '交付物數量']);
 const asc = real.buildContractDetailView(body(), {sort: {key: 'category', dir: 'asc'}});
 const desc = real.buildContractDetailView(body(), {sort: {key: 'category', dir: 'desc'}});
 assert.deepEqual(asc.workItems.rows.map(r => r.navKey), ['bas/tblW/w2', 'bas/tblW/w1', 'bas/tblW/w3']);
 assert.deepEqual(desc.workItems.rows.map(r => r.navKey), ['bas/tblW/w1', 'bas/tblW/w2', 'bas/tblW/w3']);
 assert.equal(desc.workItems.rows[2].category.kind, 'unknown');
 const ignored = real.buildContractDetailView(body(), {sort: {key: 'quantity', dir: 'desc'}, filters: {search: 'x'}});
 assert.equal(ignored.workItems.sort, null);
 assert.equal(ignored.workItems.rows.length, 3);
});

test('9 child states: partial counted rows; complete-empty only when body says so; technical ids only in nav/drawer', () => {
 const v = real.buildContractDetailView(body());
 assert.equal(v.workItems.state.label, '部分資料（3 筆）');
 const empty = real.buildContractDetailView(mutated(body(), b => { b.work_items = {...b.work_items, state: st(['complete_empty']), rows: []}; b.details.relationship_count = st(['complete_empty']); }));
 assert.equal(empty.workItems.emptyMessage, '尚無資料');
 const shown = displayJson(v);
 for (const id of ['bas', 'tblC', 'tblW', 'c1', 'w1', 'k1']) assert.ok(!shown.includes(`"${id}"`) && !shown.includes(`/${id}`), id);
});

test('10 version history: observed snapshots labelled; formal revisions unlocated; effective version unknown', () => {
 const h = real.buildContractDetailView(body()).versionHistory;
 assert.equal(h.currentVersionLabel, '來源版本 3');
 assert.equal(h.observations[0].label, '觀測快照（非正式修訂）');
 assert.equal(h.observations[0].versionLabel, '來源版本 2');
 assert.deepEqual(h.observations[0].sourceFields, [{field: '備註', value: '合成備註'}]);
 assert.match(h.formalRevisions.label, /找不到資料來源/);
 assert.deepEqual(h.formalRevisions.states, ['unlocated']);
 assert.equal(h.effectiveVersion.kind, 'unknown');
 const none = real.buildContractDetailView(mutated(body(), b => { b.version_history.state = st(['unknown']); b.version_history.historical_observations = []; }));
 assert.equal(none.versionHistory.observations.length, 0);
 assert.equal(none.versionHistory.state.label, '狀態未知');
 assert.equal(real.buildContractDetailView(mutated(body(), b => { b.version_history.formal_revisions = {state: st(['partial'])}; })).kind, 'state');
});

test('11 drawer is selection-only: null by default, contract line or listed child when selected, else null', () => {
 assert.equal(real.buildContractDetailView(body()).drawer, null);
 const d = real.buildContractDetailView(body(), {selected: 'bas/tblC/c1'}).drawer;
 assert.equal(d.kind, 'contract_line');
 assert.deepEqual([d.identity.base, d.identity.table, d.identity.recordId, d.identity.version], ['bas', 'tblC', 'c1', '3']);
 assert.deepEqual(d.mapping.states, ['unlocated']);
 assert.equal(d.edgeVerification, '對應未驗證');
 assert.ok(d.warnings.every(w => w.label.length > 0));
 assert.ok(d.warnings.some(w => w.code === 'original_source_order_unlocated'));
 assert.equal(d.relationship.label, '部分資料（3 筆）');
 assert.deepEqual(d.sourceFields, [{field: '備註', value: '合成備註'}]);
 assert.equal(real.buildContractDetailView(body(), {selected: 'bas/tblW/w2'}).drawer.kind, 'work_item');
 // absent / hidden / sibling keys open nothing and echo nothing
 for (const key of ['bas/tblW/hidden', 'bas/tblC/c2', '', 7, null]) {
  const v = real.buildContractDetailView(body(), {selected: key});
  assert.equal(v.drawer, null);
 }
 assert.doesNotMatch(JSON.stringify(real.buildContractDetailView(body(), {selected: 'bas/tblW/hidden'})), /hidden/);
});

test('12 receipt_missing always surfaces as 對應未驗證 even if the warnings list omits it', () => {
 const v = real.buildContractDetailView(mutated(body(), b => { b.details.warnings = []; }), {selected: 'bas/tblC/c1'});
 assert.ok(v.drawer.warnings.some(w => w.code === 'receipt_missing' && /對應未驗證/.test(w.label)));
 assert.ok(v.summary.warnings.some(w => w.code === 'receipt_missing'));
 // unknown warning codes are generic, never echoed as copy
 const w = real.buildContractDetailView(mutated(body(), b => { b.details.warnings.push('totally_new'); }), {selected: 'bas/tblC/c1'});
 assert.equal(w.drawer.warnings.find(x => x.code === 'totally_new').label, '未列於已知清單的警示');
});

test('13 page states: forbidden exposes nothing; unlocated/loading/read_failed/unknown are text states; stale is a retained-snapshot note', () => {
 const f = real.buildContractDetailView({page_state: {states: ['forbidden']}, header: {name: 'SECRET'}, main: line('c1', 1)});
 assert.deepEqual(f.page.states, ['forbidden']); assert.doesNotMatch(JSON.stringify(f), /SECRET|c1/);
 assert.equal(f.page.label, '沒有權限');
 for (const [s, label] of [['unlocated', '找不到資料來源'], ['loading', '讀取中'], ['read_failed', '讀取失敗'], ['unknown', '狀態未知']]) {
  const v = real.buildContractDetailView({page_state: st([s])});
  assert.equal(v.kind, 'state'); assert.equal(v.page.label, label);
 }
 assert.equal(real.buildContractDetailView({page_state: st(['unlocated'])}).page.note, '找不到此合約明細');
 // a state-only page may not smuggle sections
 assert.equal(real.buildContractDetailView({page_state: st(['unlocated']), main: line('c1', 1)}).page.reason?.startsWith('malformed'), true);
 const stale = real.buildContractDetailView(mutated(body(), b => { b.page_state = st(['partial', 'stale']); }));
 assert.deepEqual(stale.page.states, ['partial', 'stale']);
 assert.match(stale.page.note, /保留快照/);
 assert.ok(stale.summary.warnings.some(w => w.code === 'retained_source_missing'));
 assert.equal(stale.header.sourceUpdated.kind, 'unknown');
});

test('14 duplicate case/line numbers and names across contracts stay separate; same key listed twice is malformed', () => {
 const dup = mutated(body(), b => { b.siblings.rows[0].line_number = 'L-01'; b.siblings.rows[0].name = '合成明細'; });
 const v = real.buildContractDetailView(dup);
 assert.equal(v.directory.entries.filter(e => e.name.text === '合成明細').length, 2);
 assert.equal(real.buildContractDetailView(mutated(body(), b => { b.siblings.rows[1].identity = b.siblings.rows[0].identity; })).kind, 'state');
});

test('15 input is not mutated and the view is JSON-safe', () => {
 const b = body(); const before = JSON.stringify(b);
 real.buildContractDetailView(b, {selected: 'bas/tblC/c1', sort: {key: 'category', dir: 'asc'}});
 assert.equal(JSON.stringify(b), before);
 JSON.parse(JSON.stringify(real.buildContractDetailView(b)));
});

// ---- mutation checks: each guard must fail against a deliberately broken copy ----
const dir = mkdtempSync(join(tmpdir(), 'contract-detail-mut-'));
copyFileSync(new URL('dataState.ts', srcDir), join(dir, 'dataState.ts'));
const source = readFileSync(new URL('contractDetailView.ts', srcDir), 'utf8');
let n = 0;
async function mutant(from, to) {
 assert.ok(source.includes(from), `mutation anchor missing: ${from}`);
 const file = join(dir, `contractDetailView${n++}.ts`);
 writeFileSync(file, source.replace(from, to));
 return import(pathToFileURL(file).href);
}
const mutations = [
 ['M1 unknown rendered as 0 -> unknown-not-zero guard', 'unknownNotZero',
  "const unknownCell = (reason: string): Cell => ({kind: 'unknown', text: '—', reason});",
  "const unknownCell = (reason: string): Cell => ({kind: 'text', text: '0', reason} as never);"],
 ['M2 withheld amount rendered as a number -> amount guard', 'amountWithheld',
  "return {kind: 'withheld', text: CONTRACT_LABELS.withheld, reason: CONTRACT_LABELS.withheldReason};",
  "return {kind: 'withheld', text: '0' as never, reason: CONTRACT_LABELS.withheldReason};"],
 ['M2b amount strictness removed (extra keys trusted) -> amount guard', 'amountWithheld',
  "const o = rec(v, ['state', 'reason'], path);\n if (o.state !== 'withheld'",
  "const o = v as Record<string, unknown>;\n if (o.state !== 'withheld'"],
 ['M3 write action added -> forbidden-absent guard', 'forbiddenAbsent',
  "const actions: NavTarget[] = [",
  "const actions: NavTarget[] = [{route: 'workitem', key: '完成'} as NavTarget, "],
 ['M3b approve label leaks into warnings -> forbidden-absent guard', 'forbiddenAbsent',
  "receipt_missing: '對應未驗證（尚無對應收據）',", "receipt_missing: '對應未驗證（尚無對應收據）；可核准',"],
 ['M4 malformed body partially trusted -> fail-closed guard', 'malformedFailClosed',
  "if (o.source_key !== `${base}/${table}/${recordId}` || typeof o.view !== 'string') return bad(path);", "if (typeof o.view !== 'string') return bad(path);"],
 ['M4b extra keys tolerated -> fail-closed guard', 'malformedFailClosed',
  "if (own.length !== keys.length || !keys.every(key => Object.hasOwn(v, key))) return bad(path);", "if (!keys.every(key => Object.hasOwn(v, key))) return bad(path);"],
 ['M4c mapping claim trusted -> fail-closed guard', 'malformedFailClosed',
  "if (mapping.states.length !== 1 || mapping.states[0] !== 'unlocated') bad('details.mapping_state');", ""],
];
for (const [name, guard, from, to] of mutations) {
 test(`mutation ${name} fails the guard`, async () => {
  const m = await mutant(from, to);
  assert.throws(() => guards[guard](m), undefined, `${name} must make ${guard} fail`);
 });
}

let failed = 0;
for (const [name, run] of tests) {
 try { await run(); console.log(`ok - ${name}`); } catch (error) { failed++; console.error(`not ok - ${name}\n${error.stack}`); }
}
rmSync(dir, {recursive: true, force: true});
if (failed) { console.error(`${failed} failed`); process.exit(1); }
console.log(`${tests.length} tests passed`);
