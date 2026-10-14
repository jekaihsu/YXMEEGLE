import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {spawnSync} from 'node:child_process';

const generated = spawnSync(process.env.YX_TEST_PYTHON ?? '/Users/vc/Local/worktrees/YXMEEGLE/yx-company-system/.venv/bin/python', ['-c', `
import json
from backend.test_confirmation_list import state
from backend.confirmation_list import build_confirmation_list
print(json.dumps(build_confirmation_list(state(source_status={'status':'stale','last_success_at':'2026-10-14T01:00:00Z'}),as_of='2026-10-14T02:00:00Z')))
`], {cwd: new URL('../', import.meta.url).pathname, encoding: 'utf8'});
assert.equal(generated.status, 0, generated.stderr);
const fixture = JSON.parse(generated.stdout);

const bundle = await build({entryPoints: [new URL('./src/P2Pages.tsx', import.meta.url).pathname], bundle: true,
 write: false, platform: 'node', format: 'esm', jsx: 'automatic', packages: 'external', loader: {'.css': 'empty'}});
const path = new URL('./.confirmations-loading-bundle.mjs', import.meta.url);
await fs.writeFile(path, bundle.outputFiles[0].text);
let P2Page;
try {({P2Page} = await import(path.href));} finally {await fs.unlink(path);}
const dom = new JSDOM('<div id="root"></div>', {url: 'http://localhost/#view=confirmations'});
for (const key of ['window', 'document', 'location', 'history', 'HTMLElement', 'Event'])
 Object.defineProperty(globalThis, key, {configurable: true, value: dom.window[key]});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let finish;
globalThis.fetch = () => new Promise(resolve => {finish = resolve;});
const root = createRoot(document.getElementById('root'));
try {
 await act(async () => {root.render(React.createElement(P2Page, {c: {
  route: {view: 'confirmations'}, w: {version: 1}, s: {user: {id: 'synthetic-user'}}, go: () => {},
 }}));});
 const content = document.querySelector('main').textContent;
 assert.match(content, /讀取中/);
 assert.ok(!content.includes('confirmation list body is malformed or unavailable'));
 assert.equal(document.querySelectorAll('tbody tr').length, 1);
 console.log('PASS pending confirmations render loading without malformed-body fallback');
 await act(async () => {finish(new Response(JSON.stringify(fixture)));});
 assert.equal(document.querySelectorAll('tbody tr').length, 6);
 const loaded = document.querySelector('main').textContent;
 assert.match(loaded, /資料待更新/);
 assert.match(loaded, /2026-10-14T01:00:00Z/);
 assert.match(loaded, /已載入筆數：6/);
 assert.ok(!loaded.includes('confirmation list body is malformed or unavailable'));
 console.log('PASS completed backend snapshot renders six rows, counts and last-success time');
} finally {await act(async () => root.unmount()); dom.window.close();}
