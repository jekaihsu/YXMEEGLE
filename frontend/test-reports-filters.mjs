import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
const screenshotDir=process.env.REPORTS_FILTERS_SCREENSHOTS;
if(screenshotDir)await mkdir(screenshotDir,{recursive:true});
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
const bundle=await build({stdin:{contents:`import './src/styles.css';import './src/reports/preview';`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,outdir:'out',format:'iife',jsx:'automatic'});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 for(const hasTouch of [false,true])for(const width of [1440,1024,768,390]){
  const page=await browser.newPage({viewport:{width,height:1000},hasTouch});
  await page.route('http://reports.test/**',route=>{const name=new URL(route.request().url()).pathname;const file=bundle.outputFiles.find(f=>f.path.endsWith(name));return route.fulfill(file?{contentType:name.endsWith('.css')?'text/css':'text/javascript',body:file.text}:{contentType:'text/html',body:'<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/stdin.css"><div id="root"></div><script src="/stdin.js"></script>'})});
  await page.goto('http://reports.test/?mock=1&tab=contacts');
  for(const [tab,count] of [['業主聯繫紀錄',7],['業務數據',2],['檢查報告',4],['儀器車輛',4],['工作進度',1]]){
   await page.getByRole('button',{name:tab,exact:true}).click();
   await page.locator('.reports-filters .ds-picker>button').first().waitFor();
   await page.waitForFunction(count=>document.querySelectorAll('.reports-filters .ds-picker>button').length===count&&[...document.querySelectorAll('.reports-filters .ds-select')].every(select=>select.querySelector('.ds-picker>button span')?.textContent===select.querySelector('select').selectedOptions[0]?.textContent),count);
   if(tab==='業主聯繫紀錄'&&screenshotDir&&!hasTouch){
    await page.evaluate(async()=>{await document.fonts.ready;const filters=document.querySelector('.reports-filters');window.scrollTo(0,filters.getBoundingClientRect().top+scrollY-100);await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))});
    await page.screenshot({path:join(screenshotDir,`after-${width}.png`),animations:'disabled'});
   }
   const failures=await page.evaluate(()=>{
    const failures=[];
    const controlHeight=matchMedia('(max-width:700px),(pointer:coarse)').matches?44:40;
    for(const field of document.querySelectorAll('.reports-filters label')){
     const control=field.querySelector('.ds-picker>button,input');if(!control)continue;
     const range=document.createRange();range.selectNodeContents(field.firstChild);
     if(range.getBoundingClientRect().bottom>control.getBoundingClientRect().top)failures.push('label not above control');
     const r=control.getBoundingClientRect();if(Math.abs(r.height-controlHeight)>1)failures.push(`control height ${r.height}`);
     if(r.left<0||r.right>innerWidth)failures.push('control overflow');
    }
    for(const button of document.querySelectorAll('.reports-filters .ds-picker>button')){
     if(button.querySelector('span').getBoundingClientRect().width<20)failures.push('invisible selected text');
     if(button.querySelector('svg').getBoundingClientRect().width>20)failures.push('stretched chevron');
    }
    if(document.documentElement.scrollWidth>innerWidth)failures.push('page overflow');
    const search=document.querySelector('.contacts-screen input[type=search]');
    if(search){const ctx=document.createElement('canvas').getContext('2d');ctx.font=getComputedStyle(search).font;if(ctx.measureText(search.placeholder).width>search.clientWidth-24)failures.push('truncated search placeholder');
     const sort=document.querySelector('.reports-sort');if(Math.abs(sort.querySelector('button').getBoundingClientRect().bottom-sort.querySelector('label').getBoundingClientRect().bottom)>1)failures.push('sort misalignment');
     const filters=search.closest('.reports-filters');if(filters.getBoundingClientRect().top-filters.previousElementSibling.getBoundingClientRect().bottom>24)failures.push('gap above filters');}
    return failures;
   });
   assert.deepEqual(failures,[],`${tab} at ${width}px, touch=${hasTouch}`);
  }
  await page.close();console.log(`Report filter layout passed at ${width}px across five tabs, touch=${hasTouch}.`);
 }
}finally{await browser.close()}
