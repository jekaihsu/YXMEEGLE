// Exercise real App closures against the advertised shell contract (B2 is pending).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {a,b,workspace} from './session-epoch-fixture.mjs';
const bundle=await build({entryPoints:['src/App.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'},plugins:[{name:'observe-shell',setup(build){build.onLoad({filter:/\/App\.tsx$/},async({path})=>({contents:(await fs.readFile(path,'utf8')).replace(' const overdue=w?',' window.shellContext={w,s,error,run,upload,refresh,unmatchedDaily};\n const overdue=w?'),loader:'tsx'}))}}]});
const path=new URL('./.shell-test-bundle.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);
let App;try{App=(await import(path.href)).default}finally{await fs.unlink(path)}
const shell={...workspace,scope:'shell',attention:[{task_id:'tA',project_id:'pA',project_code:'PRIVATE_CASE_A',project_name:'PRIVATE_CASE_A',node_key:'sales',status:'pending',due_date:'2026-10-01',title:'TASK_A'}],counts:{approvals_pending:3,daily_unmatched:535,my_overdue_tasks:4,my_active_tasks:12},projects:workspace.projects.map((p,i)=>{
 const {nodes,files,comments,daily_reports,...summary}=p;
 return {...summary,concurrency_version:i+7,progress:{completed_nodes:i?0:4,approved_skipped_nodes:i?0:1,total_nodes:i?0:10},overdue_tasks:i?0:2,active_tasks:5,execution_status:i?'completed':'in_progress'};
})};
const json=(data,headers={})=>new Response(JSON.stringify(data),{status:200,headers});
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=projects'});
for(const key of ['window','document','location','history','sessionStorage','FormData','Event','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(resolve=>setTimeout(resolve,0))});
let root;let features;let current=shell;let user=a;let etag='W/"shell-A:1"';let failMutation=false;let mutationResponse;const requests=[];
globalThis.fetch=async(url,init)=>{
 requests.push({url,init});
 if(url==='/api/session')return json({user,users:[a,b],mode:'lark',environment:'production',workspace_id:'workspace-A',auth_configured:true,features});
 if(url==='/api/workspace')return json(workspace);
 if(url==='/api/workspace?scope=shell')return init.headers.get('If-None-Match')===etag?new Response(null,{status:304,headers:{ETag:etag}}):json(current,{ETag:etag});
 if(url==='/api/actions'||url==='/api/files')return failMutation?new Response(JSON.stringify({detail:'conflict'}),{status:409}):json(mutationResponse||{...workspace,version:2});
 throw Error('Unexpected endpoint '+url);
};
const mount=async(next)=>{if(root)await flush(()=>root.unmount());features=next;requests.length=0;root=createRoot(document.getElementById('root'));await flush(()=>root.render(React.createElement(App)))};
const rows=()=>[...document.querySelectorAll('.projects-table tbody tr')];
const button=text=>[...document.querySelectorAll('.tabbar button')].find(b=>b.textContent.startsWith(text));
try{
 for(const flag of [undefined,{}, {workspace_shell:false},{workspace_shell:'true'}]){
  await mount(flag);assert.deepEqual(requests.map(r=>r.url),['/api/session','/api/workspace']);
  assert.equal(window.shellContext.w.scope,undefined);assert.equal(rows().length,2);
  assert.equal(document.querySelector('.notification-button i'),null);
 }
 await mount({workspace_shell:true});
 assert.deepEqual(requests.map(r=>r.url),['/api/session','/api/workspace?scope=shell']);
 assert.equal(window.shellContext.w.scope,'shell');assert.equal(rows().length,2);
 assert.ok(document.querySelector('[aria-label="主要導覽"]').textContent.includes('逾期 4'));
 assert.ok(document.querySelector('.notification-button i'));assert.equal(window.shellContext.unmatchedDaily(window.shellContext.w),535);
 assert.ok(rows()[0].querySelector('.stage-chips').textContent.includes('進行中'));
 assert.equal(rows()[0].querySelector('.progress-cell span').textContent,'40%');
 assert.equal(rows()[1].querySelector('.progress-cell span').textContent,'0%');
 // P4-1: the dashboard renders from counts, the attention list and cards; no tree scan and no full workspace.
 await flush(()=>{location.hash='view=dashboard';window.dispatchEvent(new window.Event('hashchange'))});
 const todo=document.querySelector('.work-inbox');
 assert.ok(todo.textContent.includes('TASK_A')&&todo.textContent.includes('逾期 1 天')&&todo.textContent.includes('3 筆待審申請'));
 assert.equal(todo.querySelector('.heading-count').textContent,'7');assert.ok(document.querySelector('.today-aside').textContent.includes('535 筆日報待配對'));
 assert.ok(document.querySelector('.project-preview-row').textContent.includes('PRIVATE_CASE_A'));
 assert.ok(!requests.some(r=>r.url==='/api/workspace'),'dashboard never loads the full workspace');
 await flush(()=>{location.hash='view=projects';window.dispatchEvent(new window.Event('hashchange'))});
 await flush(()=>button('需要關注').click());assert.equal(rows().length,1);assert.ok(rows()[0].textContent.includes('PRIVATE_CASE_A'));
 await flush(()=>button('執行中').click());assert.equal(rows().length,1);assert.ok(rows()[0].textContent.includes('PRIVATE_CASE_A'));
 await flush(()=>button('交付已完成').click());assert.equal(rows().length,1);assert.ok(rows()[0].textContent.includes('CASE_B'));
 await flush(()=>button('全部紀錄').click());
 const sort=document.querySelector('[aria-label="案件排序"]');await flush(()=>{sort.value='progress';sort.dispatchEvent(new Event('change',{bubbles:true}))});
 assert.ok(rows()[0].textContent.includes('CASE_B'),'shell progress sorts without nodes');
 const cached=window.shellContext.w;await flush(()=>window.shellContext.refresh());
 assert.equal(requests.at(-1).init.headers.get('If-None-Match'),etag);assert.equal(window.shellContext.w,cached,'304 reuses cached data');
 assert.equal(window.shellContext.error,'');assert.equal(rows().length,2);
 // Identity changes clear F1's ETag cache and accept a lower workspace version.
 user=b;current={...shell,version:0,projects:[]};etag='W/"shell-B:0"';
 await flush(()=>window.shellContext.refresh());assert.equal(requests.at(-1).init.headers.get('If-None-Match'),null);assert.equal(window.shellContext.w.version,0);
 user=a;current=shell;etag='W/"shell-A:1"';await flush(()=>window.shellContext.refresh());
 await flush(()=>window.shellContext.run('case_execution_assign',{execution_system:'workbench'},{project_id:'pA'}));
 assert.equal(window.shellContext.error,'');assert.equal(window.shellContext.w.version,2,'full mutation response remains compatible before B3');
 const mutation=requests.findLast(r=>r.url==='/api/actions');const body=JSON.parse(mutation.init.body);
 assert.equal(body.version,1);assert.deepEqual(body.project_versions,{pA:7});assert.ok(body.request_id);assert.equal(mutation.init.headers.get('X-Workspace-Scope'),null);
 // Return to shell after an explicit refresh; uploads retain project concurrency.
 current={...shell,version:3};etag='W/"shell-A:3"';await flush(()=>window.shellContext.refresh());
 const form=new FormData();form.set('project_id','pB');await flush(()=>window.shellContext.upload(form));
 assert.equal(form.get('version'),'3');assert.equal(form.get('project_version'),'8');assert.equal(window.shellContext.error,'');
 mutationResponse={...shell,version:4,counts:{...shell.counts,approvals_pending:0,my_overdue_tasks:0}};
 await flush(()=>window.shellContext.run('case_execution_assign',{}, {project_id:'pA'}));
 assert.equal(window.shellContext.w.scope,'shell');assert.equal(window.shellContext.error,'');
 assert.equal(document.querySelector('.notification-button i'),null);assert.ok(!document.querySelector('[aria-label="主要導覽"]').textContent.includes('逾期 '));
 current={...shell,version:5};etag='W/"shell-A:5"';
 failMutation=true;await flush(()=>window.shellContext.run('case_execution_assign',{}, {project_id:'pA'}));
 assert.ok(requests.at(-1).url==='/api/workspace?scope=shell','409 re-reads shell');assert.ok(window.shellContext.error.includes('conflict'));
 console.log('Shell mode: feature gating, summary-only render/filter/sort, badges, 304, identity cache, mutation/upload concurrency and 409 passed');
}finally{await flush(()=>root.unmount());dom.window.close()}
