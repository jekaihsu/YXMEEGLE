import assert from 'node:assert/strict';
import {writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {readFileSync} from 'node:fs';
import {projectFixture} from './fixtures/node-assignments.mjs';
const progressFixture=JSON.parse(readFileSync(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1&tab=flow&node=node_sales',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','Element','Node','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetail} from './src/ProjectDetail'; export {normalizeRoute,parseRoute,invalidateSessionEpoch} from './src/api'; export {taskWorkFact,progressWorkItems} from './src/ProjectDetail'; export {seedProjectProgress} from './src/useProjectProgress';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.task-sheet.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const tick=()=>new Promise(r=>setTimeout(r,15));
const guest={id:'ou_guest',name:'訪客',role:'member',department:'',avatar:'',capabilities:[]};
let root,c,calls;
const render=()=>root.render(React.createElement(ui.ProjectDetail,{c}));
const go=(next,replace=false)=>{const r=ui.normalizeRoute(next);const q=new URLSearchParams();Object.entries(r).forEach(([k,v])=>{if(v)q.set(k,v)});if(replace)history.replaceState(null,'',location.pathname+location.search+'#'+q.toString());else location.hash=q.toString();c={...c,route:r};render()};
window.addEventListener('hashchange',()=>{if(!root)return;c={...c,route:ui.parseRoute(location.hash)};render()});
const task=(id,patch={})=>({id,title:`任務 ${id}`,owner_id:'',status:'in_progress',required:true,start_date:null,due_date:null,original_due_date:null,started_at:null,completed_at:null,points:null,work_item_id:'',description:'',input:'',output:'',comments:[],revision:1,can_execute:true,...patch});
async function mount(id,patch,{actor,features={},items,events,progress,project,approvals}={}){
 if(root){await act(async()=>root.unmount());root=null}ui.invalidateSessionEpoch();calls=[];if(progress)ui.seedProjectProgress('p1',progress);
 const base=projectFixture();Object.assign(base.project,project);if(approvals)base.workspace.approvals=approvals;
 const node=base.project.nodes.find(n=>n.key==='sales');node.tasks=[task(id,{owner_id:base.user.id,...patch})];
 if(items)base.workspace.contract_items=items;if(events)base.workspace.events=events;
 location.hash=`view=project&project=p1&tab=flow&node=${node.id}&task=${id}`;await tick();
 c={w:base.workspace,s:{user:actor||base.user,mode:'demo',workspace_id:'local-company',features:{node_assignment:false,...features}},route:ui.parseRoute(location.hash),busy:false,error:'',run:async(action,payload)=>{calls.push([action,payload]);return {}},notify(){},registerDrafts(){},refresh:async()=>{},go};
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:'disabled'}),{status:404,headers:{'Content-Type':'application/json'}});
 root=createRoot(document.getElementById('root'));await act(async()=>{render();await tick()});
}
const drawer=()=>document.querySelector('.task-drawer[data-kind="legacy"]');
const footer=()=>drawer().querySelector('.task-drawer-footer');
const button=(text,scope=drawer())=>[...scope.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
const click=async element=>{assert.ok(element,'requested control exists');await act(async()=>{element.click();await tick()})};
const type=async(element,value)=>{await act(async()=>{const proto=element.tagName==='TEXTAREA'?dom.window.HTMLTextAreaElement.prototype:dom.window.HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(element,value);element.dispatchEvent(new dom.window.Event('input',{bubbles:true}));await tick()})};
const tab=async name=>click([...drawer().querySelectorAll('.inspector-tabs button')].find(b=>b.textContent===name));
const checks=[];const check=async(name,fn)=>{try{await fn();console.log('PASS',name)}catch(e){console.log('FAIL',name,e);process.exitCode=1}};

await check('footer exists only on the details tab',async()=>{
 await mount('t1');
 assert.ok(footer());
 await tab('評論');assert.equal(drawer().querySelector('.task-drawer-footer'),null);
 await tab('歷程');assert.equal(drawer().querySelector('.task-drawer-footer'),null);
 await tab('任務詳情');assert.ok(footer());
});
await check('an in-progress actor gets one primary that waits for a result, with return in the overflow',async()=>{
 await mount('t1');
 const primary=[...footer().querySelectorAll('.task-drawer-primary button')];
 assert.deepEqual(primary.map(b=>[b.textContent,b.disabled]),[['完成任務',true]]);
 assert.equal(primary[0].getAttribute('aria-describedby'),'task-output-hint');
 assert.equal(primary[0].getAttribute('title'),null,'the reason is inline text, not a title');
 assert.equal(drawer().querySelector('#task-output-hint').textContent,'完成任務前請先填寫成果。');
 assert.equal(footer().querySelector('#task-output-hint'),null);
 assert.deepEqual([...footer().querySelectorAll('button,summary')].map(b=>b.textContent||b.getAttribute('aria-label')),['更多操作','完成任務'],'overflow first, then the single primary');
 assert.doesNotMatch(footer().textContent,/展延未開放|僅負責人或代理人可操作|已完成/);
 await click(footer().querySelector('.task-drawer-more>summary'));
 assert.deepEqual([...document.querySelectorAll('.task-drawer-more-list button')].map(b=>b.textContent),['退回']);
 await click(button('退回',document.querySelector('.task-drawer-more-list')));
 assert.ok(drawer().querySelector('.return-form'),'退回 opens the return form');
 assert.equal(drawer().querySelector('.task-drawer-footer'),null,'the footer steps aside while the return form is open');
 await click(button('取消'));assert.ok(footer());
});
await check('writing a result enables completion and sends it',async()=>{
 await mount('t1');
 await type(drawer().querySelector('textarea[aria-label="成果與交接說明"]'),'已交付成果');
 assert.equal(drawer().querySelector('#task-output-hint'),null);
 const primary=footer().querySelector('.task-drawer-primary button');assert.equal(primary.disabled,false);
 await click(primary);
 assert.deepEqual(calls.at(-1),['task_complete',{output:'已交付成果'}]);
});
await check('a pending task offers only 開始作業',async()=>{
 await mount('t1',{status:'pending'});
 assert.deepEqual([...footer().querySelectorAll('.task-drawer-primary button')].map(b=>[b.textContent,b.disabled]),[['開始作業',false]]);
 assert.equal(drawer().querySelector('textarea[aria-label="成果與交接說明"]'),null,'no result box before the work starts');
 await click(button('開始作業'));assert.equal(calls.at(-1)[0],'task_start');
});
await check('extension appears in the overflow only when the feature is on',async()=>{
 await mount('t1',{},{features:{change_extension:true}});
 await click(footer().querySelector('.task-drawer-more>summary'));
 assert.deepEqual([...document.querySelectorAll('.task-drawer-more-list button')].map(b=>b.textContent),['退回','展延']);
});
await check('a completed task has no 已完成 button and shows its result as plain text',async()=>{
 await mount('t1',{status:'completed',output:'成果已歸檔'});
 assert.equal(button('已完成'),undefined);
 assert.equal(drawer().querySelector('textarea'),null);
 assert.equal(drawer().querySelector('.task-drawer-primary'),null);
 assert.match(drawer().querySelector('.task-drawer-body').textContent,/成果與交接成果已歸檔/);
 assert.equal(button('編輯'),undefined,'finished tasks are not editable');
});
await check('a viewer who cannot act sees facts and result but no footer, form or notes',async()=>{
 await mount('t1',{owner_id:'ou_someone',can_execute:false,output:'同事的成果'},{actor:guest});
 assert.equal(drawer().querySelector('.task-drawer-footer'),null);
 assert.equal(drawer().querySelector('textarea'),null);
 assert.equal(drawer().querySelector('.nw-task-editor'),null);
 assert.equal(button('編輯'),undefined);
 assert.match(drawer().querySelector('.task-drawer-body').textContent,/成果與交接同事的成果/);
 assert.doesNotMatch(drawer().textContent,/僅負責人或代理人可操作|展延未開放/);
 await mount('t1',{owner_id:'ou_someone',can_execute:false,output:''},{actor:guest});
 assert.doesNotMatch(drawer().querySelector('.task-drawer-body').textContent,/成果與交接/,'an empty result is omitted for non-actors');
});
await check('the editor mounts only behind 編輯 and replaces the read-only facts',async()=>{
 await mount('t1',{description:'依確認單施作',due_date:'2026-10-30',points:2});
 assert.equal(drawer().querySelector('.nw-task-editor'),null);
 assert.deepEqual([...drawer().querySelectorAll('.task-drawer-facts dt')].map(d=>d.textContent),['負責人','期限','營業額點數']);
 assert.equal(drawer().querySelectorAll('.task-drawer-body h3').length>=2,true);
 assert.equal([...drawer().querySelectorAll('h3')].filter(h=>h.textContent==='任務說明').length,1,'the description is shown once');
 await click(button('編輯'));
 assert.ok(drawer().querySelector('.nw-task-editor'));
 assert.equal(drawer().querySelector('.task-drawer-facts'),null,'the facts are replaced by the form');
 assert.equal(drawer().querySelector('.task-drawer-footer'),null,'one footer: none while editing');
 assert.deepEqual([...drawer().querySelectorAll('.nw-task-editor label')].map(l=>l.firstChild.textContent),['任務名稱','負責人','開始日期','營業額點數','備註']);
 await click(button('取消'));assert.equal(drawer().querySelector('.nw-task-editor'),null);assert.ok(footer());
});
await check('known facts only: schedule range, work item and points appear when present',async()=>{
 await mount('t1',{start_date:'2026-10-01',due_date:'2026-10-30',points:3});
 const dts=[...drawer().querySelectorAll('.task-drawer-facts dt')].map(d=>d.textContent);
 assert.deepEqual(dts,['負責人','開始 → 期限','營業額點數']);
 await mount('t1');
 assert.deepEqual([...drawer().querySelectorAll('.task-drawer-facts dt')].map(d=>d.textContent),['負責人']);
});
const facts=()=>Object.fromEntries([...drawer().querySelectorAll('.task-drawer-facts > div')].map(d=>[d.querySelector('dt').textContent,d.querySelector('dd').textContent]));
await check('工項 fact: known titles; review only for wholly dangling contract links',async()=>{
 await mount('t1',{work_item_id:'p1-survey'});
 assert.equal(facts()['工項'],undefined,'an unresolved work_item_id alone is omitted');
 await mount('t1',{contract_item_ids:['ci-gone']});
 assert.equal(facts()['工項'],'來源工項待核對','an unresolved contract-item link still shows');
 await mount('t1',{contract_item_ids:['ci-1','ci-gone']},{items:[{id:'ci-1',title:'控制點測量'}]});
 assert.equal(facts()['工項'],'控制點測量','a partly resolved contract link shows only the known title');
 await mount('t1',{work_item_id:'wi-9'},{items:[{id:'wi-9',title:'水準測量'}]});
 assert.equal(facts()['工項'],'水準測量','a work item that resolves shows its real title');
 await mount('t1',{work_item_id:'p1-survey'},{items:[{id:'other',title:'不相干工項'}]});
 assert.equal(facts()['工項'],undefined,'the title is never guessed from an unrelated item');
 await mount('t1');
 assert.equal(facts()['工項'],undefined,'truly unlinked: omitted');
});
await check('工項 fact resolves against the loaded progress work items and stays quiet on finished tasks',async()=>{
 const progress=structuredClone(progressFixture);progress.production.field.items[0]={...progress.production.field.items[0],item_id:'p1-survey',name:'現況測量'};
 await mount('t1',{work_item_id:'p1-survey'},{progress});
 assert.equal(facts()['工項'],'現況測量','a work_item_id found in the progress work items shows its real title');
 await mount('t1',{work_item_id:'p1-survey',status:'completed'},{progress});
 assert.equal(facts()['工項'],'現況測量','a resolvable id still shows its title on a finished task');
 await mount('t1',{work_item_id:'p1-survey',status:'completed'});
 assert.equal(facts()['工項'],undefined,'completed task whose work item cannot be resolved: no 來源工項待核對 row');
 await mount('t1',{work_item_id:'p1-survey',status:'superseded'});
 assert.equal(facts()['工項'],undefined,'cancelled task: no 來源工項待核對 row');
 await mount('t1',{work_item_id:'p1-survey'});
 assert.equal(facts()['工項'],undefined,'an open work-item-only task also stays quiet');
 assert.deepEqual(ui.progressWorkItems({production:{field:{items:[{item_id:'a',name:null,code:'C1'},{item_id:'b',name:null,code:null}]}}}),[{id:'a',title:'C1'}]);
 assert.equal(ui.taskWorkFact({contract_item_ids:['x','y']},[{id:'x',title:'控制點'}],[]),'控制點','partially resolved links show known titles only');
});
await check('contract links review regardless of task state, with resolution in either loaded list',async()=>{
 for(const status of ['in_progress','completed','superseded']){
  await mount('t1',{status,contract_item_ids:['missing']});
  assert.equal(facts()['工項'],'來源工項待核對');
 }
 assert.equal(ui.taskWorkFact({contract_item_ids:['missing'],work_item_id:'known'},[],[{id:'known',title:'已載入工項'}]),'已載入工項');
 assert.equal(ui.taskWorkFact({contract_item_ids:['known','known','missing']},[],[{id:'known',title:'已載入工項'}]),'已載入工項');
 assert.equal(ui.taskWorkFact({contract_item_ids:[],work_item_id:'missing'},[]),'');
});
await check('pause wording follows loaded design-change evidence, case pause, then generic fallback',async()=>{
 const callout=()=>drawer().querySelector('.info-callout')?.textContent;
 const event={id:'pause',project_id:'p1',node_id:projectFixture().project.nodes.find(n=>n.key==='sales').id,task_id:'t1',actor_id:'system',action:'task_pause_for_change',message:'設計調整',created_at:'2026-10-01'};
 await mount('t1',{status:'paused'},{events:[event]});assert.match(callout(),/^設計變更暫停中/);
 const approval={id:'change',project_id:'p1',type:'change',task_ids:['t1'],reason:'設計調整',frozen:true,title:'變更審批'};
 await mount('t1',{status:'paused'},{approvals:[approval],events:[]});assert.match(callout(),/^設計變更暫停中/);
 assert.ok(button('查看「變更審批」'),'the related approval remains reachable');
 await mount('t1',{status:'paused'},{events:[],approvals:[{...approval,frozen:false}]});assert.match(callout(),/^任務暫停中/);assert.doesNotMatch(callout(),/設計變更暫停中/);
 await mount('t1',{status:'paused'},{events:[],approvals:[],project:{execution_status:'paused'}});assert.match(callout(),/^案件暫停中，任務目前無法執行/);
 await mount('t1',{status:'in_progress'},{events:[],approvals:[approval],project:{execution_status:'paused'}});assert.match(callout(),/^案件暫停中/,'a related approval alone does not make an active task change-paused');
 await mount('t1',{status:'paused'},{events:[event],project:{execution_status:'paused'}});assert.match(callout(),/^設計變更暫停中/,'positive task evidence takes priority');
 for(const wrong of [{node_id:'other'},{project_id:'other'},{task_id:'other'},{message:''},{action:'task_start'}]){
  await mount('t1',{status:'paused'},{events:[{...event,...wrong}],approvals:[]});assert.match(callout(),/^任務暫停中/,'foreign or empty evidence must not invent a cause');
 }
 await mount('t1',{status:'in_progress'},{events:[event],approvals:[approval]});assert.equal(callout(),undefined);
});
await check('keyboard: 編輯 moves focus to the first field; cancel and save return it to 編輯',async()=>{
 await mount('t1',{description:'依確認單施作'});
 await click(button('編輯'));
 assert.ok(document.activeElement===drawer().querySelector('.nw-task-editor [aria-label="任務名稱"]'),'first editable field has focus');
 await click(button('取消'));
 assert.ok(document.activeElement===button('編輯'),'cancel restores focus to 編輯');
 await click(button('編輯'));
 await type(drawer().querySelector('[aria-label="任務名稱"]'),'改過的任務名稱');
 await click(button('儲存任務'));
 assert.equal(calls.at(-1)[0],'task_update');
 assert.equal(drawer().querySelector('.nw-task-editor'),null);
 assert.ok(document.activeElement===button('編輯'),'save restores focus to 編輯');
});
await check('展延 keeps its earlier rule: any viewer sees it in the overflow when the feature is on, never when off',async()=>{
 await mount('t1',{owner_id:'ou_someone',can_execute:false},{actor:guest,features:{change_extension:true}});
 assert.ok(footer(),'a viewer who is neither actor nor assigner still gets the overflow');
 assert.equal(footer().querySelector('.task-drawer-primary'),null,'but no primary');
 await click(footer().querySelector('.task-drawer-more>summary'));
 assert.deepEqual([...document.querySelectorAll('.task-drawer-more-list button')].map(b=>b.textContent),['展延']);
 await mount('t1',{owner_id:'ou_someone',can_execute:false},{actor:guest});
 assert.equal(drawer().querySelector('.task-drawer-footer'),null,'feature off: no footer at all');
});
await check('歷程 carries 已依排程啟用 whether or not the activation event is in the feed',async()=>{
 const patch={status:'in_progress',activation_source:'schedule',activated_at:'2026-10-01T09:00:00+08:00'};
 await mount('t1',patch);await tab('歷程');
 assert.match(drawer().querySelector('.event-list').textContent,/已依排程啟用 · 尚未記錄實際開始/);
 await mount('t1',patch,{events:[{id:'e1',project_id:'p1',task_id:'t1',actor_id:'system',action:'task_activate',message:'排程日已到且前置條件齊備；未記錄實際作業開始',created_at:'2026-10-01T01:00:00Z'}]});await tab('歷程');
 const text=drawer().querySelector('.event-list').textContent;
 assert.match(text,/已依排程啟用 · 排程日已到/);assert.equal(text.split('已依排程啟用').length-1,1,'shown once, not duplicated');
 await mount('t1');await tab('歷程');
 assert.doesNotMatch(drawer().querySelector('.event-list').textContent,/已依排程啟用/);
});
console.log(process.exitCode?'Task sheet checks FAILED':'Task sheet checks passed');
