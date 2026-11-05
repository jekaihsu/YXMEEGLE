import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {JSDOM} from 'jsdom';
const bundle=await build({stdin:{contents:"export {CaseDetailSkeleton} from './src/DetailLoadingSkeleton';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.detail-skeleton-test.mjs',import.meta.url);
await fs.writeFile(file,bundle.outputFiles[0].text);
let ui;try{ui=await import(file.href)}finally{await fs.unlink(file)}
const dom=new JSDOM(renderToStaticMarkup(React.createElement(ui.CaseDetailSkeleton)));
const doc=dom.window.document;
assert.equal(doc.querySelector('[role=status]').textContent,'正在載入案件詳細內容…');
assert.equal(doc.querySelector('[role=status]').closest('[aria-hidden=true]'),null);
assert.deepEqual([...doc.querySelectorAll('h2')].map(h=>h.textContent),['總覽','確認單版本','合約明細','工項','流程節點／SOP','報告與文件','歷程']);
assert.equal(doc.querySelectorAll('.detail-table-placeholder-row').length,21);
assert.equal(doc.querySelectorAll('.case-detail-placeholder-fields > *').length,8);
assert.equal(doc.querySelectorAll('aside').length,1);
dom.window.close();console.log('PASS case detail skeleton: announced loading, header, seven sections, tables and sidebar');
