// P1-INT: hash return context, legacy tabs, fetched-payload adapters, and App wiring of the two pages.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
const bundle = await build({stdin: {contents: `export * from './src/integrationRoutes.ts'; export {parseRoute} from './src/api.ts';
 export {buildMyWorkView} from './src/myWorkView.ts'; export {buildSourceHealthView} from './src/sourceHealthView.ts';`,
 resolveDir: process.cwd(), loader: 'ts'}, bundle: true, write: false, platform: 'node', format: 'esm', packages: 'external'});
const m = await import('data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const toHash = route => {const q = new URLSearchParams(); Object.entries(route).forEach(([k, v]) => {if (v) q.set(k, v)}); return q.toString()};

// selection and filters survive navigation and Back (the hash is the only carrier)
const filters = {search: '報價 & 案件 #1', mode: 'awaiting_my_confirmation', selectedId: 'p2-sales-t1'};
const route = m.withFilters({view: 'work'}, filters);
const restored = m.filtersFromRoute(m.parseRoute('#' + toHash(route)));
assert.deepEqual(restored, filters);
assert.equal(m.withFilters({view: 'work', ctx: 'x'}, {}).ctx, undefined, 'default context keeps the bare hash');
assert.deepEqual(m.filtersFromRoute({ctx: '{broken'}), {search: '', mode: 'todo', selectedId: null});
assert.deepEqual(m.filtersFromRoute({}), {search: '', mode: 'todo', selectedId: null});

// legacy screens stay reachable
assert.equal(m.isLegacyTab({tab: 'legacy'}, 'work'), true);
assert.equal(m.isLegacyTab({tab: 'legacy'}, 'sources'), true);
assert.equal(m.isLegacyTab({tab: 'all'}, 'work'), true, 'existing "view all work" link keeps the legacy scope');
assert.equal(m.isLegacyTab({tab: 'all'}, 'sources'), false);
assert.equal(m.isLegacyTab({}, 'work'), false);

// only backend-issued same-origin hash routes navigate
assert.equal(m.hashOfRoute('/#view=project&project=p1&task=t1&tab=flow'), 'view=project&project=p1&task=t1&tab=flow');
for (const bad of ['https://evil.test/#view=project', '//evil.test/#view=x', '/#', '/#foo=bar', 'javascript:1', '/#view=a b', null, 5, '/#view=a\\b']) assert.equal(m.hashOfRoute(bad), null, String(bad));

// fetched adapters: unknown is never zero or empty
const f = {search: '', mode: 'todo', selectedId: null};
assert.deepEqual(m.buildMyWorkView(m.myWorkInput({status: 'loading'}, f)).pageState.states, ['loading']);
assert.deepEqual(m.buildMyWorkView(m.myWorkInput({status: 'error', httpStatus: 403}, f)).pageState, {states: ['forbidden']});
assert.deepEqual(m.buildMyWorkView(m.myWorkInput({status: 'error', httpStatus: 500}, f)).pageState.states, ['read_failed']);
assert.deepEqual(m.buildMyWorkView(m.myWorkInput({status: 'ok', body: null}, f)).pageState.states, ['unknown']);
const ok = m.buildMyWorkView(m.myWorkInput({status: 'ok', body: {rows: [{id: 'a', title: 'T', ended: false, parent: {verified: false}}], readState: 'ready', assignment: 'assigned', canSeeAwaitingConfirmation: false}}, f));
assert.equal(ok.pageState, null); assert.equal(ok.count, 1); assert.equal(ok.rows[0].id, 'a');
assert.equal(m.buildMyWorkView(m.myWorkInput({status: 'ok', body: {rows: [], readState: 'ready', assignment: 'unknown'}}, f)).pageState.states[0], 'unknown');
assert.equal(m.myWorkInput({status: 'ok', body: {rows: [], weeklyActivity: {items: [{id: 'x'}]}}}, f).weeklyActivity, undefined, 'weekly activity stays absent');

const health = fetched => m.buildSourceHealthView(m.sourceHealthInput(fetched), {diagnosticCapability: false}).page;
assert.deepEqual(health({status: 'ok', body: {page_state: null, sources: []}}).states, ['unknown'], 'null page_state is unknown, never healthy');
assert.equal(health({status: 'ok', body: {page_state: null, sources: []}}).statusLabel, '狀態未知');
assert.equal('healthy' in health({status: 'ok', body: {page_state: null, sources: []}}), false);
assert.deepEqual(health({status: 'ok', body: {sources: []}}).states, ['unknown']);
assert.deepEqual(health({status: 'ok', body: {page_state: {states: ['stale'], count: null}, sources: []}}).states, ['stale']);
assert.deepEqual(health({status: 'error', httpStatus: 403}).states, ['forbidden']);
assert.deepEqual(health({status: 'error'}).states, ['read_failed']);
assert.deepEqual(health({status: 'loading'}).states, ['loading']);
assert.deepEqual(health({status: 'ok', body: 'x'}).states, ['unknown']);

// App wiring: pages are the defaults, legacy components stay mounted behind tab=legacy, nothing else is fetched
const app = await fs.readFile(new URL('./src/App.tsx', import.meta.url), 'utf8');
assert.match(app, /route\.view==='work'&&\(isLegacyTab\(route,'work'\)\?[^]*?<MyWork c=\{fc\}\/>[^]*?:<WorkPage c=\{c\}\/>\)/);
assert.match(app, /route\.view==='sources'&&\(isLegacyTab\(route,'sources'\)\?[^]*?<Sources c=\{c\}\/>[^]*?:<SourceHealthPage c=\{c\}\/>\)/);
assert.match(app, /async function sync|const sync=async/, 'legacy sync function is not deleted');
const pages = await fs.readFile(new URL('./src/IntegratedPages.tsx', import.meta.url), 'utf8');
assert.deepEqual([...pages.matchAll(/useFetched\('([^']+)'/g)].map(x => x[1]).sort(), ['/api/health', '/api/my-work', '/api/source-health']);
assert.match(pages, /diagnosticCapability: true/);
assert.doesNotMatch(pages, /\/api\/(audit|projects|actions|workspace)\b|method:\s*'(POST|PUT|PATCH|DELETE)'/, 'VCC-125: no reuse of audit/action/project payloads and no writes');
console.log('integration routes: all passed');
