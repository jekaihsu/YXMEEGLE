import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {chromium} from '/Users/vc/Local/review-artifacts/cd-simplify/node_modules/playwright-core/index.mjs';
const base='http://localhost:5451',output='/Users/vc/Local/review-artifacts/cd-simplify/fix3-flow';
await mkdir(output,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true});
const causes={paused:'案件暫停中，等待林育寬處理。',source:'來源案件狀態待核對；未確認前不自動啟用工作',intake:'接案尚未轉正式案件',closed:'來源標示結案；工作台待核對，不自動重新啟用工作',schedule:'尚未排定開始日期'};
const writes=[],errors=[];
try{
 for(const width of [1280,390])for(const [name,cause] of Object.entries({live:null,...causes})){
  const context=await browser.newContext({viewport:{width,height:width===1280?900:844}});
  await context.route('**/api/**',async route=>{
   if(!['GET','HEAD','OPTIONS'].includes(route.request().method())){writes.push(route.request().url());return route.abort()}
   if(cause&&/\/api\/workspace(?:\?|$)/.test(route.request().url())){
    const response=await route.fetch(),data=await response.json(),project=data.projects.find(p=>p.id==='p3');
    if(name==='paused')project.status='paused';
    for(const task of project.nodes.find(n=>n.key==='field').tasks){task.status='pending';task.execution_blockers=name==='schedule'?[cause]:['案件已暫停、結案或來源待核對',cause,'尚未排定開始日期'];task.activation_blockers=[]}
    return route.fulfill({response,json:data});
   }
   return route.continue();
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/api/session');await page.goto(base+'/');
  for(const tab of ['overview','flow']){
   await page.goto(base+`/#view=project&project=p3&tab=${tab}&node=field`);await page.locator('#flow-tasks').waitFor();
   if(cause){await page.waitForFunction(c=>document.querySelector('.st-blocker-banner>p')?.textContent===c,cause);const banner=page.locator('.st-blocker-banner');assert.equal(await banner.locator(':scope>p').innerText(),cause);if(name!=='schedule'){assert.equal(await banner.locator('details').getAttribute('open'),null);await banner.locator('summary').click();assert.equal(await banner.locator('details').getAttribute('open'),'');assert.equal((await page.locator('main').innerText()).split(cause).length-1,1)}}
   if(tab==='flow'){
    const sizes=await page.evaluate(()=>['#flow-tasks h3','.flow-operations .ops-heading h2'].map(s=>{const c=getComputedStyle(document.querySelector(s));return [c.fontSize,c.lineHeight,c.fontWeight,c.margin]}));assert.deepEqual(sizes[0],sizes[1]);
    assert.equal(await page.locator('main button.primary:visible,main button[data-variant=primary]:visible').count(),1);
    await page.locator('.pf-more>summary').click();assert.equal(await page.getByRole('button',{name:'指派負責人',exact:true}).count(),0);await page.locator('a[href*=people]:visible').first().waitFor();await page.keyboard.press('Escape');
    if(name==='live'){
     const trigger=page.getByRole('button',{name:'新增任務',exact:true});await trigger.focus();await trigger.click();await page.getByRole('dialog').waitFor();await page.screenshot({path:`${output}/add-task-${width}.png`});await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0);assert.equal(await trigger.evaluate(e=>e===document.activeElement),true);
    }
   }
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:`${output}/${name}-${tab}-${width}.png`,fullPage:true});
   if(name==='live'&&tab==='flow'){
    await page.locator('.pf-more>summary').click();await page.locator('a[href*=people]:visible').first().click();
    await page.getByRole('heading',{name:'排程與人員',exact:true}).waitFor();
    await page.screenshot({path:`${output}/people-destination-${width}.png`,fullPage:true});
   }
  }
  await context.close();console.log(`PASS browser ${name} ${width}`);
 }
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);console.log('All browser checks passed; no mutations attempted');
}finally{await browser.close()}
