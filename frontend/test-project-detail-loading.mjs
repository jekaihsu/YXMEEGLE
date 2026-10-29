import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture,assignmentFixture} from './fixtures/node-assignments.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetailGate} from './src/ProjectDetail';export {invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.project-detail-loading-test.mjs',import.meta.url);
await fs.writeFile(file,bundle.outputFiles[0].text);
let ui;try{ui=await import(file.href)}finally{await fs.unlink(file)}
const {project,user,workspace}=projectFixture();
const c={w:{...workspace,scope:'shell'},s:{user,workspace_id:'offline',features:{node_assignment:true}},route:{view:'project',project:project.id},go(){},registerDrafts(){},notify(){}};
const requests=[];
globalThis.fetch=url=>new Promise(resolve=>requests.push({url,resolve}));
let root;
const render=tab=>act(async()=>root.render(React.createElement(ui.ProjectDetailGate,{c:{...c,route:{...c.route,tab}}})));
const settle=()=>{for(const request of requests)request.resolve(new Response('{"detail":"offline test complete"}',{status:503}));};
try{
 root=createRoot(document.getElementById('root'));
 await render('overview');
 assert.deepEqual(requests.map(r=>r.url),['/api/projects/p1/first-screen'],'overview starts one aggregate read');
 await render('flow');
 assert.equal(requests.length,1,'changing tabs shares the pending first-screen read');
 await render('overview');
 const examples=JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8'));
 const tasks=structuredClone(examples.sop_tasks);tasks.project_id=project.id;
 const progress=JSON.parse(await fs.readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));progress.project_id=project.id;
 const assignments=assignmentFixture().list;
 assignments.node_details=Object.fromEntries(assignments.nodes.map(n=>[n.key,{tasks:[],assignable_people:[]} ]));
 const start={project_id:project.id,code:project.code,eligible:false,can_start:false,already_started:true,seeds_pending:0,seeds_optional:false,blockers:[],warnings:[],nodes:[],chain_note:'',preview_hash:'h1',plan_rule_version:'v1'};
 await act(async()=>requests[0].resolve(new Response(JSON.stringify({project:{...workspace,scope:'project',project:{...project,source_kind:'lark'}},assignments:{status:200,body:assignments},tasks:{status:200,body:tasks},start:{status:200,body:start},progress:{status:200,body:progress}}),{headers:{'X-Read-Snapshot':'stale'}})));
 assert.match(document.body.textContent,/SOP 已啟動/,'aggregate status renders without a second request');
 assert.ok(document.querySelector('.po-todos .po-task-row'),'aggregate tasks render with status');
 assert.match(document.body.textContent,/上次成功資料，待更新/,'background snapshot refresh is visibly labeled');
 assert.equal(requests.filter(r=>['/sop-tasks','/node-assignments','/start-sop'].some(s=>r.url.endsWith(s))).length,0,'seeded status/task readers add no heavy requests');
 assert.equal(requests.filter(r=>r.url.endsWith('/progress')).length,1,'progress starts only after status/tasks have rendered');

 await act(async()=>{root.unmount();settle()});
 ui.invalidateSessionEpoch();requests.length=0;
 root=createRoot(document.getElementById('root'));
 await render('files');
 assert.deepEqual(requests.map(r=>r.url),['/api/projects/p1'],'opening documents does not load unrelated workflow data');
 await act(async()=>requests[0].resolve(new Response(JSON.stringify({...workspace,scope:'project',project}))));
 assert.match(document.body.textContent,/文件與交付/);
 assert.equal(requests.length,1,'rendering documents adds no workflow waterfall');
 await act(async()=>root.render(React.createElement(ui.ProjectDetailGate,{c:{...c,reloadVersion:1,route:{...c.route,tab:'files'}}})));
 assert.equal(requests.length,2,'workspace reload explicitly refreshes the mounted snapshot');
 assert.match(document.body.textContent,/文件與交付/,'refresh keeps existing content');
 await act(async()=>requests[1].resolve(new Response(JSON.stringify({...workspace,scope:'project',project:{...project,name:'更新後案件'}}))));
 assert.match(document.body.textContent,/更新後案件/);
 const originalNow=Date.now;let now=100000;Date.now=()=>now;
 try {
  await act(async()=>window.dispatchEvent(new Event('blur')));now+=60000;
  await act(async()=>{document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'))});
  assert.equal(requests.length,3,'return refreshes the mounted snapshot once');
  await act(async()=>requests[2].resolve(new Response(JSON.stringify({...workspace,scope:'project',project}))));
 } finally {Date.now=originalNow}

 await act(async()=>root.unmount());
 ui.invalidateSessionEpoch();requests.length=0;
 const originalTimeout=globalThis.setTimeout,originalClear=globalThis.clearTimeout;
 const timers=new Map();let timerId=0;
 globalThis.setTimeout=(fn,ms)=>{assert.equal(ms,20000);timers.set(++timerId,fn);return timerId};
 globalThis.clearTimeout=id=>timers.delete(id);
 try {
  root=createRoot(document.getElementById('root'));await render('files');
  assert.equal(requests.length,1);
  await act(async()=>{[...timers.values()][0]()});
  assert.equal(requests.length,1,'timeout does not silently duplicate an upstream request');
  assert.match(document.querySelector('[role=alert]').textContent,/案件讀取失敗/);
  await act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='重試').click());
  assert.equal(requests.length,2);
  globalThis.setTimeout=originalTimeout;globalThis.clearTimeout=originalClear;
  await act(async()=>requests[1].resolve(new Response(JSON.stringify({...workspace,scope:'project',project}))));
  assert.match(document.body.textContent,/文件與交付/);
 } finally {globalThis.setTimeout=originalTimeout;globalThis.clearTimeout=originalClear}
 console.log('PASS project detail: aggregate status/tasks render together; seeded readers add no heavy requests; shared pending detail; document isolation');
}finally{await act(async()=>{root.unmount();settle()});dom.window.close()}
