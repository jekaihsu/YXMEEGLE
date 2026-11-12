import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
const b=await build({stdin:{contents:"import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {MetaNotice} from './src/reports/shared';export const render=meta=>renderToStaticMarkup(<MetaNotice meta={meta}/>);",resolveDir:import.meta.dirname,loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',loader:{'.css':'empty'}});
const m={exports:{}};new Function('require','module','exports',b.outputFiles[0].text)(createRequire(import.meta.url),m,m.exports);
const html=m.exports.render({gaps:[],stale:true,fetched_at:'2026-11-02T12:00:00Z'});
assert.doesNotMatch(html,/背景更新中/,'stale alone is not proof of an active refresh');assert.match(html,/資料待更新/);assert.match(html,/2026/);
assert.match(m.exports.render({gaps:[],stale:true,refresh_error:'failed'}),/舊資料 · 資料待更新/);
console.log('reports stale notice: truthful state and retained timestamp');
