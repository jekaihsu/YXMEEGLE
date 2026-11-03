import {build} from 'esbuild';
import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {projectFixture,assignmentFixture} from './fixtures/node-assignments.mjs';
const evidence=process.env.LIVE3_EVIDENCE;assert(evidence,'LIVE3_EVIDENCE must point outside the repository');
const source=process.env.LIVE3_SOURCE||process.cwd(),baseline=!!process.env.LIVE3_SOURCE;
const label=baseline?'before':'after';
const {project,user,workspace}=projectFixture();project.source_kind='lark';project.contract_amount=47000;project.source_projection={finance:{contract_amount:94000}};
const assignments=assignmentFixture().list;assignments.node_details=Object.fromEntries(assignments.nodes.map(n=>[n.key,{tasks:[],assignable_people:[]}]));
const tasks=JSON.parse(await fs.readFile('../backend/sop_import/api-examples.json','utf8')).sop_tasks;tasks.project_id='p1';
const progress=JSON.parse(await fs.readFile('./fixtures/project-progress.json','utf8'));progress.project_id='p1';
const contents=`import React from 'react';import {createRoot} from 'react-dom/client';import {ProjectDetailGate} from './src/ProjectDetail';const root=createRoot(document.getElementById('root'));const c=${JSON.stringify({w:{...workspace,scope:'shell'},s:{user,workspace_id:'offline',features:{node_assignment:true}},route:{view:'project',project:'p1',tab:'overview'}})};c.go=r=>{c.route={...c.route,...r};render()};c.registerDrafts=()=>{};c.notify=()=>{};const render=()=>root.render(React.createElement(ProjectDetailGate,{c}));window.caseTab=t=>{c.route.tab=t;render()};render();`;
const bundled=await build({stdin:{contents,resolveDir:source},bundle:true,write:false,format:'iife',platform:'browser',jsx:'automatic',outdir:'.live3-browser',loader:{'.png':'dataurl','.svg':'dataurl'},define:{'process.env.NODE_ENV':'"production"'}});
const styles=await build({entryPoints:[source+'/src/main.tsx'],bundle:true,write:false,outdir:'.live3-css',loader:{'.png':'dataurl','.svg':'dataurl'}});
const css=[...styles.outputFiles,...bundled.outputFiles].filter(f=>f.path.endsWith('.css')).map(f=>f.text).join('\n');
const js=bundled.outputFiles.find(f=>f.path.endsWith('.js')).text;
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:1000}}),calls=[];
  await page.route('**/api/**',route=>{
   const path=new URL(route.request().url()).pathname;calls.push(path);
   const data=path.endsWith('/first-screen')?{project:{...workspace,scope:'project',project},snapshot:{as_of:'2026-11-03T02:41:47Z',completeness:'partial',stale:true},assignments:{status:200,body:assignments},tasks:{status:200,body:tasks},start:{status:404,body:{}}}:path==='/api/projects/p1'?{...workspace,scope:'project',project:{...project,nodes:[]}}:path.endsWith('/progress')?progress:path.includes('/node-assignments/')?{...assignmentFixture().detail,node:assignments.nodes.find(n=>n.key===path.split('/').at(-1))}:path.endsWith('/node-assignments')?assignments:path.endsWith('/sop-tasks')?tasks:path.includes('/report-links/summary')?{linked:0,total:535,unlinked:535,departments:{},reasons:{},unlinked_scope:'visible_queue_not_attributed_to_case'}:{};
   return route.fulfill({json:data});
  });
  await page.goto('http://localhost:5193');
  await page.setContent(`<html data-theme="dark"><head><style>${css}</style></head><body><div class="app-shell"><main class="workspace"><div id="root"></div></main></div></body></html>`);
  await page.addScriptTag({content:js});
  await page.locator('.pds-status-chip').waitFor();
  for(const tab of ['overview','flow','items','people','files','data']){
   await page.evaluate(t=>window.caseTab(t),tab);
   await page.waitForTimeout(250);
   await page.screenshot({path:`${evidence}/${label}-${tab}-${width}.png`,fullPage:true});
   if(!baseline){
    assert.equal(await page.locator('.pds-status-chip').innerText(),'控制 · 進行中');
    assert.match(await page.locator('.pds-data-time').innerText(),/2026\/11\/03 10:41:47/);
    assert.doesNotMatch(await page.locator('body').innerText(),/正在更新節點資料，請稍候/);
    const small=await page.locator('.project-detail :is(button,a,select,input:not([type=checkbox],[type=radio]),summary)').evaluateAll(es=>es.filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'&&(r.width<43.9||r.height<43.9)}).map(e=>({text:e.textContent,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})));assert.deepEqual(small,[],`${tab} ${width} 44px targets`);
    if(tab==='people')assert.match(await page.locator('caption').innerText(),/本案各節點負責人/);
    if(tab==='data')assert.match(await page.locator('body').innerText(),/金額來源不一致/);
   }
  }
  if(!baseline){await page.evaluate(()=>window.caseTab('flow'));await page.getByRole('button',{name:/財務來源（唯讀）/}).click();await page.getByText('金額來源不一致 · 待核對，尚未選定權威總額').waitFor();await page.screenshot({path:`${evidence}/after-finance-${width}.png`,fullPage:true})}
  await fs.writeFile(`${evidence}/${label}-${width}-requests.json`,JSON.stringify(calls,null,2));await page.close();
 }
 console.log(`PASS ${label} real Chromium isolated demo + synthetic source-shaped case, all six tabs at 1440/390`);
}finally{await browser.close()}
