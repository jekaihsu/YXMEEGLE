import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const b=await build({stdin:{contents:"export {SourceHealth} from './src/SourceHealth';export {buildSourceHealthView} from './src/sourceHealthView';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.source-health-ui.mjs',import.meta.url);await writeFile(temp,b.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const view=ui.buildSourceHealthView({page_state:{states:['stale']},sources:[{key:'PRIVATE_RECORD_ID',authorized:true,name:'工程來源',data_state:{states:['stale']},last_success:'2026-10-26T00:00:00Z',last_error_summary:'讀取失敗',read_authorized:true,retry_handle:{dataset:'sources'}},{key:'PRIVATE_SECOND_ID',authorized:true,name:'班表來源',data_state:{states:['unknown']}}]},{diagnosticCapability:true});
const html=renderToStaticMarkup(React.createElement(ui.SourceHealth,{view,onRetry:()=>{}}));
assert.match(html,/部分來源時間未知/);assert.match(html,/2026\/10\/26 08:00:00/);assert.match(html,/前/);assert.match(html,/尚無成功紀錄/);assert.match(html,/讀取失敗/);assert.match(html,/重試/);assert.doesNotMatch(html,/PRIVATE_|來源代碼|對應未驗證|請聯絡管理員/);
assert.match(html,/>待處理</);
console.log('Source health shows Taipei time, age, unknown state and retry without identifiers.');

const unknownPage=ui.buildSourceHealthView({page_state:{states:['unknown']},sources:[{key:'healthy',authorized:true,health:'healthy',name:'工程來源'}]},{diagnosticCapability:true});
const unknownHtml=renderToStaticMarkup(React.createElement(ui.SourceHealth,{view:unknownPage}));
assert.match(unknownHtml,/<span class="source-health-status-badge">狀態未知<\/span>/);
assert.match(unknownHtml,/<span class="source-health-tag">已讀取<\/span>/);

const healthyPage=ui.buildSourceHealthView({page_state:null,sources:[{key:'healthy',authorized:true,health:'healthy',name:'工程來源'}]},{diagnosticCapability:true});
const healthyHtml=renderToStaticMarkup(React.createElement(ui.SourceHealth,{view:healthyPage}));
assert.match(healthyHtml,/<span class="source-health-status-badge">已讀取<\/span>/,'a healthy page reported as null shows 已讀取');
const unrowedHtml=renderToStaticMarkup(React.createElement(ui.SourceHealth,{view:ui.buildSourceHealthView({page_state:null,sources:[]},{diagnosticCapability:true})}));
assert.match(unrowedHtml,/<span class="source-health-status-badge">狀態未知<\/span>/,'no rows and no reported state stays unknown');
