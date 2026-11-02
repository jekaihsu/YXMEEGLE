import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import {chromium} from 'playwright-core';
const backend=process.env.YX_CASE_DEMO_API_URL;
if(!backend){console.log('SKIP real case demo: set YX_CASE_DEMO_API_URL to an isolated loopback backend');process.exit(0)}
assert(backend&&['localhost','127.0.0.1'].includes(new URL(backend).hostname),'YX_CASE_DEMO_API_URL must name an isolated loopback demo backend');
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const context=await browser.newContext();
 const first=await (await context.request.get(new URL('/api/session',backend).href)).json();assert.equal(first.mode,'demo');
 const manager=first.users.find(u=>u.role==='manager');assert(manager,'demo manager fixture required for shell mode');
 assert.equal((await context.request.post(new URL('/api/demo/session',backend).href,{data:{user_id:manager.id}})).status(),200);
 const session=await (await context.request.get(new URL('/api/session',backend).href)).json();assert.equal(session.features.workspace_shell,true);
 const workspace=await (await context.request.get(new URL('/api/workspace',backend).href)).json();const id=workspace.projects[0].id;
 const page=await context.newPage(),base='http://127.0.0.1:52882',reads=[],errors=[];
 page.on('pageerror',error=>errors.push(error.message));await page.clock.install({time:new Date('2026-11-02T15:00:00Z')});
 await page.route(base+'/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname.startsWith('/api/')){
   if(route.request().method()==='GET'&&url.pathname.startsWith('/api/projects/'+id))reads.push(url.pathname+url.search);
   return route.fulfill({response:await route.fetch({url:new URL(url.pathname+url.search,backend).href})});
  }
  const path=url.pathname==='/'?'index.html':url.pathname.slice(1);
  try{return route.fulfill({body:await readFile(resolve(import.meta.dirname,'dist',path)),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[extname(path)]||'application/octet-stream'})}
  catch{return route.fulfill({status:404,body:'Not found'})}
 });
 await page.goto(base+'/#view=project&project='+id);await page.waitForLoadState('networkidle');
 const freshness=page.locator('[data-snapshot-id]');await freshness.waitFor();assert.match(await freshness.innerText(),/資料時間/);
 const snapshotId=await freshness.getAttribute('data-snapshot-id');assert(snapshotId);
 await page.getByRole('button',{name:'流程與任務',exact:true}).click();await page.waitForLoadState('networkidle');
 const initial=reads.length;assert(initial>0);
 await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('blur'))});
 await page.clock.fastForward(600000);
 await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});for(const name of ['focus','visibilitychange','online','yx:mutation-state']){window.dispatchEvent(new Event(name));document.dispatchEvent(new Event(name))}});
 await page.getByRole('button',{name:'總覽',exact:true}).click();await page.getByRole('button',{name:'流程與任務',exact:true}).click();await page.waitForLoadState('networkidle');
 assert.equal(reads.length,initial,'ten minute away and tab round-trip add zero case reads');
 await freshness.getByRole('button',{name:'重新整理',exact:true}).click();await page.waitForFunction(()=>!document.body.textContent.includes('正在更新案件資料'));await page.waitForLoadState('networkidle');
 const batch=reads.slice(initial);assert.equal(batch.length,3,'one first-screen, assignees and progress refresh batch');assert.equal(new Set(batch).size,3);assert.equal(batch.filter(url=>url.endsWith('/first-screen')).length,1);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',realDemo:true,case:id,initialReads:initial,afterTenMinutes:initial,idleReads:0,explicitRefreshBatches:1,refreshReads:batch,snapshotId,sourceLabel:await freshness.innerText()}));
}finally{await browser.close()}
