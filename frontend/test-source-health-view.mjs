import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, writeFileSync, rmSync, copyFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';

const moduleUrl = process.env.SOURCE_HEALTH_MODULE || new URL('./src/sourceHealthView.ts', import.meta.url).href;
const {buildSourceHealthView: build} = await import(moduleUrl);
const options = {diagnosticCapability: true};
const iso = day => `2026-10-${String(day).padStart(2, '0')}T00:00:00Z`;
const healthy = (key, extra = {}) => ({key, name: key, authorized: true, health: 'healthy', ...extra});
const problem = (key, states, extra = {}) => healthy(key, {data_state: {states, count: null}, ...extra});
const input = sources => ({page_state: {states: ['partial', 'stale'], count: 15, name: 'SECRET_PAGE_NAME'}, sources});
const view = (sources, extra = {}) => build(input(sources), {...options, ...extra}).diagnostic;
const keys = result => result.rows.map(row => row.key);
const tests = [];
const test = (name, run) => tests.push([name, run]);

test('1 attention-first; asc/desc/clear and stable source key; no retrieval fallback', () => {
 const sources = [healthy('healthy', {name: 'A', last_attempt: iso(1), source_updated: iso(1)}),
  ...['read_failed', 'unlocated', 'partial', 'stale', 'unknown'].map((s, i) => problem(s, [s], {name: 'Z', last_attempt: iso(i + 2), source_updated: iso(12 - i)})),
  problem('blocked', ['forbidden'], {name: 'secret'})];
 assert.deepEqual(keys(view(sources, {sort: {column: 'name', direction: 'asc'}})), ['partial', 'read_failed', 'stale', 'unknown', 'unlocated', 'healthy']);
 assert.deepEqual(keys(view(sources, {sort: {column: 'source_updated', direction: 'desc'}})), ['read_failed', 'unlocated', 'partial', 'stale', 'unknown', 'healthy']);
 assert.deepEqual(keys(view(sources, {sort: {column: 'source_updated', direction: 'asc'}})), ['unknown', 'stale', 'partial', 'unlocated', 'read_failed', 'healthy']);
 assert.deepEqual(keys(view(sources, {sort: {column: 'last_attempt', direction: 'clear'}})), ['partial', 'read_failed', 'stale', 'unknown', 'unlocated', 'healthy']);
 const opposite = [healthy('a', {last_attempt: iso(12), source_updated: iso(1)}), healthy('b', {last_attempt: iso(1), source_updated: iso(12)})];
 assert.deepEqual(keys(view(opposite, {sort: {column: 'source_updated', direction: 'asc'}})), ['a', 'b']);
 assert.deepEqual(keys(view(opposite, {sort: {column: 'last_attempt', direction: 'asc'}})), ['b', 'a']);
 assert.deepEqual(keys(view([healthy('b', {last_attempt: iso(1)}), healthy('a', {last_attempt: iso(12)})], {sort: {column: 'source_updated', direction: 'desc'}})), ['a', 'b']);
 assert.deepEqual(keys(view([healthy('a'), healthy('z', {located: false})])), ['z', 'a']);
});

test('2 three independent timestamps; summary oldest relevant success or unknown', () => {
 const sources = [healthy('a', {last_attempt: iso(12), last_success: iso(5), source_updated: iso(1)}), healthy('b', {last_attempt: iso(13), last_success: iso(3)}), healthy('irrelevant', {relevant: false})];
 const result = view(sources);
 assert.deepEqual([result.rows[0].last_attempt.value, result.rows[0].last_success.value, result.rows[0].source_updated.value], [iso(12), iso(5), iso(1)]);
 assert.deepEqual(result.rows[1].source_updated, {value: null, label: '狀態未知'});
 assert.equal(result.summary.last_success.value, iso(3));
 assert.equal(view([...sources, healthy('older-irrelevant', {relevant: false, last_success: iso(1)})]).summary.last_success.value, iso(3));
 assert.equal(view([...sources, healthy('missing', {last_attempt: iso(13)})]).summary.last_success.value, null);
 assert.equal(view([]).summary.last_success.value, null);
 assert.equal(view([healthy('a', {last_success: iso(5)}), {authorized: true}]).summary.last_success.value, null);
 assert.equal(view([healthy('a', {last_success: iso(5)}), healthy('duplicate'), healthy('duplicate')]).summary.last_success.value, null);
 assert.equal(view([healthy('offset', {last_success: '2026-10-03T01:00:00+08:00'}), healthy('utc', {last_success: iso(3)})]).summary.last_success.value, '2026-10-03T01:00:00+08:00');
});

test('3 distinct stages; caller receipts never authoritative; definitions never success counts', () => {
 const receipt = {source_key: 'a', reference: 'synthetic-receipt'};
 const absent = view([healthy('a', {located: true, readable: false, presented: true, mapped: true, accepted: true, configured_definition_count: 37})]).rows[0];
 assert.deepEqual([absent.located, absent.readable, absent.mapped, absent.presented, absent.accepted, absent.mappingLabel], [true, false, false, true, false, '對應未驗證']);
 assert.deepEqual(absent.counts, {whole_table: null, view: null, loaded: null, excluded: null});
 assert.deepEqual(view([healthy('definitions-only', {configured_definition_count: 37})]).rows[0].counts,
  {whole_table: null, view: null, loaded: null, excluded: null});
 const present = view([healthy('a', {mapped: true, accepted: true, receipt, fields: [{field_id: 'f', yx_mapping: 'binding', receipt}]})]).rows[0];
 assert.deepEqual([present.mapped, present.accepted, present.receiptReference, present.fields[0].yxMapping], [false, false, null, null]);
 const wrong = view([healthy('b', {mapped: true, accepted: true, receipt, fields: [{yx_mapping: 'binding', receipt}]})]).rows[0];
 assert.deepEqual([wrong.mapped, wrong.accepted, wrong.fields[0].yxMapping, wrong.fields[0].mappingLabel], [false, false, null, '對應未驗證']);
 assert.deepEqual([present.mappingLabel, present.fields[0].mappingLabel], ['對應未驗證', '對應未驗證']);
 assert.equal(view([healthy('a', {receipt, mapped: false, accepted: true})]).rows[0].accepted, false);
});

test('4 partial and stale independent and coexisting', () => {
 const rows = view([problem('both', ['stale', 'partial']), problem('partial', ['partial']), problem('stale', ['stale'])]).rows;
 assert.deepEqual(rows.map(row => [row.key, row.partial, row.stale, row.statusLabel]), [
  ['both', true, true, '部分資料・資料待更新'], ['partial', true, false, '部分資料'], ['stale', false, true, '資料待更新']]);
});

test('5 viewer split; forbidden omitted from every output; search cannot alter summary', () => {
 const forbidden = problem('SECRET_KEY', ['forbidden'], {name: 'SECRET_NAME', base_id: 'SECRET_BASE', loaded_count: 991, last_success: iso(1), fields: [{field_id: 'SECRET_FIELD'}], retry_handle: 'SECRET_HANDLE', read_authorized: true});
 const sources = [healthy('a', {last_success: iso(5), loaded_count: 7, base_id: 'base'}), forbidden];
 assert.deepEqual(build(input(sources), {diagnosticCapability: false}), {page: {states: ['partial', 'stale'], statusLabel: '部分資料・資料待更新', explanation: '目前只顯示部分資料，請確認既有來源的讀取狀態。 目前資料待更新，請確認最近成功讀取時間。'}, diagnostic: null});
 assert.equal(build(input(sources), {diagnosticCapability: 'true'}).diagnostic, null);
 const diagnostic = view(sources, {selectedKey: 'SECRET_KEY'});
 assert.deepEqual(keys(diagnostic), ['a']);
 assert.equal(diagnostic.rows[0].counts.loaded, 7);
 assert.equal(diagnostic.rows[0].identifiers.base, 'base');
 assert.equal(diagnostic.drawer, null);
 assert.equal(diagnostic.summary.last_success.value, iso(5));
 assert.doesNotMatch(JSON.stringify(diagnostic), /SECRET|991/);
 assert.deepEqual(view(sources, {search: 'SECRET'}).rows, []);
 assert.deepEqual(view(sources, {search: 'SECRET'}).summary, view(sources).summary);
 assert.deepEqual(view([sources[0]]).summary, diagnostic.summary);
 assert.deepEqual(keys(view([healthy('a'), problem('x', ['forbidden', 'invalid']), healthy('y', {authorized: false})])), ['a']);
});

test('6 drawer selection only; revocation and disappearance drop selection', () => {
 const sources = [healthy('a'), healthy('b')];
 assert.equal(view(sources).drawer, null);
 assert.equal(view(sources, {selectedKey: 'a'}).drawer.key, 'a');
 assert.equal(view(sources, {selectedKey: 'a', search: 'b'}).selectedKey, 'a');
 for (const next of [[healthy('b')], [healthy('a', {authorized: false})], [problem('a', ['forbidden'])]]) {
  const result = view(next, {selectedKey: 'a'});
  assert.deepEqual([result.selectedKey, result.drawer], [null, null]);
 }
});

test('7 retry preserves opaque authorized handle; no scope expansion or unauthorized retry', () => {
 const handle = {existingRead: 'opaque-token', scope: ['existing-source']};
 const row = view([healthy('a', {read_authorized: true, retry_handle: handle})]).rows[0];
 assert.equal(row.retry.handle, handle);
 assert.deepEqual(Object.keys(row.retry), ['handle']);
 for (const extra of [{read_authorized: false, retry_handle: handle}, {retry_handle: handle}, {read_authorized: true}]) assert.equal(view([healthy('a', extra)]).rows[0].retry, null);
 assert.equal(view([healthy('a', {authorized: false, read_authorized: true, retry_handle: handle})]).rows.length, 0);
});

test('8 C-STATE text labels; unknown never zero; malformed payloads fail closed', () => {
 for (const [state, label] of [['loading', '讀取中'], ['complete_empty', '尚無資料'], ['filtered_empty', '沒有符合篩選條件的資料'], ['unlocated', '找不到資料來源'], ['forbidden', '沒有權限'], ['read_failed', '讀取失敗'], ['partial', '部分資料'], ['stale', '資料待更新'], ['unknown', '狀態未知']]) {
  assert.equal(build({page_state: {states: [state]}, sources: []}, options).page.statusLabel, label);
 }
 const unknown = view([{key: 'a', authorized: true, loaded_count: 0}]).rows[0];
 assert.deepEqual([unknown.statusLabel, unknown.counts.loaded, unknown.last_success.label], ['狀態未知', null, '狀態未知']);
 for (const bad of [null, 0, {}, {sources: 'bad'}, {sources: [null, {}, , {key: 'a'}]}]) assert.deepEqual(keys(build(bad, options).diagnostic), []);
 for (const badTime of ['2026-02-30T00:00:00Z', '2026-10-03', '2026-10-03T00:00:00', '2026-10-03T24:00:00Z', 0]) assert.equal(view([healthy('a', {source_updated: badTime})]).rows[0].source_updated.value, null);
 assert.deepEqual(keys(view([healthy('duplicate'), healthy('duplicate'), healthy('unique')])), ['unique']);
 assert.equal(view([problem('a', ['unknown'], {loaded_count: 0})]).rows[0].counts.loaded, null);
 assert.deepEqual(view([healthy('a', {loaded_count: -1, whole_table_count: '37', view_count: 0, excluded_count: 1.5})]).rows[0].counts,
  {whole_table: null, view: 0, loaded: null, excluded: null});
});

test('G2 loading and unlocated suppress every scoped count', () => {
 for (const state of ['loading', 'unlocated']) {
  const row = view([problem('a', [state], {whole_table_count: 9, view_count: 8, loaded_count: 5, excluded_count: 3})]).rows[0];
  assert.deepEqual(row.counts, {whole_table: null, view: null, loaded: null, excluded: null});
 }
});

test('G4 timestamp sorting compares instants across mixed offsets', () => {
 for (const column of ['last_attempt', 'last_success', 'source_updated']) {
  const sources = [healthy('x', {[column]: '2026-10-03T01:00:00+08:00'}), healthy('y', {[column]: '2026-10-02T20:00:00Z'})];
  assert.deepEqual(keys(view(sources, {sort: {column, direction: 'asc'}})), ['x', 'y']);
  assert.deepEqual(keys(view(sources, {sort: {column, direction: 'desc'}})), ['y', 'x']);
 }
});

test('G5 present non-boolean stage flags are unknown and need attention', () => {
 for (const stage of ['located', 'readable', 'presented']) {
  for (const value of ['false', 0, 'no', null, undefined]) {
   for (const source of [healthy('a', {[stage]: value}), problem('a', ['partial'], {[stage]: value})]) {
    const row = view([source]).rows[0];
    assert.deepEqual([row.statusLabel, row.needsAttention, row.dataState?.states, row[stage]], ['狀態未知', true, ['unknown'], null]);
   }
  }
 }
 for (const extra of [{}, {located: true, readable: true, presented: true}]) {
  const row = view([healthy('a', extra)]).rows[0];
  assert.deepEqual([row.statusLabel, row.needsAttention, row.dataState], ['資料正常', false, null]);
 }
});

test('G6 source and field mappings use unverified mapping copy without authority', () => {
 const sources = [healthy('healthy', {located: true, readable: true, presented: true}),
  ...['loading', 'complete_empty', 'filtered_empty', 'unlocated', 'read_failed', 'partial', 'stale', 'unknown'].map(state => problem(state, [state]))];
 for (const source of sources) {
  const row = view([{...source, mapped: true, accepted: true, receipt: {source_key: source.key, reference: 'untrusted'},
   fields: [{field_id: 'f', yx_mapping: 'untrusted'}, {}]}]).rows[0];
  assert.deepEqual([row.mappingLabel, row.mapped, row.accepted, row.receiptReference], ['對應未驗證', false, false, null]);
  assert.deepEqual(row.fields.map(field => [field.mappingLabel, field.yxMapping]), [['對應未驗證', null], ['對應未驗證', null]]);
 }
});

test('F1 timestamp sorting never substitutes retrieval and keeps unknown last', () => {
 const bothUnknown = [healthy('a', {last_attempt: iso(12)}), healthy('b', {last_attempt: iso(1)})];
 for (const direction of ['asc', 'desc']) {
  assert.deepEqual(keys(view(bothUnknown, {sort: {column: 'source_updated', direction}})), ['a', 'b']);
  for (const column of ['last_attempt', 'last_success', 'source_updated']) {
   const mixed = [healthy('a'), healthy('b', {[column]: iso(5)})];
   assert.deepEqual(keys(view(mixed, {sort: {column, direction}})), ['b', 'a']);
  }
 }
});

test('F2 healthy text requires absence of every negative stage flag', () => {
 const normal = view([healthy('a')]).rows[0];
 assert.deepEqual([normal.statusLabel, normal.needsAttention, normal.dataState], ['資料正常', false, null]);
 for (const stage of ['readable', 'presented', 'located']) {
  const row = view([healthy('a', {[stage]: false})]).rows[0];
  assert.deepEqual([row.statusLabel, row.needsAttention, row[stage]], [stage === 'located' ? '找不到資料來源' : '狀態未知', true, false]);
 }
});

test('F3 read_failed suppresses every count rather than inventing an empty read', () => {
 const row = view([problem('a', ['read_failed'], {whole_table_count: 9, view_count: 8, loaded_count: 5, excluded_count: 3})]).rows[0];
 assert.deepEqual([row.statusLabel, row.counts], ['讀取失敗', {whole_table: null, view: null, loaded: null, excluded: null}]);
});

test('F4 accepted is always false even with matched caller receipts and stage flags', () => {
 for (const mapped of [true, false, undefined]) {
  const row = view([healthy('a', {located: true, readable: true, presented: true, mapped, accepted: true,
   receipt: {source_key: 'a', reference: 'receipt', verified: true, version: 'V4'},
   fields: [{field_id: 'f', yx_mapping: 'binding', receipt: {source_key: 'a', reference: 'receipt'}}]})]).rows[0];
  assert.deepEqual([row.located, row.readable, row.presented, row.mapped, row.accepted, row.receiptReference, row.mappingLabel,
   row.fields[0].yxMapping, row.fields[0].mappingLabel], [true, true, true, false, false, null, '對應未驗證', null, '對應未驗證']);
 }
});

test('F5 empty states never present contradictory nonzero scope counts', () => {
 for (const state of ['complete_empty', 'filtered_empty']) {
  const row = view([problem('a', [state], {whole_table_count: 9, view_count: 8, loaded_count: 5, excluded_count: 3})]).rows[0];
  assert.deepEqual([row.dataState.count, row.counts], [0, {whole_table: null, view: null, loaded: null, excluded: null}]);
 }
});

test('F7 malformed and forbidden-looking states expose no metadata anywhere', () => {
 const malformed = ['forbidden', {state: 'forbidden'}, null, {}, {states: 'forbidden'}, {states: []},
  {states: ['partial', 'unknown']}, {states: ['partial'], count: -1}, {states: ['unknown'], count: 0},
  {states: ['invalid']}, {states: ['stale', 'stale']}, {states: ['forbidden', 'invalid']},
  {states: ['unknown'], state: 'forbidden'}];
 for (const data_state of malformed) {
  const secret = healthy('SECRET_KEY', {data_state, name: 'SECRET_NAME', last_success: iso(1), loaded_count: 991,
   base_id: 'SECRET_ID', fields: [{field_id: 'SECRET_FIELD'}], read_authorized: true, retry_handle: 'SECRET_HANDLE'});
  const sources = [healthy('visible', {last_success: iso(5)}), secret];
  const result = view(sources, {selectedKey: 'SECRET_KEY'});
  assert.deepEqual(keys(result), ['visible']);
  assert.deepEqual([result.drawer, result.selectedKey, result.summary.last_success.value], [null, null, iso(5)]);
  assert.doesNotMatch(JSON.stringify(result), /SECRET|991/);
  assert.deepEqual(keys(view(sources, {search: 'SECRET'})), []);
 }
 assert.equal(view([problem('known-unknown', ['unknown'])]).rows[0].statusLabel, '狀態未知');
});

test('F8 ordinary read_failed guidance offers an available administrator action', () => {
 const result = build({page_state: {states: ['read_failed']}, sources: []}, {diagnosticCapability: false});
 assert.deepEqual(result, {page: {states: ['read_failed'], statusLabel: '讀取失敗', explanation: '請聯絡管理員確認既有授權讀取的失敗原因。'}, diagnostic: null});
});

let passed = 0;
test('H1 null page_state stays unknown and never yields a healthy/clean label; absent or malformed too', () => {
 for (const nul of [{page_state: null, sources: []}, {sources: []}, {page_state: undefined, sources: []}, {page_state: 0, sources: []}, {page_state: {}, sources: []}, {page_state: {states: ['bogus']}, sources: []}, null, 'x']) {
  const page = build(nul, options).page;
  assert.deepEqual([page.states, page.statusLabel], [['unknown'], '狀態未知'], JSON.stringify(nul));
  assert.equal('healthy' in page, false);
  assert.doesNotMatch(JSON.stringify(page), /資料正常|已完成讀取/);
 }
 assert.deepEqual(build({page_state: null, sources: []}, {diagnosticCapability: false}).page.states, ['unknown']);
 assert.deepEqual(build({page_state: {states: ['stale']}, sources: []}, options).page.states, ['stale']);
});

for (const [name, run] of tests) {
 if (process.env.SOURCE_HEALTH_TEST && !name.startsWith(process.env.SOURCE_HEALTH_TEST)) continue;
 run(); passed++; console.log(`PASS ${name}`);
}

// Actually execute incorrect modules against these same behavioral assertions.
// Mutation files are temporary and never alter the checkout or install dependencies.
if (!process.env.SOURCE_HEALTH_MODULE) {
 const {spawnSync} = await import('node:child_process');
 const source = readFileSync(new URL('./src/sourceHealthView.ts', import.meta.url), 'utf8');
 const mutations = [
  ['unknown source update falls back to retrieval', 'const av = a[column].value, bv = b[column].value;', "const av = a[column].value ?? (column === 'source_updated' ? a.last_attempt.value : null), bv = b[column].value ?? (column === 'source_updated' ? b.last_attempt.value : null);", 'F1 '],
  ['unknown timestamp sorts first', 'return av === null ? 1 : -1;', 'return av === null ? -1 : 1;', 'F1 '],
  ['healthy label erased', "statusLabel: state === null ? '資料正常'", "statusLabel: state === null ? ''", 'F2 '],
  ['failed read retains counts', "['unknown', 'loading', 'unlocated', 'read_failed']", "['unknown', 'loading', 'unlocated']", 'F3 '],
  ['caller receipt reference echoed', 'receiptReference: null,', 'receiptReference: text(record(raw.receipt).reference),', '3 distinct'],
  ['retrieval substituted for source update', 'const column = sort.column;', "const column = sort.column === 'source_updated' ? 'last_attempt' : sort.column;", '1 attention-first'],
  ['caller string re-enables mapping authority', 'const mapped = false;', "const mapped = raw.mapped === true && record(raw.receipt).source_key === key && text(record(raw.receipt).reference) !== null;", '3 distinct'],
  ['caller string re-enables acceptance', 'const accepted = false;', "const accepted = raw.accepted === true && text(record(raw.receipt).reference) !== null;", 'F4 '],
  ['field caller string re-enables YX binding', 'const mapping = null;', 'const mapping = text(field.yx_mapping);', '3 distinct'],
  ['forbidden metadata leaked', 'permitsSourceState(source.data_state)', 'true', '5 viewer split'],
 ];
 const dir = mkdtempSync(join(tmpdir(), 'source-health-mutations-'));
 try {
  copyFileSync(new URL('./src/dataState.ts', import.meta.url), join(dir, 'dataState.ts'));
  for (const [name, from, to, expectedTest] of mutations) {
   assert.ok(source.includes(from), `mutation anchor exists: ${name}`);
   const file = join(dir, 'sourceHealthView.ts');
   writeFileSync(file, source.replace(from, to));
   const result = spawnSync(process.execPath, [new URL(import.meta.url).pathname], {env: {...process.env, SOURCE_HEALTH_MODULE: pathToFileURL(file).href, SOURCE_HEALTH_TEST: expectedTest}, encoding: 'utf8'});
   assert.notEqual(result.status, 0, `mutant must fail: ${name}`);
   assert.doesNotMatch(result.stdout, /PASS/);
   assert.match(result.stderr, /AssertionError/);
   console.log(`PASS mutation rejected: ${name} (${expectedTest})`);
  }
 } finally {rmSync(dir, {recursive: true, force: true});}
}
console.log(`source health: ${passed} named tests passed`);
