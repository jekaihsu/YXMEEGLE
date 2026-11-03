import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {chromium} from 'playwright-core';
const output=process.env.CASE_SIMPLIFY_SHOTS||'/Users/vc/Local/review-artifacts/cd-simplify/impl-flow';
const origin=process.env.CASE_SIMPLIFY_URL||'http://localhost:5301';
await mkdir(output,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const context=await browser.newContext();
const errors=[],writes=[],results=[];
await context.route('**/api/**',route=>{if(!['GET','HEAD','OPTIONS'].includes(route.request().method())){writes.push(route.request().url());return route.abort()}return route.continue()});
const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
try{
 await page.goto(origin+'/api/session');
 for(const width of [1280,390]){
  await page.setViewportSize({width,height:width===1280?800:844});
  for(const project of ['p1','p6'])for(const tab of ['overview','flow']){
   await page.goto(`${origin}/#view=project&project=${project}&tab=${tab}`);
   await page.locator('#flow-tasks').waitFor();
   await page.waitForTimeout(600);
   assert.equal(await page.locator('.cs-stale').count(),0);
   assert.doesNotMatch(await page.locator('body').innerText(),/資料為上次成功讀取|上次成功資料，待更新|讀取時間/);
   const measurement=await page.evaluate(()=>({height:document.documentElement.scrollHeight,width:document.documentElement.scrollWidth,viewport:innerWidth,selected:(()=>{const e=document.querySelector('.pf-node[aria-current]'),chain=document.querySelector('.pf-chain');if(!e||!chain)return null;const b=e.getBoundingClientRect(),v=chain.getBoundingClientRect();return {left:b.left,right:b.right,viewportLeft:v.left,viewportRight:Math.min(v.right,innerWidth)}})()}));
   assert.ok(measurement.width<=width,`horizontal overflow: ${JSON.stringify(measurement)}`);
   if(tab==='overview'){assert.equal(await page.locator('.i3-stepper.pf-diagram').count(),1);assert.equal(await page.locator('.po-next-action').count(),1);assert.equal(await page.locator('#flow-tasks').count(),1);if(width===1280)assert.ok(measurement.height<=1800,`overview height ${measurement.height}`)}
   if(tab==='flow'&&measurement.selected){const s=measurement.selected;assert.ok(s.left>=s.viewportLeft-1&&s.right<=s.viewportRight+1,'selected stage visible initially')}
   const path=`${output}/${project}-${tab}-${width}.png`;await page.screenshot({path,fullPage:true});results.push({project,tab,...measurement,path});
  }
 }
 const workspace=await context.request.get(origin+'/api/workspace');
 const body=await workspace.json();const projects=body.projects||body.workspace?.projects||[];
 const statuses=[...new Set(projects.map(p=>p.status))];
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
 await writeFile(output+'/verification.json',JSON.stringify({results,statuses,closedProjects:projects.filter(p=>p.status==='closed').map(p=>p.id),errors,writes},null,2));
 console.log(JSON.stringify({results,statuses,closedObserved:statuses.includes('closed'),errors,writes},null,2));
}finally{await browser.close()}
