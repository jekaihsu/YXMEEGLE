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
const overviewFacts=[{contract_amount:123456,source_lifecycle:{relationship:'已關聯確認單',state:'mapped',canonical:'執行中',reasons:[]},current_nodes:[{key:'field',name:'SERVER_FIELD',status:'in_progress'},{key:'custom',name:'PAUSED_STAGE',status:'paused'}],blocked_tasks:2},{contract_amount:null,current_nodes:[],blocked_tasks:0}];
let includeFacts=true;
const shell={...workspace,scope:'shell',attention:[{task_id:'tA',project_id:'pA',project_code:'PRIVATE_CASE_A',project_name:'PRIVATE_CASE_A',node_id:'nA',node_key:'sales',node_name:'NODE_A',assignee_id:workspace.users[0].id,status:'pending',due_date:'2026-10-01',title:'TASK_A'}],pending_approvals:[{id:'apA',title:'APPROVAL_A',type:'change',project_id:'pA'}],counts:{approvals_pending:3,daily_unmatched:535,my_overdue_tasks:4,my_active_tasks:12,active_tasks:30,overdue_tasks:6,due_today_tasks:2},projects:workspace.projects.map((p,i)=>{
 const {nodes,files,comments,daily_reports,...summary}=p;
 return {...summary,concurrency_version:i+7,progress:{completed_nodes:i?0:4,approved_skipped_nodes:i?0:1,total_nodes:i?0:10},overdue_tasks:i?0:2,active_tasks:5,execution_status:i?'completed':'in_progress'};
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
 const id=decodeURIComponent(url.split('/').pop());await detailGate(id);const project=workspace.projects.find(p=>p.id===id);
 if(!project)return new Response(JSON.stringify({detail:'找不到這個案件'}),{status:404});
 return json({scope:'project',version:current.version,as_of:workspace.as_of,project,settings:{},delegations:[],handover_requests:[],sop_requests:[],sop_templates:[],approved_leave_delegations:[],approvals:[],events:[],policy_summary:[],financial_requests:[],source_quotes:[],source_confirmations:[],contract_items:[],node_skip_requests:[]});
};
const pct=p=>p.progress.total_nodes?p.progress.completed_nodes/p.progress.total_nodes:0;
const overview=async(url)=>{
 const query=new URL(url,'http://x').searchParams;await overviewGate(query);
 const cards=current.projects.map((p,i)=>includeFacts?{...p,...overviewFacts[i%2]}:p),formal=p=>p.case_type!=='intake',tab=query.get('tab'),needle=(query.get('q')||'').toLowerCase(),sign=query.get('dir')==='desc'?-1:1;
 const keep={all:()=>true,formal,intake:p=>!formal(p),active:p=>p.execution_status!=='completed',overdue:p=>p.overdue_tasks>0,completed:p=>p.execution_status==='completed'}[tab];
 const key={due:p=>p.due_date||'9999',name:p=>p.name,progress:pct}[query.get('sort')];
 const hit=cards.filter(p=>keep(p)&&(!needle||(p.code+' '+p.name+' '+p.client).toLowerCase().includes(needle))&&(!query.get('owner')||p.pm_id===query.get('owner')))
  .sort((x,y)=>(key(x)<key(y)?-1:key(x)>key(y)?1:x.id<y.id?-1:1)*sign);
 const offset=Number(query.get('offset')),limit=Number(query.get('limit'));
 return json({total:hit.length,offset,limit,facets:{all:cards.length,formal:cards.filter(formal).length,intake:cards.filter(p=>!formal(p)).length},items:hit.slice(offset,offset+limit)});
};
let root;let features;let current=shell;let user=a;let etag='W/"shell-A:1"';let failMutation=false;let mutationResponse;const requests=[];
globalThis.fetch=async(url,init)=>{
 requests.push({url,init});
 if(url==='/api/session')return json({user,users:[a,b],mode:'lark',environment:'production',workspace_id:'workspace-A',auth_configured:true,features});
 if(url==='/api/workspace'){await fullGate();return json({...workspace,version:current.version});}
 if(url.startsWith('/api/projects?view=overview'))return overview(url);
 if(url.startsWith('/api/projects/'))return detail(url);
 if(url==='/api/workspace?scope=shell')return init.headers.get('If-None-Match')===etag?new Response(null,{status:304,headers:{ETag:etag}}):json(current,{ETag:etag});
 if(url==='/api/actions'||url==='/api/files')return failMutation?new Response(JSON.stringify({detail:'conflict'}),{status:409}):json(mutationResponse||{...workspace,version:2});
 throw Error('Unexpected endpoint '+url);
};
const mount=async(next)=>{if(root)await flush(()=>root.unmount());features=next;requests.length=0;root=createRoot(document.getElementById('root'));await flush(()=>root.render(React.createElement(App)))};
const lastShell=()=>requests.findLast(r=>r.url==='/api/workspace?scope=shell');
const rows=()=>[...document.querySelectorAll('.projects-table tbody tr')];
const button=text=>[...document.querySelectorAll('.tabbar button')].find(b=>b.textContent.startsWith(text));
try{
 for(const flag of [undefined,{}, {workspace_shell:false},{workspace_shell:'true'}]){
  await mount(flag);assert.deepEqual(requests.map(r=>r.url),['/api/session','/api/workspace']);
  assert.equal(window.shellContext.w.scope,undefined);assert.equal(rows().length,2);
  assert.equal(document.querySelector('.notification-button i'),null);
 }
 await mount({workspace_shell:true});
 assert.deepEqual(requests.map(r=>r.url),['/api/session','/api/workspace?scope=shell','/api/projects?view=overview&tab=formal&sort=due&dir=asc&limit=10&offset=0']);
 assert.equal(window.shellContext.w.scope,'shell');assert.equal(rows().length,2);
 assert.ok(document.querySelector('[aria-label="主要導覽"]').textContent.includes('逾期 4'));
 assert.ok(document.querySelector('.notification-button i'));assert.equal(window.shellContext.unmatchedDaily(window.shellContext.w),535);
 assert.equal(rows()[0].querySelector('.stage-chips').textContent,'外業PAUSED_STAGE');
 assert.equal(rows()[1].querySelector('.stage-chips').textContent,'');
 assert.ok(rows()[0].textContent.includes('123,456'));assert.equal(rows()[1].querySelector('td.mono.numeric').textContent,'待帶入');
 assert.equal(rows()[0].querySelector('.verification-cell').getAttribute('aria-label'),'已驗證');
 assert.equal(rows()[1].querySelector('.verification-cell').getAttribute('aria-label'),'來源待確認');
 assert.ok(rows()[0].querySelector('.attention-badges').textContent.includes('受阻'));
 assert.ok(!document.querySelector('.verification-legend').textContent.includes('摘要未提供'));
 assert.ok(document.querySelector('.verification-legend').textContent.includes('受阻僅計暫停／受阻狀態任務'));
 // Old servers keep hidden amounts and the stage dash/status hint.
 includeFacts=false;await mount({workspace_shell:true});
 assert.ok(!document.querySelector('.projects-table thead').textContent.includes('合約金額'));
 assert.ok(rows()[0].querySelector('.stage-chips').textContent.includes('—進行中'));
 assert.ok(document.querySelector('.verification-legend').textContent.includes('摘要未提供'));
 includeFacts=true;overviewFacts[0].source_lifecycle.reasons=['conflict'];await mount({workspace_shell:true});
 assert.equal(rows()[0].querySelector('.verification-cell').getAttribute('aria-label'),'不一致');assert.equal(rows()[0].querySelector('.verification-cell').textContent,'!');
 overviewFacts[0].source_lifecycle.reasons=[];await mount({workspace_shell:true});
 assert.equal(rows()[0].querySelector('.progress-cell span').textContent,'40%');
 assert.equal(rows()[1].querySelector('.progress-cell span').textContent,'0%');
 // P4-1: the dashboard renders from counts, the attention list and cards; no tree scan and no full workspace.
 await flush(()=>{location.hash='view=dashboard';window.dispatchEvent(new window.Event('hashchange'))});
 const todo=document.querySelector('.work-inbox');
 assert.ok(todo.textContent.includes('TASK_A')&&todo.textContent.includes('逾期 1 天')&&todo.textContent.includes('APPROVAL_A')&&todo.textContent.includes('NODE_A')&&todo.textContent.includes(workspace.users[0].name)&&todo.textContent.includes('逾期 6 · 當日到期 2'));
 assert.equal(todo.querySelector('.heading-count').textContent,'11');assert.ok(document.querySelector('.today-aside').textContent.includes('535 筆日報待配對'));
 assert.ok(document.querySelector('.project-preview-row').textContent.includes('PRIVATE_CASE_A'));
 assert.ok(!requests.some(r=>r.url==='/api/workspace'),'dashboard never loads the full workspace');
 // U6: status-blocked tasks include undated/future tasks, dedupe overlap, and precede due-today tasks.
 const base=shell.attention[0];const today={...base,task_id:'today',title:'DUE_TODAY',due_date:shell.as_of.slice(0,10)};
 const undated={...base,task_id:'undated',title:'UNDATED_BLOCKED',status:'paused',due_date:''};
 const future={...base,task_id:'future',title:'FUTURE_BLOCKED',status:'blocked',due_date:'2099-01-01'};
 current={...shell,attention:[today,base],blocked:[undated,{...base,status:'paused'},future],counts:{...shell.counts,blocked_tasks:8}};etag='W/"blocked"';
 await flush(()=>window.shellContext.refresh());
 const inbox=document.querySelector('.work-inbox');
 assert.ok(inbox.textContent.indexOf('TASK_A')<inbox.textContent.indexOf('UNDATED_BLOCKED'));
 assert.ok(inbox.textContent.indexOf('UNDATED_BLOCKED')<inbox.textContent.indexOf('DUE_TODAY'));
 assert.ok(inbox.textContent.indexOf('FUTURE_BLOCKED')<inbox.textContent.indexOf('DUE_TODAY'));
 assert.equal(inbox.textContent.split('TASK_A').length-1,1,'overlap is rendered once');
 assert.ok(inbox.textContent.includes('受阻 8（僅暫停／受阻狀態）')&&!inbox.textContent.includes('已載入'));
 assert.ok(inbox.textContent.includes('查看全部工作'),'blocked remainder has a link');
 const rowFor=title=>[...inbox.querySelectorAll('.ds-row')].find(r=>r.textContent.includes(title));
 assert.ok(rowFor('TASK_A').textContent.includes('受阻'),'blocked badge comes from either list');
 assert.ok(rowFor('UNDATED_BLOCKED').textContent.includes('受阻')&&!rowFor('UNDATED_BLOCKED').textContent.includes('逾期'));
 await flush(()=>rowFor('UNDATED_BLOCKED').click());assert.ok(location.hash.includes('task=undated'));
 await flush(()=>{location.hash='view=dashboard';window.dispatchEvent(new window.Event('hashchange'))});
 current={...shell,attention:[{...base,status:'paused'}]};etag='W/"old-blocked"';await flush(()=>window.shellContext.refresh());
 assert.ok(document.querySelector('.work-inbox').textContent.includes('受阻 1（已載入，僅暫停／受阻狀態）'));
 current={...shell,blocked:[],counts:{...shell.counts,blocked_tasks:0}};etag='W/"zero-blocked"';await flush(()=>window.shellContext.refresh());
 assert.ok(document.querySelector('.work-inbox').textContent.includes('受阻 0（僅暫停／受阻狀態）'));
 current=shell;etag='W/"shell-A:1"';await flush(()=>window.shellContext.refresh());
 await flush(()=>{location.hash='view=projects';window.dispatchEvent(new window.Event('hashchange'))});
 await flush(()=>button('需要關注').click());assert.equal(rows().length,1);assert.ok(rows()[0].textContent.includes('PRIVATE_CASE_A'));
 await flush(()=>button('執行中').click());assert.equal(rows().length,1);assert.ok(rows()[0].textContent.includes('PRIVATE_CASE_A'));
 await flush(()=>button('交付已完成').click());assert.equal(rows().length,1);assert.ok(rows()[0].textContent.includes('CASE_B'));
 await flush(()=>button('全部紀錄').click());
 const sort=document.querySelector('[aria-label="案件排序"]');await flush(()=>{sort.value='progress';sort.dispatchEvent(new Event('change',{bubbles:true}))});
 assert.ok(rows()[0].textContent.includes('CASE_B'),'shell progress sorts without nodes');
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

 // P4-2: server-side paging for 25 cards (20 formal): page 1 asks for ten rows, filters reset to page 1, stale answers are dropped.
 const many=Array.from({length:25},(_,i)=>({...shell.projects[1],id:`c${i}`,code:`CODE_${String(i).padStart(2,'0')}`,name:`NAME_${i}`,case_type:i%5===0?'intake':'formal',due_date:`2026-11-${String(i+1).padStart(2,'0')}`}));
 current={...shell,projects:many};etag='W/"shell-big"';
 await mount({workspace_shell:true});
 const pages=()=>requests.filter(r=>r.url.startsWith('/api/projects?view=overview')).map(r=>new URL(r.url,'http://x').searchParams);
 assert.equal(pages().length,1);assert.equal(pages()[0].get('limit'),'10');assert.equal(pages()[0].get('offset'),'0');
 assert.equal(rows().length,10);assert.ok(rows()[0].textContent.includes('CODE_01'));assert.ok(document.querySelector('.table-footer').textContent.includes('共 20 筆 · 第 1 / 2 頁'));
 assert.ok(document.querySelector('.projects-table thead').textContent.includes('合約金額'),'overview facts expose contract amounts while shell cards remain slim');
 assert.equal(document.querySelector('.portfolio-index strong').textContent,'20');
 const nextPage=[...document.querySelectorAll('.table-footer button')].find(b=>b.textContent==='下一頁');
 await flush(()=>nextPage.click());assert.equal(pages().at(-1).get('offset'),'10');assert.equal(rows().length,10);assert.ok(rows()[0].textContent.includes('CODE_13'));
 assert.ok([...document.querySelectorAll('.table-footer button')].find(b=>b.textContent==='下一頁').disabled);
 const size=document.querySelector('[aria-label="每頁筆數"]');
 await flush(()=>{size.value='25';size.dispatchEvent(new Event('change',{bubbles:true}))});
 assert.equal(pages().at(-1).get('limit'),'25');assert.equal(pages().at(-1).get('offset'),'0');assert.equal(rows().length,20,'size change returns to page 1');
 await flush(()=>{size.value='10';size.dispatchEvent(new Event('change',{bubbles:true}))});
 await flush(()=>[...document.querySelectorAll('.table-footer button')].find(b=>b.textContent==='下一頁').click());assert.equal(pages().at(-1).get('offset'),'10');
 await flush(()=>button('待確認接案').click());assert.equal(pages().at(-1).get('tab'),'intake');assert.equal(pages().at(-1).get('offset'),'0','tab change returns to page 1');assert.equal(rows().length,5);
 await flush(()=>button('正式案件').click());await flush(()=>[...document.querySelectorAll('.table-footer button')].find(b=>b.textContent==='下一頁').click());
 const ownerSelect=document.querySelector('[aria-label="篩選專案經理"]');
 await flush(()=>{ownerSelect.value='actor-A';ownerSelect.dispatchEvent(new Event('change',{bubbles:true}))});assert.equal(pages().at(-1).get('offset'),'0');assert.equal(pages().at(-1).get('owner'),'actor-A','owner filter reaches the server');
 await flush(()=>{ownerSelect.value='all';ownerSelect.dispatchEvent(new Event('change',{bubbles:true}))});
 const search=document.querySelector('[aria-label="搜尋案件"]');const before=pages().length
 await flush(()=>{search.value='CODE_2';Simulate.change(search)});
 assert.equal(pages().length,before,'typing is debounced');await flush(()=>new Promise(resolve=>setTimeout(resolve,320)));
assert.equal(pages().at(-1).get('q'),'CODE_2');assert.equal(pages().length,before+1);assert.equal(rows().length,4);
 await flush(()=>search.parentElement.querySelector('button').click());await flush(()=>new Promise(resolve=>setTimeout(resolve,320)));assert.equal(pages().at(-1).get('q'),null);
 // A slow answer for an older query must never overwrite the newer one.
 let release;const slow=new Promise(resolve=>{release=resolve});overviewGate=async query=>{if(query.get('tab')==='intake')await slow};
 await flush(()=>button('待確認接案').click());await flush(()=>button('正式案件').click());
 assert.equal(pages().at(-1).get('offset'),'0','returning to an earlier filter starts at page 1');assert.equal(rows().length,10);assert.ok(rows()[0].textContent.includes('CODE_01'));
 await flush(async()=>{release();await slow});assert.equal(rows().length,10);assert.ok(rows()[0].textContent.includes('CODE_01'),'stale intake page did not overwrite formal page');
 overviewGate=async()=>{};

 // P4-3: opening a case reads that one project; tabs are client-side; a mutation hands over to the full workspace.
 current=shell;etag='W/"shell-A:1"';failMutation=false;mutationResponse=undefined;location.hash='view=project&project=pA';
 await mount({workspace_shell:true});
 const goto=async hash=>flush(()=>{location.hash=hash;window.dispatchEvent(new window.Event('hashchange'))});
 const detailUrls=()=>requests.map(r=>r.url).filter(u=>u.startsWith('/api/projects/'));
 assert.deepEqual(requests.map(r=>r.url),['/api/session','/api/workspace?scope=shell','/api/projects/pA']);
 assert.ok(document.querySelector('.workspace').textContent.includes('PRIVATE_CASE_A')&&document.querySelector('.workspace').textContent.includes('TASK_A'),'detail renders the project tree');
 await goto('view=project&project=pA&tab=flow');await goto('view=project&project=pA&tab=data&section=basic');assert.deepEqual(detailUrls(),['/api/projects/pA'],'tabs do not refetch the project');
 await goto('view=project&project=pB');assert.deepEqual(detailUrls(),['/api/projects/pA','/api/projects/pB']);assert.ok(document.querySelector('.workspace').textContent.includes('CASE_B'));
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
 await goto('view=work');assert.equal(fullReads(),1);assert.ok(document.querySelector('.workspace [role="status"]').textContent.includes('正在載入完整資料'),'loading state while the full read is pending');
 assert.ok(document.querySelector('[aria-label="主要導覽"]'),'the shell stays usable while a screen loads');
 await flush(async()=>{openFull();await heldFull});fullGate=async()=>{};
 assert.ok(document.querySelector('.workspace').textContent.includes('TASK_A'),'my work renders the loaded task');
 for(const view of ['approvals','schedule','routines','admin','work'])await goto('view='+view);
 assert.equal(fullReads(),1,'one full read per shell version, shared by every screen');
 await goto('view=dashboard');await flush(()=>[...document.querySelectorAll('.today-activity button')].find(b=>b.textContent==='載入近期活動').click());
 assert.equal(fullReads(),1);assert.ok(document.querySelector('.today-activity').textContent.includes('尚無操作紀錄'));
 current={...shell,version:5};etag='W/"shell-A:5"';await flush(()=>window.shellContext.refresh());await goto('view=approvals');
 assert.equal(fullReads(),2,'a newer shell version reads the full workspace again');
 await flush(()=>window.shellContext.run('case_execution_assign',{execution_system:'workbench'},{project_id:'pA'}));
 await goto('view=schedule');await goto('view=work');assert.equal(fullReads(),2,'after a mutation the app holds the full workspace and reads nothing');
 console.log('Shell mode: feature gating, server-side paging/filter reset/stale-response guard, lazy single-project detail, on-demand full workspace, summary-only render/filter/sort, badges, 304, identity cache, mutation/upload concurrency and 409 passed');
}finally{await flush(()=>root.unmount());dom.window.close()}
