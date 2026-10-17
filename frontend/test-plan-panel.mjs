import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFileSync,unlinkSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {JSDOM} from 'jsdom';
import {formatPlanQuantity,hasPlanDerivation} from './src/caseDetailView.ts';
const bundle=await build({entryPoints:['src/CaseDetail.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.plan-panel-test.mjs',import.meta.url);writeFileSync(path,bundle.outputFiles[0].text);
let Panel;try {Panel=(await import(path.href)).PlanQuantityPanel;} finally {unlinkSync(path);}
const summary={basis:{native:0,derived:0,ambiguous:0,unlinked:0,native_unresolved:0},lines_basis:{native:0,derived:0},categories:{},needsReview:true,truncated:true};
for(const [i,k] of ['外業','控制','圖資','報告'].entries()) summary.categories[k]={lines:i+1,planned_qty:['1.2300','1E+3','0.00000001','0E+1'][i],items:i+5,items_native:i+9,items_derived:0,items_ambiguous:0,items_unlinked:i+13,items_native_unresolved:0,needs_review:0};
const render=s=>new JSDOM(renderToStaticMarkup(React.createElement(Panel,{summary:s}))).window.document;
for(const [input,expected] of [['1.2300','1.23'],['1E+3','1000'],['1e-8','0.00000001'],['0E+1','0'],['000.000','0'],['-0.000','0']]) assert.equal(formatPlanQuantity(input),expected);
assert.equal(hasPlanDerivation(summary),false);
for(const mutate of [s=>s.basis.derived=1,s=>s.basis.ambiguous=1,s=>s.lines_basis.derived=1,s=>s.categories.控制.items_derived=1,s=>s.categories.圖資.items_ambiguous=1]) {const s=structuredClone(summary);mutate(s);assert.equal(hasPlanDerivation(s),true);}
summary.lines_basis.derived=1;
const doc=render(summary);
assert.deepEqual([...doc.querySelectorAll('tbody tr')].map(r=>[...r.querySelectorAll('th,td')].slice(0,4).map(c=>c.textContent)),[['外業','1','1.23','5'],['控制','2','1000','6'],['圖資','3','0.00000001','7'],['報告','4','0','8']]);
assert.ok(doc.body.textContent.includes('需人工確認：重複的合約項未計入總量'));
assert.ok(doc.body.textContent.includes('含依工編推導或待確認的關聯，非 Lark 原生關聯'));
assert.equal(doc.querySelector('section').getAttribute('aria-labelledby'),doc.querySelector('h3').id);
summary.categories.控制.lines=0;summary.categories.控制.items=0;
assert.deepEqual([...render(summary).querySelectorAll('tbody th')].map(x=>x.textContent),['外業','圖資','報告']);
for(const c of Object.values(summary.categories)){c.lines=0;c.items=0;}
for(const value of [null,summary]) {const d=render(value);assert.equal(d.querySelectorAll('table').length,0);assert.ok(d.body.textContent.includes('尚無計畫數量資料'));}
assert.ok(render('unavailable').body.textContent.includes('計畫數量無法顯示'));
console.log('plan panel: 8 behavior groups passed');
