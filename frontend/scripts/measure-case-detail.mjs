import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const urls=process.argv.slice(2),browser=await chromium.launch({channel:'chrome',headless:true});
const results=[];
try{for(let run=0;run<5;run++)for(const url of urls){
 const context=await browser.newContext({viewport:{width:1280,height:800}}),page=await context.newPage(),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>{
  window.caseTiming={};
  const selectors={header:'.pds-header',sop:'.po-next:not([aria-busy=true])',tasks:'.po-todos',flow:'.pf-diagram',node:'#flow-selected:not([aria-busy=true])'};
  new MutationObserver(()=>{for(const [name,selector] of Object.entries(selectors)){if(!window.caseTiming[name]&&document.querySelector(selector))window.caseTiming[name]=Math.round(performance.now())}}).observe(document,{subtree:true,childList:true,attributes:true});
 });
 await page.goto(url,{waitUntil:'domcontentloaded'});
 let failed=false;try{await page.locator('.po-todos').waitFor({timeout:90000});await page.waitForFunction(()=>!document.querySelector('[aria-label="任務載入中"],.po-next[aria-busy="true"]'),{},{timeout:60000})}catch{failed=true}
 const result=await page.evaluate(()=>({timing:window.caseTiming,text:document.querySelector('main')?.innerText.slice(0,300),resources:performance.getEntriesByType('resource').map(r=>({url:r.name,start:Math.round(r.startTime),ms:Math.round(r.duration),bytes:r.transferSize,status:r.responseStatus})),marks:performance.getEntriesByType('mark').filter(r=>r.name.includes('render')).map(r=>({name:r.name,ms:Math.round(r.startTime)}))}));
 results.push({url,run,failed,errors,...result});console.log(JSON.stringify({url,run,failed,errors,timing:result.timing,apiCount:result.resources.filter(r=>r.url.includes('/api/')).length}));await context.close();
}}finally{await browser.close();await fs.writeFile(new URL('../../.runtime/case-detail-perf/measurements.json',import.meta.url),JSON.stringify(results,null,2))}
