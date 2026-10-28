import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {chromium} from 'playwright-core';
const base=process.argv[2]||'http://[::1]:5200/';
if(!new URL(base).hostname.match(/^(\[::1\]|localhost|127\.0\.0\.1)$/))throw Error('This sweep changes local form values. Use an isolated local demo.');
const browser=await chromium.launch({channel:'chrome',headless:true}),results=[];
const routes=['projects','quotes','work','work&tab=legacy','people','admin&tab=settings','admin&tab=daily','admin&tab=people','sources','reports&tab=review','reports&tab=progress','reports&tab=quality','reports&tab=attendance',...['overview','flow','items','people','files','data'].map(tab=>`project&project=p1&tab=${tab}`),...['basic','quotes','contracts','family','participants','files','approvals','activity','sources'].map(section=>`project&project=p1&tab=data&section=${section}`)];
try{for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:900}});page.setDefaultTimeout(5000);
 await page.goto(base);await page.request.post(new URL('/api/demo/session',base).href,{data:{user_id:'u-manager'}});
 for(const route of routes){
  const errors=[];const onError=error=>errors.push(error.message);page.on('pageerror',onError);
  await page.goto(`${base.split('#')[0]}#view=${route}`);await page.locator('main').waitFor();
  await page.waitForFunction(()=>!document.querySelector('.route-skeleton,.route-progress[aria-busy=true]')).catch(()=>{});
  await page.evaluate(()=>document.querySelectorAll('details').forEach(d=>{if(!/more|menu/.test(d.className))d.open=true}));
  const count=await page.locator('.ds-picker>button:visible').count();
  for(let index=0;index<count;index++){
   const trigger=page.locator('.ds-picker>button:visible').nth(index);if(!await trigger.count())continue;
   const label=await trigger.getAttribute('aria-label');
   if(await trigger.isDisabled()){results.push({route,width,label,status:'disabled'});continue}
   try{
    await trigger.click();const popup=page.locator('.ds-picker-popup:visible');await popup.waitFor();
    const r=await popup.boundingBox();assert(r.x>=0&&r.x+r.width<=width+1&&r.y>=0&&r.y+r.height<=901,'popup inside viewport');
    assert(await popup.evaluate(p=>p.contains(document.elementFromPoint(p.getBoundingClientRect().left+15,p.getBoundingClientRect().top+15))),'popup receives pointer');
    const input=popup.locator('input');if(await input.count()){await input.fill('不存在zzzz');await popup.getByRole('status').waitFor();await input.fill('')}
    await page.keyboard.press('Escape');assert.equal(await popup.count(),0);
    await trigger.click();await popup.waitFor();await page.mouse.click(width-2,2);assert.equal(await popup.count(),0);
    await trigger.focus();await page.keyboard.press('ArrowDown');await popup.waitFor();await page.keyboard.press('End');await page.keyboard.press('Home');await page.keyboard.press('Enter');
    assert.equal(await popup.count(),0);results.push({route,width,label,status:'pass'});
   }catch(error){results.push({route,width,label,status:'fail',error:error.message});await page.keyboard.press('Escape')}
  }
  const menus=page.locator('button[aria-haspopup=menu]:visible,.pds-more>summary:visible,.pf-attention-menu>summary:visible');
  for(let index=0;index<await menus.count();index++){
   const trigger=menus.nth(index),label=await trigger.getAttribute('aria-label')||await trigger.innerText();
   try{await trigger.click();const popup=page.locator('.ds-picker-popup:visible');await popup.waitFor();await popup.locator('a,button').first().focus();await page.keyboard.press('ArrowDown');await page.keyboard.press('Escape');assert.equal(await popup.count(),0);await trigger.click();await popup.waitFor();await page.mouse.click(width-2,2);assert.equal(await popup.count(),0);results.push({route,width,label,kind:'menu',status:'pass'})}catch(error){results.push({route,width,label,kind:'menu',status:'fail',error:error.message});await page.keyboard.press('Escape')}
  }
  for(const input of await page.locator('input[type=date]:visible,input[type=datetime-local]:visible,input[type=time]:visible').all()){
   const label=await input.getAttribute('aria-label')||await input.evaluate(e=>e.labels?.[0]?.textContent||e.type);
   if(await input.isDisabled()){results.push({route,width,label,status:'disabled'});continue}
   try{const original=await input.inputValue(),type=await input.getAttribute('type');await input.fill(type==='time'?'09:30':type==='datetime-local'?'2026-11-03T09:30':'2026-11-03');await input.fill(original);results.push({route,width,label,status:'pass',kind:'date'})}catch(error){results.push({route,width,label,status:'fail',error:error.message})}
  }
  results.push({route,width,status:errors.length?'page-error':'visited',controls:count,errors});page.off('pageerror',onError);
 }
 await page.close();
}}finally{await browser.close();await fs.mkdir(new URL('../../.runtime/case-detail-perf/',import.meta.url),{recursive:true});await fs.writeFile(new URL('../../.runtime/case-detail-perf/picker-sweep.json',import.meta.url),JSON.stringify(results,null,2))}
console.log(JSON.stringify({passed:results.filter(r=>r.status==='pass').length,disabled:results.filter(r=>r.status==='disabled').length,failed:results.filter(r=>r.status==='fail'||r.status==='page-error')}));
assert(!results.some(r=>r.status==='fail'||r.status==='page-error'));
