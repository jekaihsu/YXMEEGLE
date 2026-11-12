import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
const base=process.argv[2]||'http://[::1]:5200/';
const browser=await chromium.launch({channel:'chrome',headless:true});
try{for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:900}}),requests=[];
 page.on('request',request=>requests.push(request.url()));
 await page.goto(`${base}?perf=1#view=project&project=p1&tab=overview&node=confirmation`);
 await page.locator('.po-next:not([aria-busy=true])').waitFor();
 const state=await page.evaluate(()=>{const summary=document.querySelector('.po-next'),todo=document.querySelector('.po-todos'),background=[...document.querySelectorAll('summary')].find(e=>e.textContent==='節點說明與背景');return {top:summary.getBoundingClientRect().top,summary:summary.innerText,todoBeforeBackground:!!(todo.compareDocumentPosition(background)&Node.DOCUMENT_POSITION_FOLLOWING)}});
 assert(state.top>=0&&state.top<900,'opening a node link keeps next steps on screen');assert.match(state.summary,/停留節點/);assert.match(state.summary,/原因/);assert.match(state.summary,/下一步/);assert(state.todoBeforeBackground);
 assert(!requests.some(url=>url.includes('/api/report-links/summary')),'collapsed report section does not fetch');
 assert(!requests.some(url=>/assets\/(Operations|DispatchPublish|PeopleDirectoryPanel)-/.test(url)),'secondary bundles do not block the case');
 await page.getByText('日報連結與核對',{exact:true}).click();await page.waitForResponse(response=>response.url().includes('/api/report-links/summary'));
 console.log(JSON.stringify({width,status:'pass',...state}));await page.close();
}}finally{await browser.close()}
