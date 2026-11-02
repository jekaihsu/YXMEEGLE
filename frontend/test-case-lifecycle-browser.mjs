import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {build} from 'esbuild';
import {chromium} from 'playwright-core';
import {projectFixture,assignmentFixture} from './fixtures/node-assignments.mjs';
const {project,user,workspace}=projectFixture();project.source_kind='lark';
const assignments=assignmentFixture().list;
assignments.node_details=Object.fromEntries(assignments.nodes.map(n=>[n.key,{tasks:[],assignable_people:[]} ]));
const examples=JSON.parse(await readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8'));
const tasks={...examples.sop_tasks,project_id:project.id};
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));progress.project_id=project.id;
const start={project_id:project.id,code:project.code,eligible:false,can_start:false,already_started:true,seeds_pending:0,seeds_optional:false,blockers:[],warnings:[],nodes:[],chain_note:'',preview_hash:'h1',plan_rule_version:'v1'};
const slice={...workspace,scope:'project',project};
const bundle=await build({stdin:{resolveDir:import.meta.dirname,contents:`
import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import {ProjectDetailGate} from './src/ProjectDetail';
function Fixture(){const [route,go]=useState({view:'project',project:'p1',tab:'overview'});return React.createElement(ProjectDetailGate,{c:{w:${JSON.stringify({...workspace,scope:'shell'})},s:${JSON.stringify({user,workspace_id:'offline',features:{node_assignment:true}})},route,go,registerDrafts(){},notify(){}}})}
createRoot(document.getElementById('root')).render(React.createElement(React.StrictMode,null,React.createElement(React.Suspense,{fallback:'載入中'},React.createElement(Fixture))));
`},bundle:true,write:false,format:'iife',platform:'browser',loader:{'.css':'empty'}});
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
 const page=await browser.newPage(),reads=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));await page.clock.install({time:new Date('2026-11-02T15:00:00Z')});
 await page.route('http://localhost:5192/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(!path.startsWith('/api/'))return route.fulfill({contentType:'text/html',body:`<!doctype html><div id="root"></div><script>${bundle.outputFiles[0].text}</script>`});
  reads.push(path);
  let body;
  if(path.endsWith('/first-screen'))body={project:slice,assignments:{status:200,body:assignments},tasks:{status:200,body:tasks},start:{status:200,body:start}};
  else if(path.endsWith('/node-assignments'))body=assignments;
  else if(path.endsWith('/sop-tasks'))body=tasks;
  else if(path.endsWith('/sop-assignees'))body=examples.assignees;
  else if(path.endsWith('/start-sop'))body=start;
  else if(path.endsWith('/progress'))body=progress;
  else if(path==='/api/projects/p1')body=slice;
  else return route.fulfill({status:403,contentType:'application/json',body:'{"detail":"fixture denied"}'});
  return route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto('http://localhost:5192/unit-case-fixture');await page.locator('.cs-summary').waitFor();await page.waitForFunction(()=>!document.body.textContent.includes('正在更新案件資料'));
 assert.equal(reads.length,3,'first-screen plus assignees and progress, once each under StrictMode');
 await page.getByRole('button',{name:'流程與任務',exact:true}).click();await page.getByRole('button',{name:'更新節點與任務',exact:true}).waitFor({timeout:3000}).catch(async e=>{console.log({errors,reads,text:await page.locator('body').innerText()});throw e});
 const initial=reads.length;assert.equal(initial,3);
 await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('blur'))});
 await page.clock.fastForward(600000);
 await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});for(const event of ['visibilitychange','focus','online']){window.dispatchEvent(new Event(event));document.dispatchEvent(new Event(event))}});
 await page.getByRole('button',{name:'總覽',exact:true}).click();await page.getByRole('button',{name:'流程與任務',exact:true}).click();
 assert.equal(reads.length,initial,'ten minute away/tab round-trip makes zero duplicate reads');
 await page.getByRole('button',{name:'更新節點與任務',exact:true}).click();await page.waitForFunction(()=>!document.body.textContent.includes('正在更新案件資料'));
 const refresh=reads.slice(initial);assert.equal(refresh.length,6,'one batch refreshes each loaded resource once');assert.equal(new Set(refresh).size,6,'no duplicate resource in refresh batch');
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',initialReads:initial,afterTenMinutes:initial,idleReads:0,explicitRefreshBatches:1,refreshReads:refresh}));
}finally{await browser.close()}
