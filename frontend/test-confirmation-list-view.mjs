// Synthetic behavioral checks; Node >=22 type stripping, no network/Lark calls.
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
const {buildConfirmationListView: view} = await import(process.env.CONFIRMATION_VIEW_MODULE ?? './src/confirmationListView.ts');
const tests = [];
const test = (name, run) => tests.push([name, run]);
const row = (key = 'base/table/record@i3', extra = {}) => ({
 row_key: key, case_number: 'SYN-01', project_name: '合成工程',
 confirmation_version: {state: 'known', value: '3'}, pm: {state: 'known', id: 'synthetic-pm', name: '合成角色'},
 admission: {state: 'workbench', label: '工作台執行', readonly_reason: null},
 effective_due: {state: 'unknown', value: null, reason: 'VCC-123 provenance unresolved'},
 source_modified: {state: 'unknown', value: null, reason: 'source-modified field absent'},
 workflow_summary: {state: 'known', total: 2, completed: 1, by_status: {completed: 1, pending: 1}},
 source_status: 'located', retention: 'current',
 case_link: {state: 'linked', project_id: 'synthetic-case', reason: null, verification: 'receipt_missing'},
 detail: {source_context: {base_token: 'base', table_id: 'table'}, record_id: 'record', non_default: true}, ...extra,
});
const body = (extra = {}) => ({
 status: 200, as_of: '2026-10-14T01:00:00Z', page_state: null, rows: [row()], next_cursor: 'issued_server_cursor',
 totals: {matching: 9, loaded: 1, authorized_source: 12}, totals_basis: 'current', snapshot: null,
 filter_status: {deadline: {status: 'unavailable', reason: 'VCC-123 provenance unresolved', hides_rows: false, requested: {}}},
 sort: {applied: null, order_basis: 'source_order_then_row_key', source_modified: 'unavailable', reason: 'no source-modified field'},
 columns: {default: ['case_number', 'project_name', 'confirmation_version', 'pm', 'admission_state', 'effective_due', 'workflow_summary', 'source_modified', 'source_status'], non_default: ['record_id', 'source_context']},
 amounts: {state: 'withheld', reason: 'contract amounts hidden pending G-AMT'},
 excluded_unknown: {distinct_rows: 0}, diagnostics: {unkeyed_rows: 0, duplicate_versions_collapsed: 0},
 grouping: {basis: 'verified project_id assignment only', linked_cases: 1, by_case: [{project_id: 'synthetic-case', rows: 9}], unresolved_rows: 0}, ...extra,
});
const snapshot = (state, extra = {}) => body({page_state: {states: [state], count: null}, totals_basis: 'retained_snapshot',
 snapshot: {state: 'proven', last_success_at: '2026-10-13T01:00:00Z'},
 rows: [row(undefined, {source_status: 'stale', retention: 'snapshot'})], ...extra});

test('dense table preserves duplicate case numbers and versions in server order', () => {
 const v = view(body({rows: [row('base/table/r@i4'), row('base/table/r@i3')], totals: {matching: 9, loaded: 2, authorized_source: 12}}));
 assert.deepEqual(v.table.rows.map(r => r.key), ['base/table/r@i4', 'base/table/r@i3']);
 assert.equal(v.table.rows[0].cells.case_number.label, 'SYN-01');
 assert.equal(v.table.density, 'dense');
 assert.deepEqual(v.table.stickyColumns, ['case_number', 'project_name']);
 assert.equal(v.drawer.open, false);
});
test('footer shows three distinct server totals without deriving them', () => {
 const v = view(body());
 assert.deepEqual([v.footer.matching.label, v.footer.loaded.label, v.footer.authorizedSource.label], ['9', '1', '12']);
});
test('unknown totals are em dash with a reason, never zero', () => {
 const v = view(snapshot('unknown', {totals_basis: 'undetermined', totals: {matching: null, loaded: 1, authorized_source: null}}));
 assert.equal(v.footer.matching.label, '—'); assert.match(v.footer.matching.reason, /unknown/);
 assert.equal(v.footer.authorizedSource.label, '—'); assert.equal(v.footer.loaded.label, '1');
 assert.equal(v.pageStateLabel, '狀態未知');
});
test('complete authorized empty and filtered empty remain distinct', () => {
 const empty = view(body({page_state: {states: ['complete_empty'], count: 0}, rows: [], next_cursor: null, totals: {matching: 0, loaded: 0, authorized_source: 0}}));
 assert.equal(empty.pageStateLabel, '尚無資料'); assert.equal(empty.footer.authorizedSource.label, '0');
 const filtered = view(body({page_state: {states: ['filtered_empty'], count: 0}, rows: [], next_cursor: null, totals: {matching: 0, loaded: 0, authorized_source: 12}}));
 assert.equal(filtered.pageStateLabel, '沒有符合篩選條件的資料'); assert.equal(filtered.footer.matching.label, '0');
});
test('loading and unlocated short bodies never invent a loaded zero', () => {
 for (const state of ['loading', 'unlocated']) {
  const v = view({status: 200, page_state: {states: [state], count: null}, rows: [], next_cursor: null, totals: {matching: null, loaded: 0, authorized_source: null}});
  assert.equal(v.pageState.states[0], state); assert.equal(v.footer.loaded.label, '—'); assert.ok(v.footer.loaded.reason);
 }
 const malformed = view({status: 200, page_state: {states: ['loading'], count: null}, rows: [row()], next_cursor: null, totals: {matching: null, loaded: 0, authorized_source: null}});
 assert.equal(malformed.pageStateLabel, '狀態未知'); assert.match(malformed.reason, /malformed/);
});
test('withheld amounts expose the G-AMT reason and no supplied values or derived values', () => {
 const v = view(body({amounts: {state: 'withheld', reason: 'contract amounts hidden pending G-AMT', value: 987654321, sum: 987654321}}));
 assert.deepEqual(v.amounts, {state: 'withheld', label: '未核准顯示', reason: 'contract amounts hidden pending G-AMT'});
 assert.ok(!JSON.stringify(v).includes('987654321'));
});
test('forbidden body revokes rows, selection, totals, filters and identifiers', () => {
 const good = view(body(), {selected: 'base/table/record@i3'}); assert.equal(good.drawer.detail.recordId, 'record');
 const v = view(body({status: 403, page_state: {states: ['forbidden'], count: 999, name: 'FORBIDDEN_SECRET'}}),
  {selected: 'base/table/record@i3', filters: {search: 'FORBIDDEN_SECRET'}});
 assert.equal(v.pageStateLabel, '沒有權限'); assert.deepEqual(v.table.rows, []); assert.equal(v.drawer.detail, null);
 assert.equal(v.footer.loaded.label, '—'); assert.ok(!JSON.stringify(v).includes('FORBIDDEN_SECRET'));
 assert.ok(!JSON.stringify(v).includes('synthetic-case'));
});
test('one malformed row fails the entire body closed to unknown', () => {
 const v = view(body({rows: [row(), {...row('bad'), pm: 'invalid'}], totals: {matching: 9, loaded: 2, authorized_source: 12}}));
 assert.equal(v.pageStateLabel, '狀態未知'); assert.deepEqual(v.table.rows, []); assert.match(v.reason, /malformed/);
 assert.equal(v.footer.matching.label, '—');
});
test('each consumed nested guard rejects malformed bodies without partial trust', () => {
 const corruptions = [b => b.rows[0].confirmation_version.value = 4, b => b.rows[0].admission.state = 'invented',
  b => b.rows[0].effective_due.value = '2026-10-01', b => b.rows[0].source_modified.value = b.as_of,
  b => b.rows[0].workflow_summary.total = 88, b => b.rows[0].retention = 'snapshot',
  b => b.rows[0].case_link.verification = 'verified', b => delete b.rows[0].detail.record_id,
  b => b.next_cursor = 12, b => b.totals.loaded = 44, b => b.snapshot = {},
  b => b.filter_status.deadline.hides_rows = true, b => b.sort.applied = {column: 'source_modified', direction: 'desc'},
  b => b.columns.default = [], b => b.excluded_unknown.distinct_rows = -1, b => b.diagnostics.unkeyed_rows = '1',
  b => b.grouping.by_case = [null], b => b.page_state = {states: ['bogus'], count: null},
  b => b.amounts.state = 'known', b => b.amounts.reason = 'approved', b => b.rows = new Array(1)];
 for (const corrupt of corruptions) {
  const b = body(); corrupt(b); const v = view(b);
  assert.equal(v.pageStateLabel, '狀態未知', String(corrupt)); assert.equal(v.table.rows.length, 0, String(corrupt));
 }
});
test('unresolved cases remain explicit rows with receipt_missing vocabulary', () => {
 const v = view(body({rows: [row(undefined, {case_link: {state: 'unresolved', project_id: null, reason: 'assignment_absent', verification: 'receipt_missing'},
  pm: {state: 'unknown', id: null, name: 'source text'}, admission: {state: 'unknown', label: null, readonly_reason: 'case link unresolved'},
  workflow_summary: {state: 'unknown', reason: 'case link unresolved'}})]}), {selected: 'base/table/record@i3'});
 assert.equal(v.table.rows[0].caseLink.label, '案件連結未解決'); assert.equal(v.table.rows[0].caseLink.reason, 'assignment_absent');
 assert.equal(v.table.rows[0].caseLink.verificationLabel, '對應未驗證'); assert.equal(v.drawer.detail.projectId, null);
 assert.equal(v.table.rows[0].cells.pm.label, '—');
});
test('partial, stale and read failure snapshots have per-row text and distinct retrieval time', () => {
 for (const state of ['partial', 'stale', 'read_failed']) {
  const v = view(snapshot(state)); assert.equal(v.pageState.states[0], state);
  assert.equal(v.table.rows[0].sourceStatusLabel, '資料待更新'); assert.equal(v.table.rows[0].retentionLabel, '保留快照');
  assert.equal(v.header.snapshot.label, '2026-10-13T01:00:00Z'); assert.equal(v.table.rows[0].cells.source_modified.label, '—');
 }
 const v = view(snapshot('partial', {totals_basis: 'partial_snapshot', rows: [], next_cursor: null, totals: {matching: 0, loaded: 0, authorized_source: 9}}));
 assert.equal(v.footer.matching.label, '—'); assert.equal(v.footer.loaded.label, '—');
});
test('technical IDs only appear in selected source drawer and chooser stays non-default', () => {
 const v = view(body()); assert.equal(v.table.rows[0].cells.record_id, undefined);
 assert.equal(v.columns.find(c => c.key === 'record_id').visible, false); assert.equal(v.columns.find(c => c.key === 'source_context').default, false);
 const selected = view(body(), {selected: 'base/table/record@i3', columns: ['project_name', 'record_id']});
 assert.equal(selected.drawer.selectionOnly, true); assert.equal(selected.drawer.detail.sourceContext.tableId, 'table');
 assert.equal(selected.columns.find(c => c.key === 'record_id').visible, true);
 assert.equal(view(body(), {selected: 'absent'}).drawer.open, false);
});
test('deadline disabled with backend reason; sorting offers asc desc clear only on supported columns', () => {
 const v = view(body(), {filters: {deadline_from: '2026-01-01'}, sort: {key: 'confirmation_version', dir: 'desc'}});
 assert.deepEqual(v.controls.deadline, {disabled: true, reason: '尚無法判定期限：期限來源待確認'});
 assert.deepEqual(v.controls.sort, {key: 'confirmation_version', dir: 'desc'});
 assert.deepEqual(v.columns.find(c => c.key === 'pm').sortChoices, ['asc', 'desc', 'clear']);
 assert.equal(v.columns.find(c => c.key === 'source_modified').sortable, false);
 assert.equal(view(body(), {sort: null}).controls.sort, null);
 assert.equal(view(body({sort: {applied: {column: 'pm', direction: 'asc'}, order_basis: 'column_then_row_key', source_modified: 'unavailable', reason: 'unavailable'}}), {sort: null}).controls.sort, null);
 assert.deepEqual(v.controls.resetFilters, {filters: {}, cursor: null});
});
test('next is opaque server cursor; previous only accepts same-query actual cursor history', () => {
 const opts = {filters: {search: 'synthetic', pm: 'synthetic-pm'}, sort: {key: 'pm', dir: 'asc'}, cursor: 'current_server_cursor'};
 const page = body({sort: {applied: {column: 'pm', direction: 'asc'}, order_basis: 'column_then_row_key', source_modified: 'unavailable', reason: 'unavailable'}});
 const history = {filters: {...opts.filters}, sort: {...opts.sort}, current: opts.cursor, stack: [null, 'earlier_server_cursor']};
 const v = view(page, {...opts, cursorHistory: history});
 assert.equal(v.pagination.kind, 'server_cursor'); assert.equal(v.pagination.next.cursor, 'issued_server_cursor');
 assert.deepEqual(v.pagination.previous, {enabled: true, cursor: 'earlier_server_cursor', reason: null});
 assert.deepEqual(view(page, {...opts, cursorHistory: {...history, stack: [null]}}).pagination.previous, {enabled: true, cursor: null, reason: null});
 for (const wrong of [{...history, filters: {search: 'changed'}}, {...history, sort: null}, {...history, current: 'wrong'}, {...history, stack: []}, {...history, stack: [1]}]) {
  const prev = view(page, {...opts, cursorHistory: wrong}).pagination.previous;
  assert.equal(prev.enabled, false); assert.ok(prev.reason);
 }
});
test('read-only view never projects caller write actions or raw metadata', () => {
 const v = view(body({actions: ['Complete', 'Approve', 'SOP'], raw: {hidden: 'RAW_SECRET'}}));
 assert.equal(v.table.rows[0].cells.project_name.label, '合成工程'); assert.ok(!JSON.stringify(v).includes('RAW_SECRET'));
 assert.equal(v.actions, undefined); assert.equal(v.drawer.actions, undefined);
});

let failures = 0;
for (const [name, run] of tests) {try {run(); console.log(`PASS ${name}`);} catch (error) {failures++; console.error(`FAIL ${name}\n${error.stack}`);}}
if (failures) process.exit(1);
console.log(`${tests.length} named behavioral tests passed`);

// Rerunnable mutation evidence for the four mandatory safety guards. Every
// mutant runs these same public behavior tests in a separate Node process.
if (process.argv.includes('--mutations')) {
 const source = readFileSync(new URL('./src/confirmationListView.ts', import.meta.url), 'utf8');
 const mutations = [
  ['unknown-not-zero', "({label: '—', reason})", "({label: '0', reason})"],
  ['amount-withheld', "label: '未核准顯示', reason: b?.amounts.reason", "label: '987654321', reason: b?.amounts.reason"],
  ['forbidden-absent', "const valid = !blocked && validBody(raw);", "const valid = forbidden || !blocked && validBody(raw);"],
  ['malformed-fail-closed', "!Array.from(v.rows).every(validRow)", "false"],
 ];
 const dir = mkdtempSync(join(tmpdir(), 'confirmation-view-mutations-'));
 try {
  for (const [name, from, to] of mutations) {
   assert.ok(source.includes(from), `mutation target exists: ${name}`);
   const path = join(dir, `${name}.ts`);
   const mutated = source.replace(from, to).replaceAll("'./dataState.ts'", JSON.stringify(new URL('./src/dataState.ts', import.meta.url).href));
   writeFileSync(path, mutated);
   const run = spawnSync(process.execPath, [new URL(import.meta.url).pathname], {encoding: 'utf8', env: {...process.env, CONFIRMATION_VIEW_MODULE: pathToFileURL(path).href}});
   assert.notEqual(run.status, 0, `mutant must fail: ${name}`);
   assert.match(run.stderr, /FAIL /, `behavior assertion kills mutant: ${name}`);
   console.log(`KILLED ${name}: exit ${run.status}; ${run.stderr.split('\n')[0]}`);
  }
 } finally {rmSync(dir, {recursive: true, force: true});}
}
