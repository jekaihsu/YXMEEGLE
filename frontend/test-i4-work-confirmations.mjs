import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {confirmationFixture} from './fixtures/confirmation-detail.mjs';
const bundle=await build({stdin:{contents:"export {CaseDetail,PlanQuantityPanel} from './src/CaseDetail'; export {buildCaseDetailView} from './src/caseDetailView'; export {ConfirmationList} from './src/ConfirmationList'; export {buildConfirmationListView} from './src/confirmationListView'; export {DisabledApprovals} from './src/DisabledApprovals'; export {ContractDetail} from './src/ContractDetail'; export {buildContractDetailView} from './src/contractDetailView'; export {WorkItemDetail} from './src/WorkItemDetail'; export {buildWorkItemDetailView} from './src/workItemDetailView'; export {plainReason} from './src/workPresentation';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const file=new URL('./.i4-test.mjs',import.meta.url);await writeFile(file,bundle.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await unlink(file)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=confirmation'});
for(const key of ['window','document','location','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const root=createRoot(document.getElementById('root'));
const render=async(component,props)=>act(async()=>root.render(React.createElement(component,props)));
const fixture=confirmationFixture();fixture.page_state=[];fixture.sections.overview.reason='header_carries_summary';
await render(ui.CaseDetail,{view:ui.buildCaseDetailView(fixture)});
assert.match(document.body.textContent,/部分資料未驗證/);
assert.match(document.body.textContent,/不是 0，也不是沒有資料/);
assert.match(document.body.textContent,/2026\/10\/14 09:00/);
assert.doesNotMatch(document.getElementById('root').innerHTML,/receipt_missing|header_carries_summary|no_authorized_parent_edge|not_in_authorized_view/);
assert.match(document.body.textContent,/未開始/);
assert.match(document.body.textContent,/計畫數量待核對/);
assert.equal(document.querySelectorAll('[id^="confirmation-section-"]').length,7);
assert.equal(ui.plainReason('no_authorized_parent_edge'),'找不到可檢視的上層關聯，對應尚未驗證');
assert.equal(ui.plainReason('unrecognized_internal_reason'),'來源或作業條件待核對，請聯絡管理者');
for(const code of ['stale','timeout','withheld','G-OWNER','R01','unrecognized_internal_reason']){
 assert.equal(ui.plainReason(code),'來源或作業條件待核對，請聯絡管理者',code+' cannot leak');
}
assert.equal(ui.plainReason('請先確認現場條件'),'請先確認現場條件');
for(const [state,kind,title] of [['forbidden','Denied','你目前無法查看此確認單'],['read_failed','Error','無法載入確認單'],['partial','Partial','部分資料未驗證']]){
 const blank=ui.buildCaseDetailView({project_id:'unavailable',page_state:[state],header:null,sections:{},reason:'timeout'});
 await render(ui.CaseDetail,{view:blank});
 assert.equal(document.querySelector('.ds-data-state strong')?.textContent,title);
 assert.equal(document.querySelector('.ds-data-state')?.dataset.kind,kind);
 assert.equal(document.querySelector('h1')?.textContent,'工程確認單');
 // Also cover retained/header-populated view props, where the misleading title originally lived.
 await render(ui.CaseDetail,{view:{...ui.buildCaseDetailView(fixture),page:{states:[state],label:state,reason:null}}});
 assert.equal(document.querySelector('.ds-data-state strong')?.textContent,title);
}
let home=0;await render(ui.DisabledApprovals,{onHome:()=>home++});
assert.match(document.body.textContent,/不能新增申請，也不會有待審項目/);
assert.equal(document.querySelectorAll('table,tbody tr,details,main').length,0,'disabled page has no fabricated rows or nested main');
assert.equal(document.querySelector('[aria-labelledby="approvals-disabled-title"]')?.tagName,'SECTION');
assert.equal(document.querySelector('[data-kind="Partial"]'),null,'deliberately disabled is not a partial-read warning');
assert.doesNotMatch(document.body.textContent,/示意|待辦狀態尚未取得/);
assert.deepEqual([...document.querySelectorAll('button')].map(x=>x.textContent),['回今日工作台']);
await act(async()=>document.querySelector('button').click());assert.equal(home,1);
await render(ui.ContractDetail,{view:ui.buildContractDetailView({page_state:{states:['forbidden']}})});
assert.match(document.body.textContent,/目前無法開啟關聯內容/);
assert.equal(document.querySelectorAll('[data-kind="Denied"]').length,1);
assert.equal(document.querySelectorAll('table').length,0);
await render(ui.WorkItemDetail,{view:ui.buildWorkItemDetailView({body:{read_state:{states:['forbidden']}}})});
assert.match(document.body.textContent,/系統不會推測關聯/);
assert.equal(document.querySelectorAll('[data-kind="Denied"]').length,1);
await render(ui.ContractDetail,{view:ui.buildContractDetailView({page_state:{states:['unlocated']}})});
assert.equal(document.querySelector('.ds-data-state')?.dataset.kind,'Partial');
await render(ui.WorkItemDetail,{view:ui.buildWorkItemDetailView({body:{read_state:{states:['unlocated']}}})});
assert.equal(document.querySelector('.ds-data-state')?.dataset.kind,'Partial');
await render(ui.ConfirmationList,{view:ui.buildConfirmationListView({status:403})});
assert.match(document.body.textContent,/沒有權限檢視工程確認單/);
assert.equal(document.querySelector('[hidden]')?.className,'p2-toolbar-primary-right');
assert.equal(document.querySelector('.confirmation-list-layout').hidden,true);
await act(async()=>root.unmount());
console.log('I4: partial copy, translated reasons, known-vs-unknown plan counts, Taipei times, stable sections, disabled history copy without fabricated rows, denied unresolved pages and list passed');
