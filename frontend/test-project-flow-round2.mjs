import assert from 'node:assert/strict';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {response as dispatchExample} from './qa/dispatch-api-examples.mjs';
import {projectFixture,embeddedAssignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','HTMLDetailsElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){globalThis.lastScroll=this.id};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetail} from './src/ProjectDetail'; export {AppShell} from './src/AppShell'; export {invalidateSessionEpoch} from './src/api'; export {prefetchNodeAssignmentDetail} from './src/useNodeAssignments';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.project-flow-ui.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));progress.project_id='p1';
let root,c,fixture,calls,hold,evidenceStatus=200,nodeStatus=200,detailStatus=200,mutationStatus=200;
const tick=()=>new Promise(r=>setTimeout(r,15));
async function mount({tab='flow',node,task,enabled=true,role='manager',dispatch=false,assign=true,evidenceHold=false,embedded=true,parentProject='p1',shell=false,detailHold=false,configure=()=>{}}={}){
 if(root)await act(async()=>root.unmount());ui.invalidateSessionEpoch();
 const base=projectFixture();fixture=embeddedAssignmentFixture();
 for(const n of fixture.list.nodes){n.departments=['控制'];fixture.list.node_details[n.key].assignable_people.forEach(p=>p.departments=['控制']);}
 fixture.list.node_details.control.tasks.push({...fixture.detail.tasks[0],id:'recUnassigned',title:'尚待指派的核對任務',assignee:null,deadline:'2026-10-01'});
 if(!assign){fixture.list.can.control.assign=false;fixture.list.node_details.control.tasks.forEach(t=>t.can.assign=false)}
 configure(base,fixture);const detailPayloads=fixture.list.node_details;if(!embedded)delete fixture.list.node_details;globalThis.detailPayloads=detailPayloads;
 calls=[];let releaseEvidence;hold=evidenceHold?new Promise(r=>releaseEvidence=r):null;globalThis.releaseEvidence=releaseEvidence;
 c={w:base.workspace,s:{user:{...base.user,role},mode:'lark',workspace_id:'flow-company',features:{node_assignment:enabled,dispatch_write:dispatch}},route:{view:'project',project:'p1',tab,node,task},busy:false,run:async()=>true,notify(){},registerDrafts(){},refresh:async()=>{},go(route,replace){history[replace?'replaceState':'pushState']({},'', '#'+new URLSearchParams(Object.entries(route).filter(([,v])=>v!==undefined)));c={...c,route};render()}};
 globalThis.fetch=async(url,init={})=>{calls.push({url,method:init.method||'GET',body:init.body?JSON.parse(init.body):null});
  if(url.endsWith('/progress')){if(hold)await hold;return response(evidenceStatus===200?progress:{detail:'合成證據讀取失敗'},evidenceStatus)}
  if(url.endsWith('/node-assignments'))return response(nodeStatus===200?fixture.list:{detail:'合成節點來源失敗'},nodeStatus);
  if(url.includes('/node-assignments/nodes/')){
   if(detailHold && (init.method||'GET')==='GET'){const old=structuredClone({...fixture.list,node:fixture.list.nodes.find(n=>n.key==='control'),can:fixture.list.can.control,...detailPayloads.control});await new Promise(r=>globalThis.releaseDetail=r);return response(old)}
   const key=url.split('/nodes/')[1].split('/')[0];const node=fixture.list.nodes.find(n=>n.key===key);if((init.method||'GET')==='GET'&&detailStatus!==200)return response({detail:'合成任務明細失敗'},detailStatus);
   if(init.method==='PATCH'){
    if(mutationStatus!==200)return response({detail:'沒有指派權限',code:'forbidden'},mutationStatus);
    const t=fixture.list.node_details[key].tasks.find(t=>t.id===url.split('/').at(-1));const patch=JSON.parse(init.body);if(patch.status)t.status=patch.status;else t.assignee={open_id:patch.assignee_open_id,name:'林安娜'};
   }
   return response({...fixture.list,node,can:fixture.list.can[key],...detailPayloads[key]});
  }
  if(url.includes('/dispatch/work'))return response({source:{quality:{states:['complete']}},rows:[{task_id:'recObligation',title:'控制義務',project_id:parentProject,kind:'obligation',phase:'正式',status:'待處理',department:'控制',case:{ref:'recCase',code:'C001',name:'合成確認單'},node_position:'控制',source:'v4_task'}]});
  if(url.endsWith('/dispatch/options'))return response({people:[{person_ref:'ou_anna',open_id:'ou_anna',name:'林安娜',active:true,has_lark_account:true}],instruments:[],vehicles:[],cases:[{ref:'recCase',code:'C001',name:'合成確認單'}],departments:['控制'],seats:[],joins:{}});
  if(url.endsWith('/dispatch/previews')){const data=dispatchExample('decision: PM final accepts');data.proposal=JSON.parse(init.body);data.crew=data.proposal.crew.map(person_ref=>({person_ref,name:'林安娜',feasibility:'feasible'}));data.resources=[];data.expires_at='2099-01-01T00:00:00Z';return response(data)}
  if(url.endsWith('/dispatch/commits')){fixture.list.node_details.control.tasks.push({...fixture.detail.tasks[0],id:'recPublished',record_id:'recPublished',title:'已發布的新排班'});return response({command:{command_id:JSON.parse(init.body).command_id,state:'committed',revision:1,task_record_id:'recPublished'}})}
  return response({detail:'disabled'},404);
 };
 function render(){const child=React.createElement(ui.ProjectDetail,{c});root.render(shell?React.createElement(ui.AppShell,{...c,s:c.s,w:c.w,route:c.route,ready:true,setMobile(){},setError(){},go:c.go,refresh:c.refresh,overdue:0,children:child}):child)}
 root=createRoot(document.getElementById('root'));await act(async()=>{render();await tick()});
}
function response(body,status=200){return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}})}
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
const click=async element=>{assert.ok(element,'requested control exists');assert.equal(element.disabled,false,element.textContent);await act(async()=>{element.click();await tick()})};
const value=async(el,v)=>act(async()=>{Object.getOwnPropertyDescriptor(el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(el,v);el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));await tick()});

const failures=[];
async function check(name,run){try{await run();console.log('PASS '+name)}catch(error){failures.push(name);console.error('FAIL '+name+' '+error.stack)}}
const secondary=name=>[...document.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent===name);
await check('round2 local workflow stays available with assignments',async()=>{
 await mount({node:'control',configure(base){base.project.nodes[4].tasks=[{id:'local',title:'本地驗收',status:'in_progress',owner_id:'ou_anna',required:true,can_execute:true,confirmation_hash:'fixture-confirmation',comments:[],description:'範本',revision:1}];}});
 const local=secondary('範本與本地流程');assert.equal(local?.open,false);assert.match(local.textContent,/增補任務/);assert.match(local.textContent,/本地驗收/);assert.match(local.textContent,/進行中/);assert.match(local.textContent,/一次確認我的成果（1）/);await click([...local.querySelectorAll('button')].find(b=>b.textContent==='本地驗收'));assert.equal(document.querySelector('[role=dialog]').getAttribute('aria-label'),'本地驗收');assert.doesNotMatch(document.querySelector('#flow-tasks').textContent,/找不到此 Lark 任務/);
});
await check('legacy task drawer shows facts, tabs and one footer reason',async()=>{
 await mount({node:'control',configure(base){base.project.nodes[4].tasks=[{id:'local',title:'本地驗收',status:'in_progress',owner_id:'ou_anna',required:true,can_execute:true,confirmation_hash:'fixture-confirmation',comments:[],description:'範本',revision:1}];}});
 await click([...secondary('範本與本地流程').querySelectorAll('button')].find(b=>b.textContent==='本地驗收'));
 const drawer=document.querySelector('[role=dialog]');
 assert.equal(drawer.dataset.kind,'legacy');
 assert.deepEqual([...drawer.querySelectorAll('.task-drawer-trail>span')].map(s=>s.textContent),['YX-2026-042','控制']);
 assert.deepEqual([...drawer.querySelectorAll('.inspector-tabs button')].map(b=>b.textContent),['任務詳情','評論0','歷程']);
 assert.deepEqual([...drawer.querySelectorAll('.task-drawer-facts dt')].map(d=>d.textContent),['負責人','排程','期限','工項','營業額點數']);
 const footer=drawer.querySelector('.task-drawer-footer');
 assert.equal(footer.querySelector('.task-drawer-off').textContent,'展延未開放');
 assert.deepEqual([...footer.querySelectorAll('.disabled-action-reason')].map(r=>r.textContent),['請填寫成果']);
 assert.equal(drawer.textContent.split('請填寫成果').length,2);
 await click(drawer.querySelector('[aria-label=關閉]'));
 assert.equal(document.querySelector('[role=dialog]'),null);
});
await check('round2 local flow list translates both pending and in-progress task statuses',async()=>{
 await mount({enabled:false,node:'node_control',configure(base){base.project.nodes[4].tasks=[{id:'l1',title:'待開始工作',status:'pending',owner_id:'ou_anna'},{id:'l2',title:'進行工作',status:'in_progress',owner_id:'ou_anna'}]}});
 assert.deepEqual([...document.querySelectorAll('#flow-tasks .pf-task-open>span')].map(n=>n.textContent),['林安娜 · 尚未開始 · 未排期限','林安娜 · 進行中 · 未排期限']);
});
await check('round2 completed and skipped steps show state without progress bars',async()=>{
 await mount({node:'control',configure(base,f){Object.assign(f.list.nodes.find(n=>n.key==='control'),{derived_status:'已完成'});f.list.nodes.find(n=>n.key==='mapping').derived_status='略過';}});
 const completed=document.querySelector('.pf-node[aria-label^="控制節點"]'),skipped=document.querySelector('.pf-node[aria-label^="圖資節點"]');
 assert.equal(completed.querySelector('progress'),null);assert.equal(completed.querySelector('.pf-state').textContent,'已完成');assert.match(completed.getAttribute('aria-label'),/100%/);assert.equal(skipped.querySelector('progress'),null);assert.equal(skipped.querySelector('.pf-state').textContent,'略過');assert.equal(completed.querySelector('.pf-needs'),null);assert.equal(skipped.querySelector('.pf-needs'),null);
});
await check('round2 keyboard replaces history and never scrolls the selected panel',async()=>{
 let shellScroll=0;window.scrollTo=()=>shellScroll++;await mount({node:'control',shell:true});await act(tick);const before=history.length,scrollBefore=shellScroll;globalThis.lastScroll='untouched';
 const selected=document.querySelector('.pf-node[aria-current]');selected.focus();
 await act(async()=>{selected.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));await tick()});
 assert.equal(c.route.node,'mapping');assert.equal(history.length,before);assert.equal(shellScroll,scrollBefore);assert.equal(globalThis.lastScroll,'untouched');assert.equal(document.activeElement.getAttribute('aria-current'),'step');
});
await check('round2 one selected node for panel and local operations',async()=>{
 await mount({configure(base,f){f.list.summary.current_node='field';base.project.nodes[3].description='外業背景';base.project.nodes[3].collaborator_ids=['ou_anna'];}});
 assert.equal(document.querySelector('#flow-selected h2').textContent,'外業');assert.match(document.querySelector('.flow-operations .ops-heading p').textContent,/外業 · SOP/);
 await click(button('增補任務'));assert.match(document.querySelector('[role=dialog]').textContent,/增補任務 · 外業/);
});
await check('round2 dispatch independent of node writes',async()=>{
 await mount({node:'control',dispatch:true,configure(base,f){f.list.writes_enabled=false;f.list.writes_disabled_reason='節點封鎖';f.list.can.control.create_task=false}});
 assert.equal(button('排班').disabled,false);await click(button('排班'));assert.equal(fieldFor('父義務').value,'recObligation');
});
function fieldFor(label){return [...document.querySelectorAll('.dp-field')].find(l=>l.firstElementChild.textContent===label)?.querySelector('input,select')}
await check('round2 source timestamp and honest manager fallback',async()=>{
 await mount({node:'control',configure(base,f){f.list.fetched_at='2026-10-18T00:00:00Z'}});
 assert.match(document.querySelector('.pf-source').textContent,/節點與任務.*2026\/10\/18 08:00:00 \(台北時間\)/);assert.doesNotMatch(document.querySelector('.pf-source').textContent,/節點 N/);
 const fact=[...document.querySelectorAll('.pf-facts>div')].find(d=>d.querySelector('dt').textContent==='組別主管');assert.equal(fact.querySelector('dd').textContent,'未能對應到本組主管');
});
await check('round2 overview is a real destination with one workflow strip',async()=>{await mount({tab:'overview'});await act(tick);assert.ok(document.querySelector('.project-overview'));assert.equal(document.querySelectorAll('.project-overview .pf-diagram').length,1);assert.equal(document.querySelector('.pf-overall'),null);assert.equal(document.querySelectorAll('.po-todo-primary button').length,1);assert.equal(document.querySelectorAll('.po-items-table').length,1);assert.deepEqual([...document.querySelectorAll('.po-kpi>span')].map(el=>el.textContent),['外業關聯工項','已指派待辦','待核對事項']);assert.doesNotMatch([...document.querySelectorAll('.po-kpi strong')].map(el=>el.textContent).join(' '),/未知|待核對|依各工項顯示/);assert.ok(document.querySelector('.pf-diagram').nextElementSibling.classList.contains('po-todos'));assert.doesNotMatch(document.querySelector('.po-sidebar').textContent,/來源未提供/);assert.equal(document.querySelectorAll('.po-items-table [data-item-id]').length,progress.production.field.items.length);assert.equal(document.querySelector('#flow-selected'),null);assert.equal(document.querySelector('.pds-tabs [aria-current=page]').textContent,'總覽')});
await check('overview hides empty documents and reduces empty items to one line',async()=>{
 const saved=structuredClone(progress.production.field);Object.assign(progress.production.field,{items:[],items_total:0});
 try{await mount({tab:'overview',configure(base){base.project.files=[];delete base.project.project_type;delete base.project.planned_start_date;delete base.project.planned_end_date;delete base.project.original_due_date;}});assert.equal(document.querySelector('.po-documents'),null);assert.equal(document.querySelector('.po-dates'),null);assert.equal(document.querySelector('.po-items.po-card'),null);assert.match(document.querySelector('.po-items-empty').textContent,/尚未連結外業工項.*查看工項/);assert.equal(document.querySelector('.po-items-table'),null);assert.doesNotMatch(document.querySelector('.po-sidebar').textContent,/來源未提供/);}
 finally{Object.assign(progress.production.field,saved)}
});
await check('overview item preview opens the immutable item in the existing inspector',async()=>{await mount({tab:'overview'});const rows=[...document.querySelectorAll('.po-items-table tbody tr')];assert.ok(rows.length);const row=rows.at(-1),id=row.dataset.itemId,link=row.querySelector('a');assert.equal(new URLSearchParams(link.hash.slice(1)).get('section'),`item:${id}`);await act(async()=>{link.click();await tick()});assert.equal(c.route.tab,'items');assert.equal(c.route.node,'field');assert.equal(c.route.section,`item:${id}`);assert.ok(document.querySelector('[role=dialog]'));assert.ok(document.querySelector('[role=dialog]').textContent.includes(id));});
await check('overview keeps the workflow visible while evidence loads or fails',async()=>{
 await mount({tab:'overview',evidenceHold:true});assert.match(document.querySelector('.po-items').textContent,/工項資料載入中/);assert.equal(document.querySelectorAll('.project-overview .pf-node').length,9);await act(async()=>{globalThis.releaseEvidence();await tick()});
 evidenceStatus=500;await mount({tab:'overview'});assert.match(document.querySelector('.po-items').textContent,/工程證據暫不可用/);assert.equal(document.querySelectorAll('.po-todo-primary button').length,1);assert.equal(document.querySelectorAll('.project-overview .pf-node').length,9);evidenceStatus=200;
});
await check('overview labels stale assignments and denied sources without hiding other sections',async()=>{
 await mount({tab:'overview',configure(base,f){f.list.stale=true;f.list.stale_reason='合成上次資料'}});assert.match(document.querySelector('.project-overview').textContent,/上次成功資料/);assert.equal(document.querySelector('.po-todo-primary button').textContent,'查看詳情');
 nodeStatus=403;await mount({tab:'overview'});assert.match(document.querySelector('.po-source-state').textContent,/暫不可用/);assert.ok(document.querySelector('[aria-label="案件重點指標"]'));assert.equal(document.querySelectorAll('.po-todo-primary button').length,1);nodeStatus=200;
});
await check('round2 attention excludes manager-wide completion and unowned not-started nodes',async()=>{
 await mount({configure(base,f){f.list.node_details.control.tasks.forEach(t=>t.assignee={open_id:'other',name:'別人'});f.list.nodes.forEach(n=>n.owners=[{open_id:'other',name:'別人'}]);}});
 assert.equal(document.querySelector('.pf-attention').textContent,'');
});
await check('round2 attention includes actual pending task, approval and owned not-started work',async()=>{
 await mount({configure(base,f){f.list.nodes.forEach(n=>n.owners=[]);f.list.nodes.find(n=>n.key==='mapping').derived_status='待審核';f.list.nodes.find(n=>n.key==='report').owners=[{open_id:'ou_anna',name:'林安娜'}];}});
 assert.deepEqual([...document.querySelectorAll('.pf-attention button')].map(b=>b.textContent),['控制 · 待認領','圖資 · 待審核','報告 · 待處理']);
});
await check('round2 manager resolved from loaded users and absent source distinguished',async()=>{
 await mount({node:'control',configure(base){base.workspace.users[0].department='控制'}});
 const manager=()=>[...document.querySelectorAll('.pf-facts>div')].find(d=>d.querySelector('dt').textContent==='組別主管').querySelector('dd').textContent;
 assert.equal(manager(),'林安娜');
 await mount({node:'control',configure(base,f){f.list.nodes.find(n=>n.key==='control').departments=[]}});assert.equal(manager(),'來源未提供負責組別，未能對應到本組主管');
});
await check('round2 background and file shortcut restored collapsed',async()=>{
 await mount({node:'control',configure(base){Object.assign(base.project.nodes[4],{description:'節點背景說明',collaborator_ids:['ou_anna'],started_at:'2026-10-10'})}});
 const background=secondary('節點說明與背景');assert.equal(background?.open,false);assert.match(background.textContent,/節點背景說明/);assert.match(background.textContent,/林安娜/);assert.match(background.textContent,/經過.*4.*天/);assert.match(background.textContent,/開啟 作業資料與成果/);
});
await check('round2 assignment readback wins over an in-flight stale detail and avoids refetch',async()=>{
 await mount({node:'control',detailHold:true});await click(button('指派'));await value(document.querySelector('select[aria-label="任務負責人"]'),'ou_anna');
 const pending=ui.prefetchNodeAssignmentDetail('p1','control',undefined,true);
 await click(button('儲存指派'));globalThis.releaseDetail();await act(async()=>{await pending;await tick()});
 const row=document.querySelector('[data-assignment-task="recUnassigned"]');assert.match(row.textContent,/林安娜/);assert.doesNotMatch(row.textContent,/尚未指派/);
 assert.equal(calls.filter(c=>c.url.endsWith('/nodes/control')).length,1);assert.equal(calls.filter(c=>c.url.endsWith('/node-assignments')).length,1);
});
evidenceStatus=500;
await check('round2 failed evidence retains node and offers retry in item sheet',async()=>{
 await mount({node:'control',configure(base,f){f.list.nodes.find(n=>n.key==='control').evidence={planned_qty:'12',lines:1,items:1,work_orders:0,latest_date:null,actual_known:false,actual_value:null,actual_source:null,reason:'未連結',drives_status:false,progress:null,items_total:1,items_truncated:false,work_items:[{code:'X1',name:'控制點',planned_qty:'12',planned_points:null,remaining_points:null,status:'no_signal',link_basis:'native'}]}}});await click(document.querySelector('.na-wi-row'));
 const link=document.querySelector('.na-evidence-link');assert.equal(link.textContent.trim(),'查看此節點證據');assert.match(link.getAttribute('href'),/node=control/);
 assert.match(document.querySelector('[role=dialog]').textContent,/重試工程證據/);
});
evidenceStatus=200;
const seedDetail='依計畫數量完成控制。\n計畫數量：999\n合約明細：9 筆；工項：9 項\n工項連結：原生 9、推導 0、待確認 0、未連結 0\n[SOP-START:v1:control]';
const seedConfig=(base,f)=>{Object.assign(f.list.node_details.control.tasks[0],{title:'控制：依計畫數量完成',detail:seedDetail});};
await check('production seed is one task with expanded evidence, unique item IDs and no raw marker',async()=>{
 await mount({node:'control',configure:seedConfig});
 const seed=document.querySelector('[data-assignment-task="recTask1"]');
 assert.equal(seed.querySelector('strong').textContent,'依計畫數量完成');
 assert.equal(seed.querySelector('#flow-evidence').open,true);
 assert.equal(document.querySelectorAll('#flow-selected .pf-plan-facts').length,1);
 assert.equal(seed.querySelector('.pf-plan-facts dd').textContent,progress.production.control.planned.qty);
 assert.doesNotMatch(seed.textContent,/999|SOP-START/);
 assert.deepEqual([...seed.querySelectorAll('[data-item-id]')].map(row=>row.dataset.itemId),progress.production.control.items.map(item=>item.item_id));
 await click(seed.querySelector('.pf-task-open'));
 assert.doesNotMatch(document.querySelector('[role=dialog]').textContent,/SOP-START|999/);
 assert.ok(document.querySelector('select[aria-label="任務狀態"]'));
 await value(document.querySelector('select[aria-label="任務狀態"]'),'已完成');await click(button('儲存任務'));
 assert.equal(calls.findLast(call=>call.method==='PATCH').body.status,'已完成');
 await click(document.querySelector('[role=dialog] [aria-label=關閉]'));
 assert.match(document.querySelector('[data-assignment-task="recTask1"]').textContent,/已完成/);
 await click([...seed.querySelectorAll('button')].find(b=>b.textContent==='改派'));
 assert.ok(document.querySelector('select[aria-label="任務負責人"]'));
 await value(document.querySelector('select[aria-label="任務負責人"]'),'ou_anna');await click(button('儲存指派'));
 assert.match(document.querySelector('[data-assignment-task="recTask1"]').textContent,/林安娜/);
 await act(async()=>{document.querySelector('#flow-evidence a').click();await tick()});
 assert.equal(c.route.tab,'items');assert.equal(c.route.node,'control');
});
await check('production fallback uses task facts while evidence loads and keeps the plan visible when filtered',async()=>{
 await mount({node:'control',configure:seedConfig,evidenceHold:true});
 assert.match(document.querySelector('.pf-plan-facts').textContent,/999/);
 assert.doesNotMatch(document.querySelector('#flow-selected').textContent,/SOP-START/);
 await act(async()=>{globalThis.releaseEvidence();await tick()});
 assert.doesNotMatch(document.querySelector('.pf-plan-facts').textContent,/999/);
 await click(button('未指派'));
 assert.equal(document.querySelectorAll('#flow-selected .pf-plan-facts').length,1);
 assert.equal(document.querySelector('#flow-evidence').open,true);
});
await check('completed node reopen stays secondary and preserves the reason form',async()=>{
 await mount({node:'control',configure(base,f){f.list.nodes.find(n=>n.key==='control').derived_status='已完成';f.list.can.control={claim:false,assign:false,complete:false,approve:false,reject:true,create_task:false}}});
 assert.equal(button('取消完成').classList.contains('primary'),false);
 assert.equal(document.querySelector('.pf-next-line'),null);
 await click(button('取消完成'));assert.match(document.querySelector('.ne-form').textContent,/取消完成/);
});
await check('legacy direct completion stays enabled when ordinary SOP writes are policy-blocked',async()=>{
 await mount({tab:'overview',node:'control',configure(base,f){f.list.writes_enabled=false;f.list.writes_disabled_reason='舊案維持原流程';f.list.can.control={legacy_complete:true};}});
 assert.equal(button('直接標記完成').disabled,false);
 assert.equal(document.querySelector('.pf-node-actions button.primary'),null);
 await click(button('直接標記完成'));
 assert.ok(document.querySelector('.assignment-edit textarea'));
});
await act(async()=>root.unmount());assert.deepEqual(failures,[]);
