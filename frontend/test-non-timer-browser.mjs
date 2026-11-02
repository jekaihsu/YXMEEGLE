// Run against the isolated DEMO_MODE instance; API edge cases are synthetic.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
globalThis.location={search:''};
const base=process.env.REVIEW_URL||'http://localhost:5213';
const bundle=await build({stdin:{contents:"export {mockReport} from './src/reports/mock'",resolveDir:process.cwd()},bundle:true,write:false,format:'esm',platform:'node'});
const file=new URL('./.browser-report.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);let mockReport;try{({mockReport}=await import(file.href))}finally{await fs.unlink(file)}
const {variants}=JSON.parse(await fs.readFile('fixtures/dispatchBoardSample.json','utf8'));
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install();
 await page.route('**/api/session',async route=>{const response=await route.fetch();const session=await response.json();session.mode='lark';session.workspace_id='isolated-review';session.features={...session.features,dispatch_board:true,dispatch_write:false};session.user={...session.user,role:'manager'};return route.fulfill({json:session})});
 await page.goto(base+'/#view=dispatch');
 await page.waitForSelector('.app-shell, .app, nav');
 await page.route('**/api/v2/dispatch/board?*',route=>{calls.push(route.request().url());const query=new URL(route.request().url()).searchParams;const board=structuredClone(variants.loaded);board.window={from:query.get('from'),to:query.get('to'),tz:'Asia/Taipei'};board.source.quality.states=['partial'];board.source.joins={...board.source.joins,cases:'unavailable'};return route.fulfill({json:board})});
 await page.reload();
 // Dispatch defaults to work; select its board tab when needed.
 const boardTab=page.getByRole('button',{name:'派工看板',exact:true});if(await boardTab.count())await boardTab.click();
 await page.waitForSelector('.dispatch-board');await page.waitForFunction(()=>!document.querySelector('.db-skeleton'));
 const dispatchBefore=calls.length;assert.ok(dispatchBefore>0);
 for(const gap of [1562,1789,1719,1650,1967,1656,1593,1626]){
  await page.clock.runFor(gap);assert.equal(calls.length,dispatchBefore,'staging eight-GET passive burst must not recur');
 }
 await page.clock.fastForward(600000);assert.equal(calls.length,dispatchBefore);
 await page.getByRole('button',{name:'重新讀取',exact:true}).click();await page.waitForTimeout(1);assert.equal(calls.length,dispatchBefore+1);
 await page.screenshot({path:'/tmp/yx-rd-C-review/dispatch.png',fullPage:true});
 let reportOffline=false;
 await page.route('**/api/reports/**',route=>{const url=new URL(route.request().url());calls.push(url.pathname);if(route.request().method()==='POST')return route.fulfill({status:202,json:{}});if(reportOffline)return route.fulfill({status:503,json:{detail:'fixture offline'}});const data=mockReport(url.pathname.replace('/api/reports/',''),url.searchParams);data.meta.can_refresh=true;return route.fulfill({json:data})});
 await page.goto(base+'/#view=reports&tab=progress');await page.getByRole('button',{name:'重新整理資料',exact:true}).waitFor();
 let before=calls.length;await page.getByRole('button',{name:'重新整理資料',exact:true}).click();await page.getByRole('button',{name:'查看更新結果',exact:true}).waitFor();assert.equal(calls.length,before+1);
 before=calls.length;await page.clock.fastForward(600000);assert.equal(calls.length,before);
 reportOffline=true;
 await page.getByRole('button',{name:'查看更新結果',exact:true}).click();await page.waitForTimeout(1);assert.equal(calls.length,before+1);
 await page.getByRole('alert').filter({hasText:'保留上次成功報表'}).waitFor();
 assert.ok(await page.locator('tbody tr').count(),'last successful report rows survive a failed refresh');
 before=calls.length;await page.clock.fastForward(600000);assert.equal(calls.length,before);
 reportOffline=false;await page.getByRole('button',{name:'重試',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'保留上次成功報表'}).waitFor({state:'detached'});assert.equal(calls.length,before+1);
 await page.screenshot({path:'/tmp/yx-rd-C-review/report.png',fullPage:true});assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',dispatch:{stagingPassiveExtra:8,fixturePassiveExtra:0,initial:dispatchBefore,tenMinutes:dispatchBefore,manual:dispatchBefore+1},report202:{post:1,tenMinutesExtra:0,manualResult:1},screenshots:'/tmp/yx-rd-C-review/{dispatch,report}.png'}));
}finally{await browser.close()}
