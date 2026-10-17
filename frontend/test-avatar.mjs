import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import {JSDOM} from 'jsdom';
const dom = new JSDOM('<div id="root"></div>');
for (const key of ['window', 'document', 'navigator', 'Event']) Object.defineProperty(globalThis, key, {value: dom.window[key], configurable: true});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = await import('react');
const {createRoot} = await import('react-dom/client');
const bundle = await build({entryPoints: ['src/Avatar.tsx'], bundle: true, write: false, platform: 'node', format: 'esm', packages: 'external', jsx: 'automatic', loader: {'.css': 'empty'}});
const path = new URL('./.avatar-test.mjs', import.meta.url);
await fs.writeFile(path, bundle.outputFiles[0].text);
let Avatar;
try {({Avatar} = await import(path.href))} finally {await fs.unlink(path)}
const root = createRoot(document.getElementById('root'));
const photo = 'https://s16-imfile-sg.feishucdn.com/static-resource/photo';
const render = async user => React.act(async () => root.render(React.createElement(Avatar, {user, small: true})));
try {
  await render({name: '王怡婷', avatar_url: photo});
  const img = document.querySelector('img');
  assert.equal(img.getAttribute('src'), photo);
  assert.equal(img.getAttribute('alt'), '王怡婷');
  assert.equal(img.getAttribute('loading'), 'lazy');
  assert.equal(img.getAttribute('referrerpolicy'), 'no-referrer');
  assert.equal(img.parentElement.className, 'avatar small');
  await React.act(async () => img.dispatchEvent(new Event('error')));
  assert.equal(document.querySelector('img'), null);
  assert.equal(document.getElementById('root').textContent, '王');
  await render({name: '林育寬', avatar_url: photo + '2'});
  assert.equal(document.querySelector('img').alt, '林育寬');
  for (const avatar_url of [undefined, 'https://evil.test/photo', 'https://feishucdn.com.evil.test/photo', 'http://s16-imfile-sg.feishucdn.com/photo', 'https://user:secret@s16-imfile-sg.feishucdn.com/photo']) {
    await render({name: '林育寬', avatar_url});
    assert.equal(document.querySelector('img'), null);
    assert.equal(document.getElementById('root').textContent, '林');
  }
  console.log('Avatar image, error fallback, URL changes and allowlist tests passed');
} finally {await React.act(async () => root.unmount())}
