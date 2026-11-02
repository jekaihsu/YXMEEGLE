import assert from 'node:assert/strict';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {response as dispatchExample} from './qa/dispatch-api-examples.mjs';
import {projectFixture,embeddedAssignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','Element','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','HTMLDetailsElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){globalThis.lastScroll=this.id};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetail} from './src/ProjectDetail'; export {AppShell} from './src/AppShell'; export {LocalNodeActions} from './src/LocalNodeActions'; export {invalidateSessionEpoch} from './src/api'; export {prefetchNodeAssignmentDetail} from './src/useNodeAssignments';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.project-flow-round2-bundle.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
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
 function render(){const child=React.createElement(ui.ProjectDetail,{c});root.render(React.createElement(React.Suspense,{fallback:null},shell?React.createElement(ui.AppShell,{...c,s:c.s,w:c.w,route:c.route,ready:true,setMobile(){},setError(){},go:c.go,refresh:c.refresh,overdue:0,children:child}):child))}
 root=createRoot(document.getElementById('root'));await act(async()=>{render();await tick()});
}
function response(body,status=200){return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}})}
async function schedule(){
 await act(async()=>{c.go({...c.route,tab:'people'});await tick()});
 const disclosure=document.querySelector('.people-manage');
 if(disclosure)await act(async()=>{disclosure.open=true;disclosure.dispatchEvent(new Event('toggle'));await tick()});
 await click(button('排班'));
}
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
async function more(){const menu=document.querySelector('.pf-more');if(menu&&!menu.open)await act(async()=>{menu.open=true;menu.dispatchEvent(new Event('toggle'));await tick()})}
const click=async element=>{assert.ok(element,'requested control exists');assert.equal(element.disabled,false,element.textContent);await act(async()=>{element.click();await tick()})};
const value=async(el,v)=>act(async()=>{Object.getOwnPropertyDescriptor(el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(el,v);el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));await tick()});

const failures=[];
async function check(name,run){try{await run();console.log('PASS '+name)}catch(error){failures.push(name);console.error('FAIL '+name+' '+error.stack)}}
const secondary=name=>[...document.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent===name);
await check('local tasks remain reachable by deep link without the removed template accordion',async()=>{
 await mount({enabled:false,node:'node_control',task:'local',configure(base){base.project.nodes[4].tasks=[{id:'local',title:'本地驗收',status:'in_progress',owner_id:'ou_anna',required:true,can_execute:true,comments:[],description:'範本',revision:1}];}});
 assert.equal(secondary('範本與本地流程'),undefined);assert.equal(document.querySelector('[role=dialog]').getAttribute('aria-label'),'本地驗收');
});
await check('legacy task drawer shows facts, tabs and one footer reason',async()=>{
 await mount({enabled:false,node:'node_control',task:'local',configure(base){base.project.nodes[4].tasks=[{id:'local',title:'本地驗收',status:'in_progress',owner_id:'ou_anna',required:true,can_execute:true,confirmation_hash:'fixture-confirmation',comments:[],description:'範本',revision:1}];}});

 const drawer=document.querySelector('[role=dialog]');
 assert.equal(drawer.dataset.kind,'legacy');
 assert.deepEqual([...drawer.querySelectorAll('.task-drawer-trail>span')].map(s=>s.textContent),['YX-2026-042','控制']);
 assert.deepEqual([...drawer.querySelectorAll('.inspector-tabs button')].map(b=>b.textContent),['任務詳情','評論','歷程'],'a zero comment count is hidden');
 assert.equal(drawer.querySelector('.task-drawer-eyebrow'),null,'no template/version eyebrow');
 assert.doesNotMatch(drawer.textContent,/V1|已依排程啟用/);
 assert.deepEqual([...drawer.querySelectorAll('.task-drawer-facts dt')].map(d=>d.textContent),['負責人'],'unknown schedule, work item and points are not listed');
 const footer=drawer.querySelector('.task-drawer-footer');
 assert.equal(footer.querySelector('.task-drawer-off'),null);
 assert.equal(footer.querySelector('.disabled-action-reason'),null);
 assert.deepEqual([...footer.querySelectorAll('.task-drawer-primary button')].map(b=>[b.textContent,b.disabled]),[['完成任務',true]],'one primary, disabled until a result is written');
 assert.equal(footer.querySelector('.task-drawer-primary button').getAttribute('aria-describedby'),'task-output-hint');
 assert.equal(drawer.querySelector('#task-output-hint').closest('.task-drawer-footer'),null,'the unmet-requirement text sits outside the footer');
 assert.equal(drawer.textContent.split('請先填寫成果').length,2);
 await click(drawer.querySelector('[aria-label=關閉]'));
 assert.equal(document.querySelector('[role=dialog]'),null);
});
await check('round2 local flow list translates both pending and in-progress task statuses',async()=>{
 await mount({enabled:false,node:'node_control',configure(base){base.project.nodes[4].tasks=[{id:'l1',title:'待開始工作',status:'pending',owner_id:'ou_anna'},{id:'l2',title:'進行工作',status:'in_progress',owner_id:'ou_anna'}]}});
 assert.deepEqual([...document.querySelectorAll('#flow-tasks .pf-task-open>span')].map(n=>n.textContent),['待處理林安娜未排期限','進行中林安娜未排期限']);
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
 assert.equal(document.querySelector('.pf-selected-heading'),null);assert.match(document.querySelector('#flow-selected').getAttribute('aria-label'),/外業/);assert.match(document.querySelector('.flow-operations .ops-heading p').textContent,/外業 · SOP/);
 assert.ok(document.querySelector('.flow-operations'));assert.equal(document.querySelectorAll('h2').length>0,true);
});
await check('round2 dispatch independent of node writes',async()=>{
 await mount({node:'control',dispatch:true,configure(base,f){f.list.writes_enabled=false;f.list.writes_disabled_reason='節點封鎖';f.list.can.control.create_task=false}});
 assert.ok(document.querySelector('a[href*=people]'));await schedule();assert.equal(fieldFor('父義務').value,'recObligation');
});
function fieldFor(label){return [...document.querySelectorAll('.dp-field')].find(l=>l.firstElementChild.textContent===label)?.querySelector('input,select')}
await check('flow omits the source timestamp and duplicate node facts',async()=>{
 await mount({node:'control',configure(base,f){f.list.fetched_at='2026-10-18T00:00:00Z'}});
 assert.equal(document.querySelector('.pf-source'),null);
 assert.equal(document.querySelector('.pf-facts'),null);
});
await check('overview has one summary and task list without a stepper or duplicate previews',async()=>{
 await mount({tab:'overview'});assert.ok(document.querySelector('.cs-summary'));assert.equal(document.querySelectorAll('.project-overview .pf-diagram').length,0);assert.equal(document.querySelectorAll('#flow-tasks').length,1);assert.equal(document.querySelector('.po-items-table'),null);assert.equal(document.querySelector('.po-documents'),null);assert.equal(document.querySelector('.pds-tabs [aria-current=page]').textContent,'總覽');
 assert.ok([...document.querySelectorAll('.po-team dt')].filter(n=>n.textContent==='執行人').length<=1);
});
await check('overview task list remains visible while evidence loads or fails',async()=>{
 await mount({tab:'overview',evidenceHold:true});assert.equal(document.querySelectorAll('.pf-task-open').length,2);await act(async()=>{globalThis.releaseEvidence();await tick()});
 evidenceStatus=500;await mount({tab:'overview'});assert.equal(document.querySelectorAll('.pf-task-open').length,2);evidenceStatus=200;
});
await check('stale data cannot recommend writes and source errors retain retry and reason',async()=>{
 await mount({tab:'overview',configure(base,f){f.list.stale=true;f.list.stale_reason='合成上次資料'}});assert.doesNotMatch(document.querySelector('.project-overview').textContent,/上次成功資料|可能已過期/);assert.equal(document.querySelector('.cs-next .button.primary'),null);
 nodeStatus=403;await mount({tab:'overview'});assert.match(document.querySelector('.cs-summary [role=alert]').textContent,/合成節點來源失敗/);assert.ok(button('重試'));nodeStatus=200;
});
await check('round2 attention excludes manager-wide completion and unowned not-started nodes',async()=>{
 await mount({configure(base,f){f.list.node_details.control.tasks.forEach(t=>t.assignee={open_id:'other',name:'別人'});f.list.nodes.forEach(n=>n.owners=[{open_id:'other',name:'別人'}]);}});
 await act(async()=>{const menu=document.querySelector('.pf-attention-menu');menu.open=true;menu.dispatchEvent(new Event('toggle'));await tick()});assert.equal(document.querySelector('.pf-attention').textContent,'');
});
await check('round2 attention includes actual pending task, approval and owned not-started work',async()=>{
 await mount({configure(base,f){f.list.nodes.forEach(n=>n.owners=[]);f.list.nodes.find(n=>n.key==='mapping').derived_status='待審核';f.list.nodes.find(n=>n.key==='report').owners=[{open_id:'ou_anna',name:'林安娜'}];}});
 await act(async()=>{const menu=document.querySelector('.pf-attention-menu');menu.open=true;menu.dispatchEvent(new Event('toggle'));await tick()});assert.deepEqual([...document.querySelectorAll('.pf-attention button')].map(b=>b.textContent),['控制 · 待認領','圖資 · 待審核','報告 · 待處理']);
});
await check('removed node background and selected panel do not repeat stepper facts',async()=>{
 await mount({node:'control'});assert.equal(secondary('節點說明與背景'),undefined);assert.equal(document.querySelector('.pf-selected-heading'),null);assert.equal(document.querySelector('.pf-stage-context'),null);assert.equal([...document.querySelectorAll('h2,h3')].filter(h=>h.textContent==='本階段交付與確認').length,1);assert.equal(button('待處理審批（0）'),undefined);
});
await check('round2 assignment readback wins over an in-flight stale detail and avoids refetch',async()=>{
 await mount({node:'control',detailHold:true});await click(button('指派'));const drawer=document.querySelector('.task-drawer[role=dialog]');await click(drawer.querySelector('.assignee-picker button'));await act(async()=>{[...document.querySelectorAll('[role=option]')].find(o=>o.textContent.includes('林安娜')).click();await tick()});
 const pending=ui.prefetchNodeAssignmentDetail('p1','control',undefined,true);
 await click([...drawer.querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存'));globalThis.releaseDetail();await act(async()=>{await pending;await tick()});
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
await check('production seed is one task with collapsed evidence, unique item IDs and no raw marker',async()=>{
 await mount({node:'control',configure:seedConfig});
 const seed=document.querySelector('[data-assignment-task="recTask1"]');
 assert.equal(seed.querySelector('strong').textContent,'控制：依計畫數量完成');
 assert.equal(seed.querySelector('#flow-evidence').open,false);
 assert.equal(document.querySelectorAll('#flow-selected .pf-plan-facts').length,1);
 assert.equal(seed.querySelector('.pf-plan-facts dd').textContent,progress.production.control.planned.qty);
 assert.doesNotMatch(seed.textContent,/999|SOP-START/);
 assert.deepEqual([...seed.querySelectorAll('[data-item-id]')].map(row=>row.dataset.itemId),progress.production.control.items.map(item=>item.item_id));
 await click(seed.querySelector('.pf-task-open'));
 assert.doesNotMatch(document.querySelector('[role=dialog]').textContent,/SOP-START|999/);
 assert.equal(document.querySelector('select[aria-label="任務狀態"]'),null,'the editor opens only behind 編輯');
 await click(button('編輯'));
 assert.ok(document.querySelector('select[aria-label="任務狀態"]'));
 await value(document.querySelector('select[aria-label="任務狀態"]'),'已完成');await click(button('儲存任務'));
 assert.equal(calls.findLast(call=>call.method==='PATCH').body.status,'已完成');
 await click(document.querySelector('[role=dialog] [aria-label=關閉]'));
 assert.match(document.querySelector('[data-assignment-task="recTask1"]').textContent,/已完成/);
 await click(document.querySelector('[data-assignment-task=recTask1] .pf-task-open'));await click(button('編輯'));
 assert.ok(document.querySelector('.task-drawer .assignee-picker'));await click(document.querySelector('[role=dialog] [aria-label=關閉]'));
 await act(async()=>{document.querySelector('#flow-evidence a').click();await tick()});
 assert.equal(c.route.tab,'items');assert.equal(c.route.node,'control');
});
await check('production fallback uses task facts while evidence loads and keeps the plan visible when filtered',async()=>{
 await mount({node:'control',configure:seedConfig,evidenceHold:true});
 assert.match(document.querySelector('.pf-plan-facts').textContent,/999/);
 assert.doesNotMatch(document.querySelector('#flow-selected').textContent,/SOP-START/);
 await act(async()=>{globalThis.releaseEvidence();await tick()});
 assert.doesNotMatch(document.querySelector('.pf-plan-facts').textContent,/999/);
 await act(async()=>c.go({...c.route,task_filters:'unassigned'}));assert.ok(document.querySelector('.pf-filters'));assert.equal(document.querySelectorAll('.pf-task-open').length,1);
 assert.equal(document.querySelectorAll('#flow-selected .pf-plan-facts').length,1);
 assert.equal(document.querySelector('#flow-evidence').open,false);
});
await check('completed node reopen stays secondary and preserves the reason form',async()=>{
 await mount({node:'control',configure(base,f){f.list.nodes.find(n=>n.key==='control').derived_status='已完成';f.list.can.control={claim:false,assign:false,complete:false,approve:false,reject:true,create_task:false}}});
 await more();assert.equal(button('取消完成').classList.contains('primary'),false);
 assert.equal(document.querySelector('.pf-next-line'),null);
 await click(button('取消完成'));assert.match(document.querySelector('.ne-form').textContent,/取消完成/);
});
await check('legacy direct completion stays enabled when ordinary SOP writes are policy-blocked',async()=>{
 await mount({tab:'flow',node:'control',configure(base,f){f.list.writes_enabled=false;f.list.writes_disabled_reason='舊案維持原流程';f.list.can.control={legacy_complete:true};}});
 await more();assert.equal(button('直接標記完成').disabled,false);
 assert.equal(document.querySelector('.pf-node-actions button.primary'),null);
 await click(button('直接標記完成'));
 assert.ok(document.querySelector('.assignment-edit textarea'));
});
await check('legacy overflow is secondary, closes on select, explains role blocks, and hides when empty',async()=>{
 await mount({enabled:false,node:'node_control'});assert.equal(document.querySelectorAll('.nw-actions>.button.primary').length,1);await more();assert.equal(document.querySelectorAll('.pf-more .primary').length,0);const link=document.querySelector('.pf-more a[href*=people]');assert.ok(link);assert.equal(link.getAttribute('aria-disabled'),null);assert.equal(document.querySelector('[role=dialog]'),null);
 await mount({enabled:false,node:'node_control',role:'viewer',configure(base){base.project.pm_id='someone-else';base.project.supervisor_id='someone-else';base.project.nodes[4].owner_id='other'}});await more();const assign=document.querySelector('.pf-more a[href*=people]'),complete=button('完成節點');assert.equal(assign.getAttribute('aria-disabled'),'true');assert.equal(complete.disabled,false);assert.match(document.getElementById(assign.getAttribute('aria-describedby')).textContent,/專案經理或主管/);assert.equal(complete.getAttribute('aria-describedby'),null);
 await mount({enabled:false,node:'node_pricing',role:'viewer',configure(base){base.project.pm_id='someone-else';base.project.supervisor_id='someone-else'}});assert.equal(document.querySelector('.pf-more'),null);
});
await check('common blockers appear once while unique task blockers stay in their row',async()=>{
 const configure=base=>{base.project.nodes[4].status='in_progress';base.project.nodes[4].tasks=[{id:'a',title:'甲工作',status:'in_progress',owner_id:'ou_anna',execution_blockers:['行政公務證明尚未齊備','甲工作待核對']},{id:'b',title:'乙工作',status:'pending',owner_id:'ou_anna',execution_blockers:['行政公務證明尚未齊備']}];};
 for(const tab of ['overview','flow']){await mount({enabled:false,tab,node:'node_control',configure});const text=document.querySelector('.project-detail').textContent;assert.equal(text.split('行政公務證明尚未齊備').length-1,1);assert.match(document.querySelector('[data-assignment-task=a]').textContent,/甲工作待核對/);}
 await mount({enabled:false,tab:'overview',node:'node_control',configure(base){base.project.status='paused'}});assert.equal(document.querySelector('.project-overview').textContent.split('案件暫停中，等待林安娜處理。').length-1,1);
});
await check('overflow keyboard Escape and modal cancellation return focus to the live summary',async()=>{
 await mount({enabled:false,node:'node_control'});const add=button('新增任務');add.focus();await click(add);assert.ok(document.querySelector('[role=dialog]'));await act(async()=>{document.querySelector('[role=dialog]').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick()});assert.equal(document.activeElement,add,'autofocus modal restores its opener');
 await mount({node:'control'});await more();const remoteSummary=document.querySelector('.pf-more>summary');assert.ok(document.querySelector('.pf-more a[href*=people]'));assert.equal(button('指派負責人'),undefined);
 await more();button('新增任務').focus();await click(button('新增任務'));await act(async()=>{document.querySelector('.ne-form').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick()});assert.equal(document.querySelector('.ne-form'),null);assert.equal(document.activeElement,remoteSummary);
});
await check('empty blocked stages explain the disabled action once inside the empty state',async()=>{
 for(const tab of ['overview','flow'])for(const system of ['meegle','pending','workbench']){
  await mount({enabled:false,tab,node:'node_control',configure(base){base.workspace.environment='staging';base.project.execution_allowed=false;base.project.execution_system=system;base.project.execution_readonly_reason='測試：本案暫不可執行。';base.project.nodes[4].tasks=[];}});
  const empty=document.querySelector('#flow-tasks .pf-empty');assert.ok(empty.querySelector('button:disabled'));assert.match(empty.textContent,/測試：本案暫不可執行/);assert.equal(document.querySelectorAll('#flow-tasks>.st-note').length,0);assert.equal(document.querySelector('.project-detail').textContent.split('測試：本案暫不可執行。').length-1,1);
 }
});
await check('populated legacy flow does not repeat the disabled primary execution reason in a banner',async()=>{
 for(const system of ['meegle','pending']){
  await mount({enabled:false,node:'node_control',configure(base){base.workspace.environment='staging';base.project.execution_allowed=false;base.project.execution_system=system;base.project.execution_readonly_reason='測試執行限制';base.project.nodes[4].tasks=[{id:'a',title:'甲',status:'pending',owner_id:'ou_anna',comments:[]}];}});
  assert.equal(document.querySelector('.project-detail').textContent.split('測試執行限制').length-1,1);assert.equal(document.querySelector('#flow-tasks>.st-note'),null);
 }
});
await check('sidebar executors include current and started stages only, with whole-name elements',async()=>{
 await mount({enabled:false,tab:'overview',node:'node_control',configure(base){base.workspace.users.push({id:'current',name:'目前執行者'},{id:'past',name:'已啟動執行者'},{id:'future',name:'未啟動執行者'});for(const [index,id,status] of [[3,'past','completed'],[4,'current','in_progress'],[5,'future','pending']])base.project.nodes[index].tasks=[{id,owner_id:id,title:id,status,comments:[]}];}});
 assert.deepEqual([...document.querySelectorAll('.po-executors>span')].map(e=>e.textContent),['已啟動執行者','目前執行者']);
});
await check('local SOP node forms return focus to the overflow summary on Escape and cancel',async()=>{
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
 const actions={assign:{visible:true,enabled:true,disabledReason:''},complete:{visible:false},reject:{visible:true,enabled:true,disabledReason:''}};
 for(const id of ['claim','create_task','approve','legacy_complete'])actions[id]={visible:false};
 const props={workbench:{local:{key:'control',revision:1,ownerId:'ou_anna'},actions},sop:{assignees:[{id:'ou_anna',name:'林安娜'}],current:()=>true},projectId:'p1'};
 await act(async()=>{root.render(React.createElement(ui.LocalNodeActions,props));await tick()});await more();const summary=document.querySelector('.pf-more>summary');button('指派負責人').focus();await click(button('指派負責人'));await click(button('取消'));assert.equal(document.activeElement,summary);
 await more();button('退回節點').focus();await click(button('退回節點'));await act(async()=>{document.querySelector('.nw-local-form').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick()});assert.equal(document.querySelector('.nw-local-form'),null);assert.equal(document.activeElement,summary);
});
await check('flow consolidates claim and assign into one permission-aware people link',async()=>{
 await mount({node:'control',configure(base,f){f.list.can.control.claim=true;f.list.can.control.assign=true}});await more();
 assert.equal(document.querySelectorAll('.pf-node-actions a[href*=people]').length,1);assert.equal(button('認領節點'),undefined);assert.equal(button('指派負責人'),undefined);
 await mount({node:'control',configure(base,f){f.list.writes_enabled=false;f.list.writes_disabled_reason='人員來源核對中'}});await more();
 const link=document.querySelector('.pf-node-actions a[href*=people]');assert.equal(link.getAttribute('aria-disabled'),'true');assert.match(document.getElementById(link.getAttribute('aria-describedby')).textContent,/人員來源核對中/);
});
await check('populated paused overview and flow retain one causal pause reason',async()=>{
 for(const tab of ['overview','flow']){
  await mount({enabled:false,tab,node:'node_control',configure(base){base.project.status='paused';base.project.nodes[4].tasks=[{id:'a',title:'暫停工作',status:'pending',owner_id:'ou_anna'}]}});
  assert.match(document.querySelector('.st-blocker-banner>p').textContent,/案件暫停中/);
  assert.equal(document.querySelector('.project-detail').textContent.split('案件暫停中，等待林安娜處理。').length-1,1);
 }
});
await check('shared blockers disclose each secondary cause once',async()=>{
 for(const tab of ['overview','flow'])for(const cause of ['來源案件狀態待核對；未確認前不自動啟用工作','接案尚未轉正式案件','來源標示結案；工作台待核對，不自動重新啟用工作']){
  await mount({enabled:false,tab,node:'node_control',configure(base){base.project.nodes[4].tasks=[{id:'a',title:'受阻工作',status:'pending',owner_id:'ou_anna',execution_blockers:['案件已暫停、結案或來源待核對',cause,'尚未排定開始日期']}]}});
  const banner=document.querySelector('.st-blocker-banner');assert.equal(banner.firstElementChild.textContent,cause);assert.equal(banner.querySelector('details').open,false);assert.ok(banner.querySelector('summary svg'));assert.equal(banner.textContent.split(cause).length-1,1);assert.equal([...document.querySelectorAll('.flow-operations button.primary')].filter(b=>!b.closest('[hidden]')).length,0);
 }
});
await act(async()=>root.unmount());assert.deepEqual(failures,[]);
