import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture} from './fixtures/node-assignments.mjs';

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
 assert.deepEqual(requests.map(r=>r.url).sort(),['/api/projects/p1?overview=true','/api/projects/p1/node-assignments','/api/projects/p1/node-assignments/start-sop','/api/projects/p1/sop-assignees','/api/projects/p1/sop-tasks'].sort(),'overview data starts together while project detail is unresolved');
 await render('flow');
 assert.equal(requests.filter(r=>r.url==='/api/projects/p1?overview=true').length,1,'changing tabs shares the pending detail read');
 for(const suffix of ['start-sop','sop-tasks','sop-assignees'])assert.equal(requests.filter(r=>r.url.endsWith('/'+suffix)).length,1,'flow starts '+suffix+' without waiting for detail');
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
 console.log('PASS project detail: parallel visible reads, shared pending detail, and no unrelated workflow prefetch');
}finally{await act(async()=>{root.unmount();settle()});dom.window.close()}
