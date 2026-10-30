// Reproducible evidence for the project-detail redesign against the synthetic fixture server.
// Run: node qa/project-flow-preview.mjs &  then  node qa/stage-evidence.mjs <outDir>
// Everything here is synthetic (no Lark, no staging records), so the screenshots are safe to share.
import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
const base=process.env.BASE||'http://127.0.0.1:5208';
const out=path.resolve(process.argv[2]||'.runtime/evidence');
await fs.mkdir(out,{recursive:true});
const url=`${base}/#view=project&project=p1`;
const state=async body=>fetch(`${base}/__flow-test/state`,{method:'POST',body:JSON.stringify(body)});
const calls=async()=>(await (await fetch(`${base}/__flow-test/state`)).json()).calls;
const writes=async()=>(await calls()).filter(c=>c.method!=='GET');
const results=[];const record=(id,ok,detail)=>{results.push({id,ok,detail});console.log(ok?'PASS':'FAIL',id,detail||'')};
const browser=await chromium.launch({channel:'chrome'});
const open=async(opts={})=>{const page=await browser.newPage({viewport:{width:1440,height:900},...opts});await page.goto(url,{waitUntil:'networkidle'});await page.waitForSelector('.cs-summary');await page.waitForTimeout(600);return page};
const assignFlow=async page=>{
 await page.getByRole('button',{name:'指派',exact:true}).first().click();await page.waitForSelector('.task-drawer');
 await page.locator('.task-drawer .assignee-picker button').click();await page.getByRole('option',{name:/林安娜/}).click();
 await page.locator('.task-drawer').getByRole('button',{name:'儲存',exact:true}).click();await page.waitForTimeout(900);
};

for(const [name,vp,scale] of [['1440',{width:1440,height:900},1],['1024',{width:1024,height:800},1],['768',{width:768,height:900},1],['390',{width:390,height:844},2],['zoom200',{width:720,height:450},2]]){
 await state({});const page=await browser.newPage({viewport:vp,deviceScaleFactor:scale});await page.goto(url,{waitUntil:'networkidle'});await page.waitForSelector('.cs-summary');await page.waitForTimeout(600);
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
 await page.screenshot({path:`${out}/${name}-top.png`});
 await page.evaluate(()=>document.getElementById('flow-selected').scrollIntoView());await page.waitForTimeout(250);await page.screenshot({path:`${out}/${name}-node-and-tasks.png`});
 await page.getByRole('button',{name:'指派',exact:true}).first().click();await page.waitForSelector('.task-drawer');await page.waitForTimeout(300);await page.screenshot({path:`${out}/${name}-drawer.png`});
 const drawer=await page.evaluate(()=>{const r=document.querySelector('.task-drawer').getBoundingClientRect();return {width:Math.round(r.width),fits:r.right<=innerWidth+1}});
 record(`viewport ${name}${name==='zoom200'?' (720x450 CSS px at DPR 2 = 200% zoom on 1440)':''}`,overflow<=0&&drawer.fits,`horizontal overflow ${overflow}px; drawer ${drawer.width}px wide`);
 await page.close();
}

await state({});let page=await open();
record('page open causes zero writes',(await writes()).length===0,`${(await calls()).length} reads`);
await page.getByRole('button',{name:'指派',exact:true}).first().click();await page.waitForSelector('.task-drawer');
await page.keyboard.press('Escape');await page.waitForTimeout(300);
record('Esc closes the drawer and returns focus to the trigger',await page.evaluate(()=>!document.querySelector('.task-drawer')&&document.activeElement.textContent.trim()==='指派'));
await page.close();

await state({});page=await open();await assignFlow(page);
const w1=await writes();
record('write: one PATCH, drawer closed, list shows the new executor',w1.length===1&&w1[0].method==='PATCH'&&!(await page.locator('.task-drawer').count()),`${w1.length} write(s)`);
await page.screenshot({path:`${out}/write-success.png`});await page.close();

for(const [mode,expect,file] of [['conflict','此任務已被他人修改','conflict'],['forbidden','權限已變更','server-403'],['unknown','儲存結果不明','unknown-outcome']]){
 await state({patch:mode});page=await open();await assignFlow(page);
 const text=await page.locator('.task-drawer').innerText();await page.screenshot({path:`${out}/${file}.png`});
 const w=await writes();
 record(`${mode}: drawer shows "${expect}" and sent ${w.length} write`,text.includes(expect)&&w.length===1,'draft kept, no silent retry');
 await page.close();
}

// The in-app synthetic route (#view=stage-fixture) is the same page Metis opens on staging after login.
const fixtureFlow={
 normal:async page=>{},validation:async page=>{},conflict:async page=>{},forbidden:async page=>{},timeout:async page=>{},
 partial:async page=>{await page.locator('.task-drawer input[type=date]').fill('2026-12-01')},revoked:async page=>{}
};
const expectText={normal:null,validation:'已停用或不可指派',conflict:'此任務已被他人修改',forbidden:'權限已變更',timeout:'儲存結果不明',partial:'只有部分欄位已儲存',revoked:'目前無指派權限'};
for(const [name,vp,scale] of [['1440',{width:1440,height:900},1],['1024',{width:1024,height:800},1],['768',{width:768,height:900},1],['390',{width:390,height:844},2],['zoom200',{width:720,height:450},2]]){
 for(const scenario of Object.keys(fixtureFlow)){
  const page=await browser.newPage({viewport:vp,deviceScaleFactor:scale});let nonGet=0;page.on('request',r=>{if(r.method()!=='GET'&&r.url().startsWith(base))nonGet++});
  await page.goto(`${base}/#view=stage-fixture&tab=${scenario}`,{waitUntil:'networkidle'});await page.waitForSelector('.stage-fixture');
  await page.getByRole('button',{name:'指派',exact:true}).click();await page.waitForSelector('.task-drawer');
  if(scenario==='revoked'){await page.waitForTimeout(3200)}
  else{await page.locator('.task-drawer .assignee-picker button').click();await page.getByRole('option',{name:/王小明/}).click();await fixtureFlow[scenario](page);await page.locator('.task-drawer').getByRole('button',{name:'儲存',exact:true}).click();await page.waitForTimeout(900);
   if(['timeout','partial'].includes(scenario)){await page.getByRole('button',{name:'查詢最新結果'}).click();await page.waitForTimeout(700)}}
  const text=await page.locator('.task-drawer').innerText().catch(()=>'');
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  await page.screenshot({path:`${out}/fixture-${scenario}-${name}.png`});
  const wanted=expectText[scenario],ok=overflow<=0&&nonGet===0&&(wanted?text.includes(wanted):!(await page.locator('.task-drawer').count()));
  record(`fixture route ${scenario} @${name}`,ok,`overflow ${overflow}px, non-GET requests ${nonGet}${wanted?`, shows "${wanted}"`:', drawer closed after save'}`);
  await page.close();
 }
}
await state({tasks:100});
const loads=[];
for(let i=0;i<5;i++){
 const ctx=await browser.newContext({viewport:{width:1440,height:900}});const p=await ctx.newPage();
 const cdp=await ctx.newCDPSession(p);await cdp.send('Network.emulateNetworkConditions',{offline:false,latency:100,downloadThroughput:20*1024*1024/8,uploadThroughput:5*1024*1024/8});
 const t0=Date.now();await p.goto(url,{waitUntil:'commit'});await p.waitForSelector('.cs-summary dl',{timeout:30000});await p.waitForSelector('#flow-selected h2');loads.push(Date.now()-t0);await ctx.close();
}
const pct=(a,q)=>{const s=[...a].sort((x,y)=>x-y);return s[Math.min(s.length-1,Math.ceil(q*s.length)-1)]};
record('performance: case summary and node card ready, 100-task fixture, 20 Mbps / 100 ms RTT, cold, 5 runs',pct(loads,.75)<=2500,`p75 ${pct(loads,.75)} ms (target 2500), runs ${loads.join('/')} ms; static preview build on localhost, not staging`);
page=await open();const switches=[];
for(const label of ['PM','外業','控制','PM','外業']){const t0=Date.now();await page.locator(`.pf-node[aria-label^="${label}"]`).click();await page.waitForFunction(l=>document.querySelector('#flow-selected h2')?.textContent===l,label);switches.push(Date.now()-t0)}
record('performance: node switch with cached data, 5 switches',pct(switches,.75)<=200,`p75 ${pct(switches,.75)} ms (target 200), runs ${switches.join('/')} ms; includes Playwright click overhead`);
await page.screenshot({path:`${out}/large-100-tasks.png`});await page.close();
await state({});await browser.close();
await fs.writeFile(`${out}/report.json`,JSON.stringify({base,results},null,1));
process.exit(results.every(r=>r.ok)?0:1);
