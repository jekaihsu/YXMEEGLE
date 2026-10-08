// Real shell routes and real CSS: late selections, deadlines and table columns.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import {build} from 'esbuild';
import {workspace} from './session-epoch-fixture.mjs';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE||'/tmp/shots/node_modules/playwright-core');
const bundle=await build({entryPoints:['src/main.tsx'],bundle:true,write:false,outdir:'/tmp/yx-responsive',format:'iife',platform:'browser',jsx:'automatic',define:{'process.env.NODE_ENV':'"development"'}});
const js=bundle.outputFiles.find(f=>f.path.endsWith('.js')).text,css=bundle.outputFiles.find(f=>f.path.endsWith('.css')).text;
const server=createServer((req,res)=>{res.setHeader('Content-Type',req.url==='/app.js'?'text/javascript':req.url==='/app.css'?'text/css':'text/html');res.end(req.url==='/app.js'?js:req.url==='/app.css'?css:'<!doctype html><html lang="zh-TW"><title>Responsive regression</title><link rel="stylesheet" href="/app.css"><div id="root"></div><script src="/app.js"></script></html>')});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
const w=structuredClone(workspace);w.projects[1].code='C115236';w.projects[0].nodes[0].tasks[0].due_date='2026-10-01';
w.projects[1].nodes=['sales','pm','confirmation','field','control','mapping','report','pricing','settlement'].map((key,i)=>({...structuredClone(w.projects[0].nodes[0]),id:'nB'+i,key,name:key,status:i<4?'completed':i===4?'in_progress':'pending',tasks:[{...structuredClone(w.projects[0].nodes[0].tasks[0]),id:'tB'+i,title:'Flow task '+i,owner_id:w.users[1].id,start_date:'2026-09-21',due_date:'2026-10-01',status:'pending',points:12}]}));
const shell={...w,scope:'shell',projects:w.projects.map(({nodes,files,comments,daily_reports,...p})=>p),counts:{},attention:[],pending_approvals:[]};
try{
 browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',route=>{const url=new URL(route.request().url());let data=w;
 if(url.pathname==='/api/session')data={user:w.users[0],users:w.users,mode:'demo',auth_configured:false,features:{workspace_shell:true}};
 else if(url.pathname==='/api/workspace'&&url.search)data=shell;
 else if(url.pathname==='/api/projects')data={items:shell.projects,total:2,offset:0,limit:10,facets:{all:2,formal:2,intake:0}};
 else if(url.pathname.startsWith('/api/projects/'))data={...w,scope:'project',project:w.projects.find(p=>p.id===url.pathname.split('/').at(-1))};
 else if(url.pathname==='/api/daily-reports')data={items:[],total:0,summary:{}};
 return route.fulfill({json:data});});
 const go=async hash=>{await page.goto(`http://127.0.0.1:${server.address().port}/#view=${hash}`);await page.locator('h1').waitFor();await page.waitForTimeout(150)};
 const visible=async selector=>page.locator(selector).evaluate(el=>{const r=el.getBoundingClientRect(),p=el.parentElement.closest('.project-tabs,.ops-tabs,.workflow-scroll')||el.closest('.workflow-scroll');const b=p.getBoundingClientRect();return r.left>=b.left-1&&r.right<=b.right+1});
 for(const tab of ['data','logs']){await go(`project&project=pB&tab=${tab}`);assert.ok(await visible('.project-tabs [aria-current=page]'),`phone ${tab} selected tab visible`);await page.reload();await page.locator('.project-tabs').waitFor();assert.ok(await visible('.project-tabs [aria-current=page]'),`phone ${tab} reload selected tab visible`)}
 for(const tab of ['daily','jobs']){await go(`admin&tab=${tab}`);await page.locator('.ops-tabs').waitFor();assert.ok(await visible('.ops-tabs [aria-current=page]'),`phone admin ${tab} selected tab visible`)}
 await go('dashboard');
 for(const status of await page.locator('.portfolio-stage').all())assert.equal(await status.evaluate(e=>e.getClientRects().length),1,'dashboard stage does not split mid-word');
 await go('admin&tab=settings');
 assert.ok(await page.locator('.operations .ds-section>h2').first().evaluate(e=>Math.abs(e.getBoundingClientRect().left-document.querySelector('h1').getBoundingClientRect().left)<1),'admin section headings align with the page title');
 assert.ok(await page.locator('.appearance-control').evaluate(e=>['paddingTop','paddingRight','paddingBottom','paddingLeft'].every(k=>parseFloat(getComputedStyle(e)[k])>=16)),'appearance controls have inner padding');
 await go('project&project=pB&tab=flow&node=nB4');
 assert.ok(await page.locator('.project-topline>.ds-button svg').first().evaluate(e=>Math.abs(e.getBoundingClientRect().left-document.querySelector('h1').getBoundingClientRect().left)<2),'case back link content aligns with title');assert.ok(await visible('.stage-button.selected'),'phone selected flow stage visible');
 assert.equal(await page.locator('.node-section .task-table .avatar').count(),0,'full owner names have no repeated monogram');
 assert.ok(!(await page.locator('.node-section .task-table').innerText()).includes('必做 SOP'),'default SOP labels omitted');
 const deadline=page.locator('.node-section .task-table td:nth-child(4)').first();
 assert.ok(await deadline.isVisible(),'phone flow deadline visible');assert.match(await deadline.innerText(),/10\/01/);assert.match(await deadline.innerText(),/逾期 1 天/);
 assert.deepEqual(errors,[],'shell second-case routes have no runtime error');
 console.log('Responsive detail: phone late tabs, admin tabs and selected flow stage visible on entry/reload');
 await go('project&project=pB&tab=data&section=participants');
 assert.equal(await page.locator('.person-cell .avatar').count(),0,'participant full names have no repeated monogram');
 await go('project&project=pB&tab=flow&node=nB4&task=tB4');
 assert.ok(await page.locator('.inspector-fields>div').first().evaluate(e=>parseFloat(getComputedStyle(e).paddingTop)>=12),'inspector facts have separate spacing');
 assert.equal(await page.locator('.inspector-fields .avatar').count(),0,'inspector owner name is not repeated');
 await page.setViewportSize({width:1024,height:1000});
 const checkColumns=async()=>{
  assert.ok(await page.locator('.comfortable-tasks .work-project').count()>0);
  for(const selector of ['td.work-project','td.work-due'])for(const cell of await page.locator(selector).all())assert.ok(await cell.evaluate(e=>e.scrollWidth<=e.clientWidth+1),`${selector} fits without truncation at 1024px`);
  assert.match(await page.locator('td.work-due').first().innerText(),/2026\/10\/01/);
 };
 await go('projects');await page.locator('.projects-table').waitFor();
 const tableTop=await page.locator('.projects-table').evaluate(e=>e.getBoundingClientRect().top);
 await page.locator('.column-preferences summary').click();assert.ok(Math.abs(await page.locator('.projects-table').evaluate(e=>e.getBoundingClientRect().top)-tableTop)<1,'column choices overlay without shifting table');
 await page.locator('.column-preferences summary').click();
 await go('work&tab=all');await page.locator('.comfortable-tasks').waitFor();await checkColumns();
 for(const control of await page.locator('.table-toolbar input,.table-toolbar select').all())assert.ok(await control.evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>=15),'work filters use shared readable type');
 await page.getByRole('textbox',{name:'搜尋任務'}).focus();
 assert.equal(await page.locator('.search-field').evaluate(e=>getComputedStyle(e).outlineWidth),'3px','search retains one visible focus ring');
 assert.equal(await page.getByRole('textbox',{name:'搜尋任務'}).evaluate(e=>getComputedStyle(e).boxShadow),'none','search has no doubled inner focus box');
 await go('schedule');await page.locator('.calendar-grid').waitFor();
 assert.equal(await page.locator('.calendar-grid').evaluate(e=>getComputedStyle(e).borderTopWidth),'1px','calendar uses a quiet hairline');
 assert.ok(await page.locator('.calendar-grid').evaluate(e=>e.scrollWidth<=e.parentElement.clientWidth+1),'all seven days fit at 1024px');
 await page.getByRole('button',{name:'查看當日工作',exact:true}).first().click();await checkColumns();
 console.log('Responsive detail: 1024px all-task/day codes and dates fit; all seven weekdays visible');

 await page.close();
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve))}
