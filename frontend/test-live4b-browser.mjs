import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {chromium} from 'playwright-core';
const base=process.env.YX_LIVE4B_DEMO_URL;
if(!base){console.log('SKIP: set YX_LIVE4B_DEMO_URL to the isolated demo Vite URL');process.exit(0)}
assert(['localhost','127.0.0.1'].includes(new URL(base).hostname));
const dir=process.env.YX_LIVE4B_EVIDENCE;
if(dir)await fs.mkdir(dir,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[],measurements=[];
page.on('pageerror',e=>errors.push(e.message));
const session=await (await context.request.get(base+'/api/session')).json();assert.equal(session.mode,'demo');
await page.route('**/api/workspace*',async route=>{const response=await route.fetch(),data=await response.json();const originals=data.projects;assert(originals.length);data.projects=Array.from({length:398},(_,i)=>({...originals[i%originals.length],id:'fixture-'+i,code:'DEMO-'+i,name:`示範案件 ${i+1} · ${originals[i%originals.length].name}`}));await route.fulfill({response,json:data})});
const saved={id:'live4b-saved',title:'昨日出勤回答',scope:'global',project_id:null,updated_at:'2026-11-02T10:39:00Z',turns:1,authorization_basis:'legacy_workspace'};
await page.route('**/api/reports/assets?**',route=>route.fulfill({json:{meta:{fetched_at:'2026-11-03T02:00:00Z',stale:false,gaps:[{id:'asset-vehicle-coverage',severity:'warn',message:'0 / 189 張成本單有車輛紀錄'}]},kind:'vehicle',kpi:{total:21,active:21,in_use:0,idle:21,coverage:0,repair:0,km:null,daily_rent_total:null},options:{},by_category:[],usage_trend:[],items:[{id:'a',name:'示範車輛',status:'正常',uses:0,last_used:'2026-08-01',idle_days:99,link:'https://example.invalid/source'}],total:1,offset:0,limit:50}}));
await page.route('**/api/ai/models',route=>route.fulfill({json:{default:'claude',models:[{id:'claude',label:'Claude',available:true}]}}));
await page.route('**/api/ai/conversations**',route=>route.fulfill({json:new URL(route.request().url()).pathname.endsWith(saved.id)?{...saved,messages:[{role:'user',content:'誰遲到？',at:saved.updated_at},{role:'assistant',content:'截至今天 18:39，出勤資料如下。',at:saved.updated_at}]}:{history_available:true,items:[saved],next_cursor:null}}));
async function shot(name){if(dir)await page.screenshot({path:`${dir}/${name}.png`})}
async function go(view,mock=true){await page.goto(base+`/${mock?'?mock=1':''}#view=`+view);await page.waitForTimeout(700)}
async function targets(name,selector){await page.locator(selector).first().waitFor();const rows=await page.locator(selector).evaluateAll(es=>es.map(e=>({text:e.innerText||e.getAttribute('aria-label'),w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height})).filter(r=>r.w&&r.h));measurements.push({name,rows});for(const r of rows)assert(r.w>=44&&r.h>=44,`${name}: ${JSON.stringify(r)}`)}
try{
 await go('reports&tab=sales');await targets('reports-filters-sort-source','.reports-filters .ds-picker>button,.reports-filters input,.reports-sort>button,.reports th button,.reports-link');await shot('after-sales-1440');
 const progress=await page.evaluate(async()=>{const {mockReport}=await import('/src/reports/mock.ts');return mockReport('progress',new URLSearchParams())});progress.meta.can_refresh=true;await page.route('**/api/reports/progress?**',route=>route.fulfill({json:progress}));
 await go('reports&tab=progress',false);await targets('week-refresh','.reports-week button,.reports-meta button,.reports>div>div>button');await targets('progress-raw-refresh','.reports button:not(.ds-button)');await shot('after-progress-1440');
 await go('confirmations');await targets('confirmation-search-select','.confirmation-list-root input:not([type=checkbox]),.confirmation-list-root select');await shot('after-confirmations-1440');
 await page.evaluate(async()=>{await import('/src/p2-detail.css');const a=document.createElement('a');a.href='https://example.invalid/source';a.className='p2-cell-link';a.textContent='授權來源';document.querySelector('.workspace').append(a)});await targets('shared-confirmation-source','a.p2-cell-link');
 await go('projects');await targets('project-name','.pl-title');assert.match(await page.locator('.pl-page').innerText(),/398/);await shot('after-projects-398-1440');
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:/^篩選/}).first().click();
 for(const theme of ['light','dark']){
  await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);await page.waitForTimeout(250);
  const paint=await page.locator('.ds-sheet').evaluate(e=>{const s=getComputedStyle(e);return {bg:s.backgroundColor,fg:s.color,backdrop:getComputedStyle(e.parentElement).backgroundColor}});
  assert.match(paint.bg,/^rgb\(/,'sheet is fully opaque');assert.notEqual(paint.bg,paint.backdrop,'independent backdrop');const lum=c=>{const a=c.match(/[\d.]+/g).slice(0,3).map(v=>Number(v)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return a[0]*.2126+a[1]*.7152+a[2]*.0722};const ls=[lum(paint.bg),lum(paint.fg)].sort((a,b)=>b-a);paint.contrast=(ls[0]+.05)/(ls[1]+.05);assert(paint.contrast>=4.5);measurements.push({theme,paint});await shot(`after-filter-398-${theme}-390`);
 }
 await go('howto&section=refresh');assert.match(await page.locator('#refresh').innerText(),/切換視窗或分頁 → 保留目前資料/);assert.equal(await page.locator('#refresh img').count(),0);await shot('after-guide-390');
 await page.setViewportSize({width:1440,height:1000});await go('reports&tab=assets',false);await page.getByText('0 / 189 張成本單有車輛紀錄',{exact:false}).first().waitFor({state:'attached'});const asset=await page.locator('.reports').innerText();assert.match(asset,/已記錄使用次數/);assert.match(asset,/距最近已知紀錄/);assert.doesNotMatch(asset,/閒置/);await targets('report-source','.reports-link');await shot('after-assets-1440');await page.locator('.reports-table-scroll').scrollIntoViewIfNeeded();await shot('after-assets-records-1440');
 await page.setViewportSize({width:1440,height:1000});await go('assistant',false);await page.locator('.assistant-history-open').click();await page.locator('.assistant-saved-date').waitFor();const answer=await page.locator('[data-role=assistant]').innerText();assert.match(answer,/歷史回答.*2026\/11\/02 18:39:00/);assert.match(answer,/來源時間未提供/);assert.match(answer,/截至今天/);await shot('after-history-1440');
 await page.setViewportSize({width:390,height:844});await shot('after-history-390');
 assert.deepEqual(errors,[]);console.log('LIVE4B browser targets, 398-case synthetic sheet, guide and saved-history regressions passed');
}finally{if(dir)await fs.writeFile(dir+'/browser-regressions.json',JSON.stringify({measurements,errors},null,2));await browser.close()}
