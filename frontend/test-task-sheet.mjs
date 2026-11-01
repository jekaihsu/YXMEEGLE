import assert from 'node:assert/strict';
import {writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1&tab=flow&node=node_sales',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','Element','Node','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetail} from './src/ProjectDetail'; export {normalizeRoute,parseRoute,invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.task-sheet.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const tick=()=>new Promise(r=>setTimeout(r,15));
const guest={id:'ou_guest',name:'訪客',role:'member',department:'',avatar:'',capabilities:[]};
let root,c,calls;
const render=()=>root.render(React.createElement(ui.ProjectDetail,{c}));
const go=(next,replace=false)=>{const r=ui.normalizeRoute(next);const q=new URLSearchParams();Object.entries(r).forEach(([k,v])=>{if(v)q.set(k,v)});if(replace)history.replaceState(null,'',location.pathname+location.search+'#'+q.toString());else location.hash=q.toString();c={...c,route:r};render()};
window.addEventListener('hashchange',()=>{if(!root)return;c={...c,route:ui.parseRoute(location.hash)};render()});
const task=(id,patch={})=>({id,title:`任務 ${id}`,owner_id:'',status:'in_progress',required:true,start_date:null,due_date:null,original_due_date:null,started_at:null,completed_at:null,points:null,work_item_id:'',description:'',input:'',output:'',comments:[],revision:1,can_execute:true,...patch});
async function mount(id,patch,{actor,features={}}={}){
 if(root){await act(async()=>root.unmount());root=null}ui.invalidateSessionEpoch();calls=[];
 const base=projectFixture();
 const node=base.project.nodes.find(n=>n.key==='sales');node.tasks=[task(id,{owner_id:base.user.id,...patch})];
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
console.log(process.exitCode?'Task sheet checks FAILED':'Task sheet checks passed');
