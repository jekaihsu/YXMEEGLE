// Exercise real App closures against the advertised shell contract (B2 is pending).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {Simulate} from 'react-dom/test-utils';
import {a,b,workspace} from './session-epoch-fixture.mjs';
const bundle=await build({entryPoints:['src/App.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'},plugins:[{name:'observe-shell',setup(build){build.onLoad({filter:/\/App\.tsx$/},async({path})=>({contents:"import {unmatchedDaily} from './appCommon';\n"+(await fs.readFile(path,'utf8')).replace(' const overdue=w?',' window.shellContext={w,s,error,run,upload,refresh,unmatchedDaily};\n const overdue=w?'),loader:'tsx'}))}}]});
const path=new URL('./.shell-test-bundle.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);
let App;try{App=(await import(path.href)).default}finally{await fs.unlink(path)}
const sopExample=JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8')).sop_tasks;
const shell={...workspace,scope:'shell',attention:[{task_id:'tA',project_id:'pA',project_code:'PRIVATE_CASE_A',project_name:'PRIVATE_CASE_A',node_id:'nA',node_key:'sales',node_name:'NODE_A',assignee_id:workspace.users[0].id,status:'pending',due_date:'2026-10-01',title:'TASK_A'}],pending_approvals:[{id:'apA',title:'APPROVAL_A',type:'change',project_id:'pA'}],counts:{approvals_pending:3,daily_unmatched:535,my_overdue_tasks:1,my_active_tasks:2,active_tasks:30,overdue_tasks:1,due_today_tasks:0},home_waiting:[{task_id:'wait-paused',project_id:'pA',project_code:'PRIVATE_CASE_A',node_id:'nA',title:'WAIT_PAUSED',kind:'paused',reason:'任務暫停，原期限保留',original_due_date:'2026-10-01',due_date:null},{task_id:'wait-prerequisite',project_id:'pA',project_code:'PRIVATE_CASE_A',node_id:'nA',title:'WAIT_PREREQUISITE',kind:'prerequisite',reason:'指定前置成果尚未交付',due_date:'2026-10-01'},{task_id:'wait-upcoming',project_id:'pA',project_code:'PRIVATE_CASE_A',node_id:'nA',title:'WAIT_UPCOMING',kind:'upcoming',reason:'排定 2026/10/10 開始',due_date:'2026-10-12'},{task_id:'wait-proxy',project_id:'pA',project_code:'PRIVATE_CASE_A',node_id:'nA',title:'WAIT_PROXY',kind:'proxy',reason:'代理同事執行；有效至 2026/10/31',due_date:'2026-10-12'}],projects:workspace.projects.map((p,i)=>{
 const {nodes,files,comments,daily_reports,...summary}=p;
 return {...summary,created_at:i?'2026-10-01':'2026-10-02',concurrency_version:i+7,progress:{completed_nodes:i?0:4,approved_skipped_nodes:i?0:1,total_nodes:i?0:10},overdue_tasks:i?0:2,active_tasks:5,execution_status:i?'completed':'in_progress'};
})};
const json=(data,headers={})=>new Response(JSON.stringify(data),{status:200,headers});
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=projects'});
for(const key of ['window','document','location','history','sessionStorage','FormData','Event','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(resolve=>setTimeout(resolve,0))});
// Stand-in for GET /api/projects?view=overview: same tabs, sorts, facets and paging contract as backend/shell.py.
let fullGate=async()=>{};let overviewGate=async()=>{};let detailGate=async()=>{};
// Stand-in for GET /api/projects/{id}: the single project tree plus its own records.
const detail=async(url)=>{
 const id=decodeURIComponent(url.split('?')[0].split('/').pop());await detailGate(id);const project=workspace.projects.find(p=>p.id===id);
 if(!project)return new Response(JSON.stringify({detail:'找不到這個案件'}),{status:404});
 return json({scope:'project',version:current.version,as_of:workspace.as_of,project,settings:{},delegations:[],handover_requests:[],sop_requests:[],sop_templates:[],approved_leave_delegations:[],approvals:[],events:[],policy_summary:[],financial_requests:[],source_quotes:[],source_confirmations:[],contract_items:[],node_skip_requests:[]});
};
let root;let features;let current=shell;let user=a;let etag='W/"shell-A:1"';let failMutation=false;let mutationResponse;const requests=[];
globalThis.fetch=async(url,init)=>{
 requests.push({url,init});
 if(url==='/api/session')return json({user,users:[a,b],mode:'lark',environment:'production',workspace_id:'workspace-A',auth_configured:true,features});
 if(url==='/api/my-work')return json({rows:[],readState:'ready',assignment:'unassigned',canSeeAwaitingConfirmation:false});
 if(url==='/api/source-health')return json({page_state:null,sources:[]});
 if(url==='/api/workspace'){await fullGate();return json({...workspace,version:current.version});}
 if(url==='/api/projects?view=portfolio&page=1'){await overviewGate(new URLSearchParams());return json({items:current.projects,total:current.projects.length,as_of:current.as_of,basis:'persisted_workspace'})}
 if(url.endsWith('/node-assignments'))return new Response(JSON.stringify({code:'disabled',detail:'disabled'}),{status:404});
 if(url.endsWith('/first-screen'))return new Response(JSON.stringify({detail:'not found'}),{status:404,headers:{'Content-Type':'application/json'}});
 if(url.endsWith('/sop-tasks')){const known=workspace.projects.some(p=>url.startsWith(`/api/projects/${p.id}/`));return new Response(JSON.stringify(known?{code:'sop_import_forbidden'}:sopExample),{status:known?403:200,headers:{'Content-Type':'application/json'}})}
 if(url.startsWith('/api/projects/'))return detail(url);
 if(url.startsWith('/api/daily-reports?'))return json({items:[],total:0,offset:0,limit:30,summary:{}});
 if(url==='/api/workspace?scope=shell')return init.headers.get('If-None-Match')===etag?new Response(null,{status:304,headers:{ETag:etag}}):json(current,{ETag:etag});
 if(url==='/api/actions'||url==='/api/files')return failMutation?new Response(JSON.stringify({detail:'conflict'}),{status:409}):json(mutationResponse||{...workspace,version:2});
 throw Error('Unexpected endpoint '+url);
};
const mount=async(next)=>{if(root)await flush(()=>root.unmount());features=next;requests.length=0;root=createRoot(document.getElementById('root'));await flush(()=>root.render(React.createElement(App)))};
const lastShell=()=>requests.findLast(r=>r.url==='/api/workspace?scope=shell');
const rows=()=>[...document.querySelectorAll('.pl-case')];
try{
 for(const flag of [undefined,{}, {workspace_shell:false},{workspace_shell:'true'}]){
  await mount(flag);assert.deepEqual(requests.map(r=>r.url),['/api/session','/api/workspace']);
  assert.equal(window.shellContext.w.scope,undefined);assert.equal(rows().length,2);
  assert.equal(document.querySelector('.notification-button i'),null);
 }
 await mount({workspace_shell:true});
 assert.deepEqual(requests.map(r=>r.url),['/api/session','/api/workspace?scope=shell','/api/projects?view=portfolio&page=1']);
 assert.equal(window.shellContext.w.scope,'shell');assert.equal(rows().length,2);
 assert.equal(window.shellContext.w.counts.my_overdue_tasks,1,'the shell still carries the server overdue count');assert.ok(!document.querySelector('[aria-label="主要導覽"]').textContent.includes('逾期'),'the nav badge was removed in 155b65a');
 assert.equal(document.querySelector('.notification-button'),null);assert.equal(window.shellContext.unmatchedDaily(window.shellContext.w),535);
 assert.equal(rows()[0].querySelector('.pl-current>span').textContent,'待核對'); // 目前作業 no longer repeats the workflow badge shown in the status column
 assert.equal(rows()[0].querySelectorAll('.pl-stepper li').length,9);assert.equal(rows()[0].querySelector('.pl-status').textContent,'流程進度：待核對');
 // P4-1: the dashboard renders from counts, the attention list and cards; no tree scan and no full workspace.
 await flush(()=>{location.hash='view=dashboard';window.dispatchEvent(new window.Event('hashchange'))});
 // The old home markup (.work-inbox, .dh-hero, .dh-waiting) was replaced by the unified home (155b65a and later); the shell contract kept here is that the dashboard renders from shell data alone.
 assert.ok(document.querySelector('.unified-home'),'dashboard renders the unified home from the shell workspace');
 assert.equal(window.shellContext.w.counts.approvals_pending,3);assert.equal(window.shellContext.w.attention.length,1);
 assert.ok(!requests.some(r=>r.url==='/api/workspace'),'dashboard renders without a full workspace read');
 await flush(()=>{location.hash='view=projects';window.dispatchEvent(new window.Event('hashchange'))});
 const change=async(label,value)=>flush(()=>{const select=document.querySelector(`[aria-label="${label}"]`);select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}))});
 const beforeFilters=requests.length;
 const attention=document.querySelector('.pl-check input');await flush(()=>{attention.checked=true;attention.dispatchEvent(new Event('change',{bubbles:true}))});
 await change('案件排序','created');assert.ok(rows()[0].textContent.includes('PRIVATE_CASE_A'));
 await flush(()=>document.querySelector('[aria-label="切換排序方向"]').click());
 assert.ok(rows()[0].textContent.includes('CASE_B'));
 assert.equal(requests.length,beforeFilters,'sorting complete portfolio does not request individual cases');
 await flush(()=>document.querySelector('.pl-clear').click());
 const cached=window.shellContext.w;await flush(()=>window.shellContext.refresh());
 assert.equal(lastShell().init.headers.get('If-None-Match'),etag);assert.equal(window.shellContext.w,cached,'304 reuses cached data');
 assert.equal(window.shellContext.error,'');assert.equal(rows().length,2);
 // Identity changes clear F1's ETag cache and accept a lower workspace version.
 user=b;current={...shell,version:0,projects:[]};etag='W/"shell-B:0"';
 await flush(()=>window.shellContext.refresh());assert.equal(lastShell().init.headers.get('If-None-Match'),null);assert.equal(window.shellContext.w.version,0);
 user=a;current=shell;etag='W/"shell-A:1"';await flush(()=>window.shellContext.refresh());
 await flush(()=>window.shellContext.run('case_execution_assign',{execution_system:'workbench'},{project_id:'pA'}));
 assert.equal(window.shellContext.error,'');assert.equal(window.shellContext.w.version,2,'full mutation response remains compatible before B3');
 const mutation=requests.findLast(r=>r.url==='/api/actions');const body=JSON.parse(mutation.init.body);
 assert.equal(body.version,1);assert.deepEqual(body.project_versions,{pA:7});assert.ok(body.request_id);assert.equal(mutation.init.headers.get('X-Workspace-Scope'),null);
 // Return to shell after an explicit refresh; uploads retain project concurrency.
 current={...shell,version:3};etag='W/"shell-A:3"';await flush(()=>window.shellContext.refresh());
 const form=new FormData();form.set('project_id','pB');await flush(()=>window.shellContext.upload(form));
 assert.equal(form.get('version'),'3');assert.equal(form.get('project_version'),'8');assert.equal(window.shellContext.error,'');
 mutationResponse={...shell,version:4,pending_approvals:[],counts:{...shell.counts,approvals_pending:0,my_overdue_tasks:0}};
 await flush(()=>window.shellContext.run('case_execution_assign',{}, {project_id:'pA'}));
 assert.equal(window.shellContext.w.scope,'shell');assert.equal(window.shellContext.error,'');
 assert.equal(document.querySelector('.notification-button i'),null);assert.ok(!document.querySelector('[aria-label="主要導覽"]').textContent.includes('逾期 '));
 current={...shell,version:5};etag='W/"shell-A:5"';
 failMutation=true;await flush(()=>window.shellContext.run('case_execution_assign',{}, {project_id:'pA'}));
 assert.ok(requests.findLast(r=>r.url!==undefined&&!r.url.startsWith('/api/projects')).url==='/api/workspace?scope=shell','409 re-reads shell');assert.ok(window.shellContext.error.includes('conflict'));

 const many=Array.from({length:25},(_,i)=>({...shell.projects[1],id:`c${i}`,code:`CODE_${String(i).padStart(2,'0')}`,name:`NAME_${i}`,created_at:`2026-10-${String(25-i).padStart(2,'0')}`,case_type:i%5===0?'intake':'formal',due_date:`2026-11-${String(i+1).padStart(2,'0')}`}));
 current={...shell,projects:many};etag='W/"shell-big"';await mount({workspace_shell:true});
 const portfolioReads=()=>requests.filter(r=>r.url==='/api/projects?view=portfolio&page=1').length;
 assert.equal(portfolioReads(),1);assert.equal(rows().length,3);
 await change('每組顯示筆數','10');assert.equal(rows().length,10);
 await flush(()=>document.querySelector('.pl-expand').click());assert.equal(rows().length,25);
 assert.match(document.querySelector('.pl-footer').textContent,/符合條件 25 筆/);
 await change('案件分類','intake');assert.equal(rows().length,5);
 await change('案件分類','formal');assert.equal(rows().length,10);
 assert.equal(document.querySelector('.pl-group:has(.pl-case) h2 span').textContent,'20');
 await change('篩選專案經理','actor-A');assert.equal(rows().length,10);await change('篩選專案經理','');
 const search=document.querySelector('[aria-label="搜尋案件"]');await flush(()=>{search.value='CODE_2';Simulate.change(search)});assert.equal(rows().length,4);
 await flush(()=>search.parentElement.querySelector('button').click());assert.equal(rows().length,10);
 assert.equal(portfolioReads(),1,'combined filtering, expansion and sorting reuse the complete bulk projection');
 // P4-3: opening a case reads that one project; tabs are client-side; a mutation hands over to the full workspace.
 current=shell;etag='W/"shell-A:1"';failMutation=false;mutationResponse=undefined;location.hash='view=project&project=pA';
 await mount({workspace_shell:true});
 const goto=async hash=>flush(()=>{location.hash=hash;window.dispatchEvent(new window.Event('hashchange'))});
 const detailUrls=()=>[...new Set(requests.map(r=>r.url).filter(u=>/^\/api\/projects\/[^/?]+(\?overview=true)?$/.test(u)).map(u=>u.split('?')[0]))];
 assert.deepEqual(requests.map(r=>r.url),['/api/session','/api/workspace?scope=shell','/api/projects/pA/first-screen','/api/projects/pA?overview=true','/api/projects/pA/progress','/api/projects/pA/sop-tasks','/api/projects/pA/sop-assignees'],'the overview reads only this project (first screen, fallback snapshot, progress, SOP tasks and assignees), never the full workspace');
 assert.ok(document.querySelector('.workspace').textContent.includes('PRIVATE_CASE_A'),'detail renders the project from the shell read');
 await goto('view=project&project=pA&tab=flow');await goto('view=project&project=pA&tab=data&section=basic');assert.deepEqual(detailUrls(),['/api/projects/pA'],'tabs do not refetch the project');
 assert.deepEqual(requests.filter(r=>r.url.endsWith('/node-assignments')).map(r=>r.url),[],'session flag off: no node-assignment request');
 await goto('view=project&project=pB');assert.deepEqual(detailUrls(),['/api/projects/pA','/api/projects/pB']);assert.ok(document.querySelector('.workspace').textContent.includes('CASE_B'));
 // The 日報 tab lists through /api/daily-reports; the other cards in the shell are summaries without daily_reports and must not be scanned.
 await goto('view=project&project=pB&tab=daily');assert.ok(!document.querySelector('.workspace').textContent.includes('畫面暫時無法顯示'),'daily tab survives summary projects without daily_reports');assert.equal(document.querySelector('.pds-tabs [aria-current=page]').textContent,'工項與進度','the legacy 日報 link opens the merged 工項與進度 tab');
 assert.ok(requests.some(r=>r.url==='/api/projects/pB/progress'),'that tab reads the project progress from the API');
 await goto('view=project&project=zz');assert.ok(document.querySelector('.workspace').textContent.includes('找不到這個案件'));
 let freeA;const heldA=new Promise(resolve=>{freeA=resolve});detailGate=async id=>{if(id==='pA')await heldA};
 await goto('view=project&project=pA');await goto('view=project&project=pB');await flush(async()=>{freeA();await heldA});
 assert.ok(document.querySelector('.workspace').textContent.includes('CASE_B')&&!document.querySelector('.workspace').textContent.includes('PRIVATE_CASE_A'),'a slow earlier project never replaces the one now open');
 detailGate=async()=>{};await goto('view=project&project=pA');const reads=detailUrls().length;
 await flush(()=>window.shellContext.run('case_execution_assign',{execution_system:'workbench'},{project_id:'pA'}));
 assert.equal(window.shellContext.w.scope,undefined,'mutation response is the full workspace');assert.equal(detailUrls().length,reads,'no extra project read after the full workspace arrives');
 assert.ok(document.querySelector('.workspace').textContent.includes('PRIVATE_CASE_A'),'detail keeps rendering from the full workspace');

 // P4-4: screens that need broader data read the full workspace only when opened, behind a loading state, once per shell version.
 current=shell;etag='W/"shell-A:1"';location.hash='view=dashboard';
 await mount({workspace_shell:true});
 const fullReads=()=>requests.filter(r=>r.url==='/api/workspace').length;
 assert.equal(fullReads(),0,'first paint never reads the full workspace');
 let openFull;const heldFull=new Promise(resolve=>{openFull=resolve});fullGate=()=>heldFull;
 await goto('view=work&tab=legacy');assert.equal(fullReads(),1);assert.ok(document.querySelector('.workspace [role="status"]').textContent.includes('正在載入完整資料'),'loading state while the full read is pending');
 assert.ok(document.querySelector('[aria-label="主要導覽"]'),'the shell stays usable while a screen loads');
 await flush(async()=>{openFull();await heldFull});fullGate=async()=>{};
 assert.ok(document.querySelector('.workspace').textContent.includes('TASK_A'),'my work renders the loaded task');
 for(const view of ['approvals','schedule','routines','admin','work&tab=legacy'])await goto('view='+view);
 assert.equal(fullReads(),1,'one full read per shell version, shared by every screen');
 await goto('view=dashboard');assert.equal(fullReads(),1,'the dashboard (the old lazy activity panel was replaced by the unified home) triggers no further full read');
 current={...shell,version:5};etag='W/"shell-A:5"';await flush(()=>window.shellContext.refresh());await goto('view=work&tab=legacy');
 assert.equal(fullReads(),2,'a newer shell version reads the full workspace again (approvals is feature-gated, so the legacy work tab is used)');
 await flush(()=>window.shellContext.run('case_execution_assign',{execution_system:'workbench'},{project_id:'pA'}));
 await goto('view=schedule');await goto('view=work&tab=legacy');assert.equal(fullReads(),2,'after a mutation the app holds the full workspace and reads nothing');
 // P1-INT: the default #work/#sources pages read their own GETs and never the full workspace.
 const fullBefore=fullReads();await goto('view=work');await goto('view=sources');
 assert.equal(fullReads(),fullBefore,'default work/sources pages do not read the full workspace');
 assert.ok(requests.some(r=>r.url==='/api/my-work')&&requests.some(r=>r.url==='/api/source-health'));
 assert.ok(!document.querySelector('.workspace').textContent.includes('資料正常'),'null page_state never renders a healthy label');assert.ok(document.querySelector('.workspace').textContent.includes('狀態未知'),'null page_state renders unknown');
 console.log('Shell mode: feature gating, server-side paging/filter reset/stale-response guard, lazy single-project detail, on-demand full workspace, summary-only render/filter/sort, badges, 304, identity cache, mutation/upload concurrency and 409 passed');
}finally{await flush(()=>root.unmount());dom.window.close()}
