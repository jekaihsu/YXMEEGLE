import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {chromium} from 'playwright-core';

const output=new URL('./test-project-chat-layout-artifacts/',import.meta.url);
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const page=await browser.newPage({reducedMotion:'reduce'});
const results=[];
try{
 await page.goto(process.env.PROJECT_CHAT_TEST_URL || 'http://127.0.0.1:8126/#view=project&project=p1');
 await page.locator('.pds-tabs').waitFor();
 for(const width of [1280,1366,1440,1500]){
  await page.setViewportSize({width,height:1000});
  for(const tab of ['overview','flow','items','people','files','data']){
   await page.evaluate(tab=>{location.hash='view=project&project=p1&tab='+tab},tab);
   await page.waitForFunction(tab=>document.querySelector('.pds-tabs [aria-current]')?.textContent===({overview:'總覽',flow:'流程與任務',items:'工項與進度',people:'排程與人員',files:'文件與交付',data:'案件資料'})[tab],tab);
   if(tab==='flow')await page.getByRole('button',{name:'階段導覽',exact:true}).click();
   for(const open of width===1440?[false]:[false,true]){
    const launcher=page.locator('.project-chat-launcher');
    if((await launcher.getAttribute('data-open')==='true')!==open){
     if(open)await launcher.evaluate(e=>e.click());
     else await page.getByRole('button',{name:'關閉案件 AI 助理',exact:true}).click();
    }
    await page.waitForFunction(open=>document.querySelector('.project-chat-launcher')?.dataset.open===String(open),open);
    await page.evaluate(async()=>{await document.fonts.ready;window.scrollTo(0,0);await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))});
    const layout=await page.evaluate(()=>{
     const root=document.querySelector('.project-detail');
     const open=document.querySelector('.project-chat-launcher').dataset.open==='true';
     const properties=['display','gridTemplateColumns','gridRow','flexDirection','flexWrap','position','overflowX','paddingRight','containerType'];
     const elements=[root,...root.querySelectorAll('*')].filter(e=>!e.closest('.project-chat-launcher'));
     const take=()=>elements.map(e=>{
      const rect=e.getBoundingClientRect(),style=getComputedStyle(e);
      return [e.tagName,String(e.className),...['x','y','width','height'].map(k=>Math.round(rect[k]*100)/100),...properties.map(k=>style[k])];
     });
     // Warm layout before comparing. The first offscreen rectangle can be empty until layout is flushed.
     take();
     const before=take(),removed=[];
     const strip=sheet=>{
      for(let i=sheet.cssRules.length-1;i>=0;i--){
       const rule=sheet.cssRules[i];
       if(rule.selectorText?.includes('.project-detail')&&rule.selectorText.includes('project-chat')){
        removed.push([sheet,i,rule.cssText]);sheet.deleteRule(i);
       }else if(rule.cssRules)strip(rule);
      }
     };
     if(!open)for(const sheet of document.styleSheets)strip(sheet);
     const baseline=take();
     for(const [sheet,index,text] of removed.reverse())sheet.insertRule(text,index);
     const flow=[...root.querySelectorAll('.pf-stage-workspace,.pf-panel,.pf-chain,.po-stage-scroll')].map(e=>({
      className:e.className,width:e.clientWidth,grid:getComputedStyle(e).gridTemplateColumns,
      wrap:getComputedStyle(e).flexWrap,direction:getComputedStyle(e).flexDirection,display:getComputedStyle(e).display,
     }));
     return {open,closedBaselineEqual:open?null:JSON.stringify(before)===JSON.stringify(baseline),pageOverflow:document.documentElement.scrollWidth-innerWidth,flow};
    });
    assert.equal(layout.open,open);
    assert.equal(layout.pageOverflow,0,`${width} ${tab} ${open} page overflow`);
    if(!open)assert.equal(layout.closedBaselineEqual,true,`${width} ${tab} closed layout differs with chat CSS removed`);
    if(tab==='flow'&&open){
     const workspace=layout.flow.find(e=>e.className==='pf-stage-workspace');
     const panel=layout.flow.find(e=>e.className.includes('pf-panel'));
     assert.ok(!workspace.grid.includes(' '),'stage workspace has one column');
     assert.ok(!panel.grid.includes(' '),'nested stage panel has one column');
     assert.equal(layout.flow.find(e=>e.className==='pf-chain').wrap,'nowrap');
    }
    const file=`${tab}-${width}-${open?'open':'closed'}.png`;
    await page.screenshot({path:new URL(file,output).pathname,fullPage:true});
    results.push({tab,width,open,screenshot:new URL(file,output).pathname,...layout});
   }
  }
  console.log(`PASS all tabs at ${width}px`);
 }
 await fs.writeFile(new URL('results.json',output),JSON.stringify(results,null,2)+'\n');
}finally{await browser.close()}

