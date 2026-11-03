import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const b=await build({stdin:{contents:"export {ReportLinkSummary} from './src/ReportLinkSummary';export {CaseFinanceSources} from './src/CaseFinanceSources';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.live3-presentation.mjs',import.meta.url);await fs.writeFile(file,b.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await fs.unlink(file)}
const html=renderToStaticMarkup(React.createElement(ui.ReportLinkSummary,{projectId:'115575',initial:{linked:0,total:535,unlinked:535,departments:{},reasons:{}}}));
assert.match(html,/本案已連結 0 筆/);assert.match(html,/全公司待配對 535 筆/);assert.doesNotMatch(html,/0 \/ 535/);assert.match(html,/來源時間.*來源未提供/);
console.log('PASS LIVE3 case daily-report scope and unknown source time');

const finance=renderToStaticMarkup(React.createElement(ui.CaseFinanceSources,{p:{contract_amount:47000,contract_amount_as_of:'2026-11-03T02:41:47Z',source_projection:{finance:{contract_amount:94000,as_of:'2026-11-02T02:41:47Z'}}}}));
assert.match(finance,/金額來源不一致/);assert.match(finance,/基本資料金額/);assert.match(finance,/NT\$47,000/);assert.match(finance,/合約來源金額/);assert.match(finance,/NT\$94,000/);assert.match(finance,/2026\/11\/03 10:41:47/);assert.match(finance,/2026\/11\/02 10:41:47/);
console.log('PASS LIVE3 named finance amounts and independent source times');
