import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {chromium} from 'playwright-core';
import {assignmentFixture,projectFixture} from './fixtures/node-assignments.mjs';
const actual=process.env.YX_FE1_ACTUAL==='1';
const source=process.env.YX_FE1_SOURCE||import.meta.dirname,backend=process.env.YX_CASE_DEMO_API_URL;
assert(backend&&['127.0.0.1','localhost'].includes(new URL(backend).hostname),'isolated demo backend required');
const home=`import React from 'react';import {HomeDataProvider,useHomeResource,homeValue} from '${resolve(source,'src/useHomePanels.ts')}';function Panels({c}){for(const panel of ['assigned','confirmation','delegated'])useHomeResource(c,{endpoint:'/api/home-panels',query:{panel}},homeValue);for(const endpoint of ['/api/company-dashboard','/api/weekly-report'])useHomeResource(c,{endpoint},homeValue);return <button onClick={async()=>{await c.run('confirmation_confirm',{}, {project_id:'p1'});window.writeDone=true}}>確認寫入</button>}export function UnifiedHome({c}){return <HomeDataProvider c={c}><Panels c={c}/></HomeDataProvider>}`;
const entry=`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import App from './src/App';import {DetailRefreshProvider} from './src/detailRefresh';import {useNodeAssignments} from './src/useNodeAssignments';import {useSopTasks} from './src/useSopTasks';import {useProjectProgress} from './src/useProjectProgress';import {AssignDrawer} from './src/AssignDrawer';import {SopTaskInspector} from './src/SopTaskInspector';function Case(){const a=useNodeAssignments('p1',true),s=useSopTasks('p1','test');useProjectProgress('p1');const [drawer,setDrawer]=useState('');return <><h1>案件寫入驗收</h1><button onClick={()=>setDrawer('assignment')}>開啟指派</button><button onClick={()=>setDrawer('sop')}>開啟 SOP</button>{drawer==='assignment'&&a.state.kind==='ready'&&<AssignDrawer task={window.fixture.tasks[0]} nodeKey="control" nodeLabel="控制" caseLabel="測試案件" people={window.fixture.assignable_people} unavailableReason="" mutate={a.mutate} retry={a.retryMutation} verify={async()=>undefined} refresh={()=>{}} onClose={()=>setDrawer('')}/>}{drawer==='sop'&&s.state.kind==='ready'&&<SopTaskInspector task={s.state.data.tasks[0]} project={{id:'p1'}} users={[]} sop={s} testOperator onClose={()=>setDrawer('')} onCleaned={()=>setDrawer('')}/>}</>};createRoot(document.querySelector('#root')).render(location.search.includes('case')&&${!actual}?<DetailRefreshProvider scope="test"><Case/></DetailRefreshProvider>:<App/>);`;
const bundle=await build({stdin:{contents:entry,resolveDir:source,loader:'tsx'},plugins:[{name:'home-probe',setup(b){b.onLoad({filter:/\/UnifiedHome\.tsx$/},()=>({contents:home,loader:'tsx',resolveDir:source}))}}],bundle:true,write:false,format:'iife',platform:'browser',jsx:'automatic',loader:{'.css':'empty'}});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const context=await browser.newContext();const session=await(await context.request.get(backend+'/api/session')).json();assert.equal(session.mode,'demo');await context.request.post(backend+'/api/demo/session',{data:{user_id:'u-manager'}});
 const sessionBody=await(await context.request.get(backend+'/api/session')).json(),workspace=actual?projectFixture().workspace:await(await context.request.get(backend+'/api/workspace')).json(),f=assignmentFixture();
 if(actual){f.detail.tasks[0].assignee=null;f.list.node_details={control:{tasks:f.detail.tasks,assignable_people:f.detail.assignable_people}};}
 const examples=JSON.parse(await readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url)));let overview=structuredClone(examples.sop_tasks);overview.tasks[0].local={...overview.tasks[0].local,is_test:true};
 const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url)));progress.project_id='p1';let reads=[],writes=[];
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://127.0.0.1:52885/**',async route=>{
  const req=route.request(),url=new URL(req.url());let body;
  if(!url.pathname.startsWith('/api/'))return route.fulfill({contentType:'text/html',body:`<meta charset="utf-8"><div id="root"></div><script>window.fixture=${JSON.stringify(f.detail)};</script><script>${bundle.outputFiles[0].text}</script>`});
  if(req.method()==='GET')reads.push({url:url.pathname+url.search,intent:req.headers()['x-yx-fetch-intent']});else writes.push(url.pathname);
  if(url.pathname==='/api/session')body={...sessionBody,workspace_id:'test',features:{...sessionBody.features,node_assignment:actual}};
  else if(url.pathname==='/api/workspace'||url.pathname==='/api/actions')body={...workspace,workspace_id:'test'};
  else if(url.pathname.endsWith('/cleanup-test')){overview={...overview,tasks:[]};body={task_id:examples.sop_tasks.tasks[0].id,removed:true,replayed:false,checklist_revision:2}}
  else if(req.method()!=='GET'&&url.pathname.includes('/node-assignments/'))body={...f.detail,record_id:f.detail.node.record_id};
  else if(url.pathname.endsWith('/start-sop'))body={project_id:'p1',code:'A115001',eligible:false,can_start:false,already_started:true,seeds_pending:0,seeds_optional:false,blockers:[],warnings:[],nodes:[],chain_note:'',preview_hash:'h',plan_rule_version:'v'};
  else if(url.pathname.endsWith('/node-assignments'))body=f.list;
  else if(url.pathname.endsWith('/sop-tasks'))body=overview;
  else if(url.pathname.endsWith('/sop-assignees'))body=examples.assignees;
  else if(url.pathname.endsWith('/progress'))body=progress;
  else body={count:reads.length};return route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 const run=process.env.YX_FE1_ONLY||'all';
 if(run!=='home'){
 await page.goto(actual?'http://127.0.0.1:52885/?case#view=project&project=p1&tab=flow&node=control':'http://127.0.0.1:52885/?case');await page.waitForLoadState('networkidle');if(run!=='sop'){await page.getByRole('button',{name:actual?'指派':'開啟指派',exact:true}).click();await page.locator('input[type=date]').fill('2026-12-01');reads=[];
 await page.getByRole('button',{name:'儲存',exact:true}).click();await page.getByRole('dialog').waitFor({state:'detached',timeout:4000});await page.waitForLoadState('networkidle');assert.equal(reads.length,1);assert.equal(reads[0].intent,'own_write_committed');console.log('assignment',JSON.stringify(reads));}
 if(actual){await page.goto('http://127.0.0.1:52885/?case#view=project&project=p1&tab=flow&node=sales&task_source=sop_local&task='+encodeURIComponent(examples.sop_tasks.tasks[0].id));await page.waitForLoadState('networkidle')}else await page.getByText('開啟 SOP',{exact:true}).click();await page.getByRole('button',{name:'清除測試任務',exact:true}).click();await page.getByRole('textbox',{name:'清除原因'}).fill('驗收完成');reads=[];await page.getByRole('button',{name:'確認清除',exact:true}).click();await page.getByRole('dialog').count().then(async()=>{await page.waitForFunction(()=>document.querySelectorAll('[role=dialog]').length===0,{},{timeout:4000})});await page.waitForLoadState('networkidle');assert.equal(reads.length,actual?3:2);assert(reads.every(r=>r.intent==='own_write_committed'));console.log('sop',JSON.stringify(reads));}
 await page.goto('http://127.0.0.1:52885/#view=dashboard');await page.getByText('確認寫入',{exact:true}).waitFor();await page.waitForLoadState('networkidle');reads=[];await page.getByText('確認寫入',{exact:true}).click();await page.waitForFunction(()=>window.writeDone);await page.waitForLoadState('networkidle');assert.equal(writes.at(-1),'/api/actions');console.log('home c.run',JSON.stringify(reads));assert.equal(reads.length,2,'production c.run reloads only confirmation and assigned');assert(reads.every(r=>r.intent==='own_write_committed'));assert.deepEqual(errors,[]);
}finally{await browser.close()}
