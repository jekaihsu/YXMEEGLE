import {chromium} from '../../.runtime/qa/node_modules/playwright-core/index.mjs';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const results=[],errors=[];page.on('pageerror',e=>errors.push(String(e)));
const screenshot=async name=>page.screenshot({path:`output/qa-fixes-ui/${name}.png`,fullPage:true,animations:'disabled'});
for(const tab of ['assigned','delegated','local']){
 await page.goto(`http://localhost:5299/#view=work&tab=${tab}`);
 await page.getByRole('heading',{name:'我的工作',exact:true}).waitFor();
 assert.equal(await page.locator('.breadcrumbs strong').innerText(),'我的工作');
 await screenshot(`work-${tab}-1440`);
 await page.reload();await page.getByRole('heading',{name:'我的工作',exact:true}).waitFor();
 assert.equal(await page.locator('.breadcrumbs strong').innerText(),'我的工作');
 results.push(`work ${tab} and direct reload passed`);
}
const devHealth=await (await page.request.get('http://localhost:5299/api/health')).json();assert.equal(devHealth.build,null);
const stageHealth=await (await page.request.get('http://localhost:8877/api/health')).json();assert.match(stageHealth.build.git_sha,/^[a-f0-9]{40}$/);assert.equal(typeof stageHealth.build.dirty,'boolean');
await fs.writeFile('output/qa-fixes-ui/health.json',JSON.stringify({dev:devHealth,staged:stageHealth},null,2));
await page.route('**/api/health',route=>route.fulfill({json:stageHealth}));
const stamp='2026-10-26T00:00:00.000Z';
let sourceRetry=0;
const sources={page_state:{states:['read_failed']},sources:[
 {key:'fixture-fresh',authorized:true,name:'工程確認單',health:'healthy',last_success:stamp,read_authorized:true,retry_handle:{dataset:'sources'}},
 {key:'fixture-stale',authorized:true,name:'合約工項',data_state:{states:['stale']},last_success:'2026-10-24T00:00:00.000Z',read_authorized:true,retry_handle:{dataset:'sources'}},
 {key:'fixture-failed',authorized:true,name:'外業日報',data_state:{states:['read_failed']},last_success:stamp,last_error_summary:'來源讀取失敗',read_authorized:true,retry_handle:{dataset:'sources'}},
 {key:'fixture-unknown',authorized:true,name:'班表',data_state:{states:['unknown']},read_authorized:true,retry_handle:{dataset:'sources'}}]};
await page.route('**/api/source-health',route=>route.fulfill({json:sources}));
const fresh=await (await page.request.get('http://localhost:5299/api/live/status')).json();
await page.route('**/api/live/refresh',async route=>{assert.deepEqual(route.request().postDataJSON(),{datasets:['sources'],wait:true,force:true});sourceRetry++;await route.fulfill({json:fresh});});
await page.goto('http://localhost:5299/#view=sources');await page.getByRole('heading',{name:'來源與資料健康',exact:true}).waitFor();
await page.getByText(`版本 ${stageHealth.build.git_sha.slice(0,7)}`,{exact:false}).waitFor();
const sourceText=await page.locator('.source-health-root').innerText();assert.match(sourceText,/2026\/10\/26 08:00:00/);assert.match(sourceText,/前/);assert.match(sourceText,/尚無成功紀錄/);assert.match(sourceText,/來源讀取失敗/);assert.doesNotMatch(sourceText,/fixture-|來源代碼|對應未驗證/);
await screenshot('sources-1440');await page.setViewportSize({width:390,height:844});await screenshot('sources-390');
assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'source page has no horizontal overflow');
await page.getByRole('button',{name:'重試',exact:true}).first().click();await page.waitForTimeout(400);assert.equal(sourceRetry,1);results.push('source details, Taipei times, missing timestamps, safe errors, forced retry and build identity passed at 1440/390');
await page.setViewportSize({width:1440,height:1000});
const ws=await (await page.request.get('http://localhost:5299/api/workspace')).json();const id=ws.projects[0].id;
const fixture=JSON.parse(await fs.readFile('frontend/fixtures/project-progress.json','utf8'));fixture.project_id=id;fixture.sources.source_synced_at=new Date().toISOString();fixture.sources.reports_fetched_at=fixture.sources.source_synced_at;
let mode='timeout',calls=0;
await page.route('**/api/projects/*/progress',async route=>{calls++;const state=mode;if(state==='timeout'){await new Promise(r=>setTimeout(r,31000));try{await route.fulfill({status:504,json:{detail:'讀取逾時，請重試'}})}catch{}return;}
 const data=structuredClone(fixture);if(state==='stale'){data.sources.source_status='stale';data.sources.reports_stale=true;}
 await route.fulfill({json:data});});
await page.goto(`http://localhost:5299/#view=project&project=${id}&tab=items`);
await page.getByRole('heading',{name:'工程證據暫不可用',exact:true}).waitFor({timeout:40000});await screenshot('items-timeout-1440');
mode='stale';await page.getByRole('button',{name:'重試工程證據',exact:true}).click();await page.getByText('無法更新工程證據，請重試。',{exact:true}).waitFor();
assert.equal(await page.locator('[data-item-id]').count(),0);assert.match(await page.locator('.wi-card[role=alert]').innerText(),/最近成功讀取/);await screenshot('items-retry-failed-1440');await page.setViewportSize({width:390,height:844});await screenshot('items-retry-failed-390');
mode='fresh';await page.getByRole('button',{name:'重試工程證據',exact:true}).click();await page.locator('[data-item-id]').first().waitFor();assert.equal(await page.locator('[data-item-id]').count(),3);assert.equal(await page.locator('.wi-card[role=alert]').count(),0);assert.doesNotMatch(await page.locator('.wi-evidence').innerText(),/過期/);await screenshot('items-retry-fresh-390');await page.setViewportSize({width:1440,height:1000});await screenshot('items-retry-fresh-1440');
assert.equal(calls,3);results.push('real 30-second timeout followed by stale failure then independent fresh retry passed');results.push('dev build null and staged health metadata matched manifest');assert.deepEqual(errors,[]);results.push('no browser page errors');
await fs.writeFile('output/qa-fixes-ui/browser-results.json',JSON.stringify({results,progressRequests:calls,sourceRetries:sourceRetry,errors},null,2));console.log(results.join('\n'));await browser.close();
