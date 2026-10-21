import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {a,b,workspace} from './session-epoch-fixture.mjs';
const bundle=await build({stdin:{contents:"export {default as App} from './src/App';export {ProjectFlow} from './src/ProjectFlow';export {useSopTasks,canReadSop,prefetchSopTasks} from './src/useSopTasks';export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.read-loading-test.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const json=data=>new Response(JSON.stringify(data),{headers:{'content-type':'application/json'}});
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(r=>setTimeout(r,10))});
function environment(hash){
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'+hash,pretendToBeVisual:true});
 for(const key of ['window','document','location','history','sessionStorage','localStorage','FormData','Event','DOMException','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
 window.scrollTo=()=>{};globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 return dom;
}
for(const shell of [false,true]){
 const dom=environment('#view=admin&tab=settings');ui.invalidateSessionEpoch();
 const calls=[];let resolveSummary;
 globalThis.fetch=(url,init)=>{calls.push({url,init});if(url==='/api/session')return Promise.resolve(json({user:a,users:[a,b],mode:'lark',environment:'production',workspace_id:'A',features:{workspace_shell:shell}}));if(url==='/api/settings/overview')return new Promise(resolve=>{resolveSummary=resolve});return new Promise(()=>{})};
 const root=createRoot(document.getElementById('root'));
 await flush(()=>root.render(React.createElement(ui.App)));
 await flush();
 assert.match(document.body.textContent,/管理設定/);
 assert.ok(!calls.some(c=>c.url.startsWith('/api/workspace')),'settings must not request even a shell workspace');
 await flush(()=>resolveSummary(json({user:{name:'SUMMARY_READY',role:'manager',permissions:[]},environment:'demo',identity_mode:'unknown',features:{},sources:[],sources_access:'restricted',directory:{status:'restricted',last_success_at:null},datasets:[],node_connection:[],manager_details_available:false})));
 assert.match(document.body.textContent,/SUMMARY_READY/);
 await flush(()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='日曆與連線').click());
 assert.ok(calls.some(c=>c.url.startsWith('/api/workspace')),'complete edit data is requested only after opening the section');
 assert.ok(calls.find(c=>c.url==='/api/session').init.signal,'bootstrap cancellation reaches fetch');
 await flush(()=>root.unmount());dom.window.close();
}
{
 const dom=environment('');ui.invalidateSessionEpoch();const calls=[];
 globalThis.fetch=(url)=>{calls.push(url);return new Promise(()=>{})};
 function Restricted(){const sop=ui.useSopTasks('p','A',false);return React.createElement('p',null,sop.state.kind)}
 const root=createRoot(document.getElementById('root'));await flush(()=>root.render(React.createElement(Restricted)));
 assert.equal(document.body.textContent,'forbidden');assert.deepEqual(calls,[]);
 assert.equal(ui.canReadSop({role:'manager',capabilities:[]}),false);
 assert.equal(ui.canReadSop({capabilities:['sop_task_read']}),true);
 assert.equal(ui.canReadSop({active:false,capabilities:['sop_task_read']}),false);
 await flush(()=>root.unmount());dom.window.close();
}
{
 const dom=environment('#view=project&project=pA&tab=flow');ui.invalidateSessionEpoch();
 const example=JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8')).sop_tasks;
 const calls=[];globalThis.fetch=(url)=>{calls.push(url);if(url.endsWith('/sop-tasks'))return Promise.resolve(json(example));if(url.endsWith('/sop-assignees'))return Promise.resolve(json({people:[]}));return new Promise(()=>{})};
 const c={w:workspace,s:{user:{...a,capabilities:['sop_task_read']},users:[a],mode:'demo',workspace_id:'A',features:{node_assignment:true}},route:{view:'project',project:'pA',tab:'flow'},go:()=>{},run:async()=>{},refresh:async()=>{},notify:()=>{},busy:false};
 const assignments={state:{kind:'loading'},refreshing:false,pending:'',notice:'',error:null,revision:0,reload:async()=>{},mutate:async()=>{}};
 const root=createRoot(document.getElementById('root'));await flush(()=>root.render(React.createElement(ui.ProjectFlow,{c,p:workspace.projects[0],assignments,selectedKey:'sales',secondary:null,legacyActions:null})));
 assert.ok(document.querySelector('#sop-tasks'),'SOP section is mounted while assignments remain loading');
 assert.match(document.querySelector('#sop-tasks').textContent,/業主提出報價需求/);
 assert.ok(calls.some(url=>url.endsWith('/progress')),'progress starts independently');
 await flush(()=>root.unmount());dom.window.close();
}
{
 const dom=environment('');ui.invalidateSessionEpoch();let calls=0;
 globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify({code:'sop_import_forbidden'}),{status:403})};
 await assert.rejects(()=>ui.prefetchSopTasks('denied','A'));
 await assert.rejects(()=>ui.prefetchSopTasks('denied','A',true));
 assert.equal(calls,1,'a prefetch invalidation does not retry a known 403');
 ui.invalidateSessionEpoch();
 await assert.rejects(()=>ui.prefetchSopTasks('denied','B'));
 assert.equal(calls,2,'new identity/workspace must reauthorize');
 dom.window.close();
}
{
 const dom=environment('');ui.invalidateSessionEpoch();
 const example=JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8')).sop_tasks;
 const resolvers=[];let calls=0;
 globalThis.fetch=()=>{calls++;return new Promise(resolve=>resolvers.push(resolve))};
 const old=ui.prefetchSopTasks('same-project','A');
 assert.equal(ui.prefetchSopTasks('same-project','A'),old,'parallel readers share one request');
 assert.equal(calls,1);
 ui.invalidateSessionEpoch();
 const fresh=ui.prefetchSopTasks('same-project','A');
 assert.equal(calls,2,'new session cannot reuse a previous pending request');
 resolvers[1](json({...example,checklist_revision:1}));await fresh;
 resolvers[0](json({...example,checklist_revision:99}));await old;
 const cached=await ui.prefetchSopTasks('same-project','A');
 assert.equal(cached.checklistRevision,1,'late response from the previous session cannot replace current data');
 assert.equal(calls,2);
 dom.window.close();
}
console.log('Settings bootstrap, deferred edits, cancellation, and explicit SOP read gating passed');
