// 案件資料 基本資料 must not say 未提供 when the source row holds an amount the workbench withholds (gate G-AMT).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
const bundle=await build({stdin:{contents:"export {amountWithheld,amountLabel,money} from './src/appCommon';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.amount-label-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const withheld={contract_amount:null,source_projection:{finance:{contract_amount:100000,estimated_cost:null,actual_cost:0,verified:false,readonly:true}}};
assert.equal(ui.amountWithheld(withheld),true);
assert.equal(ui.amountLabel(withheld),'未核准顯示');
const approved={contract_amount:80000,source_projection:withheld.source_projection};
assert.equal(ui.amountWithheld(approved),false);
assert.equal(ui.amountLabel(approved),'NT$ 80,000');
const sourceEmpty={contract_amount:null,source_projection:{finance:{contract_amount:null}}};
assert.equal(ui.amountWithheld(sourceEmpty),false);
assert.equal(ui.amountLabel(sourceEmpty),'待帶入');
assert.equal(ui.amountWithheld({contract_amount:null}),false);
console.log('Withheld source amounts are labelled 未核准顯示, never 未提供');
