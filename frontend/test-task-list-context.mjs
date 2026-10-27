import assert from 'node:assert/strict';
import {writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1&tab=tasks&node=node_sales',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','Element','Node','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetail} from './src/ProjectDetail'; export {normalizeRoute,parseRoute,invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.task-list-context.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const tick=()=>new Promise(r=>setTimeout(r,15));
const perNode={sales:2,pm:3,confirmation:3,field:3,control:3,mapping:2,report:2,pricing:2,settlement:1};
const overdueIds=new Set(['sales-1','pm-1','field-1','control-1','report-1']);
function localProject(){
 const base=projectFixture();
 for(const node of base.project.nodes)node.tasks=Array.from({length:perNode[node.key]},(_,i)=>{const id=`${node.key}-${i}`;return {id,title:`${node.name}任務 ${i+1}`,owner_id:base.user.id,status:'in_progress',required:true,start_date:null,due_date:overdueIds.has(id)?'2026-10-01':'2026-10-30',original_due_date:null,started_at:null,completed_at:null,points:null,work_item_id:'',description:'',input:'',output:'',comments:[],revision:1,can_execute:true}});
 return base;
}
let root,c;
const render=()=>root.render(React.createElement(ui.ProjectDetail,{c}));
const go=(next,replace=false)=>{const r=ui.normalizeRoute(next);const q=new URLSearchParams();Object.entries(r).forEach(([k,v])=>{if(v)q.set(k,v)});if(replace)history.replaceState(null,'',location.pathname+location.search+'#'+q.toString());else location.hash=q.toString();c={...c,route:r};render()};
window.addEventListener('hashchange',()=>{if(!root)return;c={...c,route:ui.parseRoute(location.hash)};render()});
async function mount(hash){
 if(root){await act(async()=>root.unmount());root=null}ui.invalidateSessionEpoch();
 location.hash=hash;await tick();
 const base=localProject();
 c={w:base.workspace,s:{user:base.user,mode:'demo',workspace_id:'local-company',features:{node_assignment:false}},route:ui.parseRoute(location.hash),busy:false,error:'',run:async()=>undefined,notify(){},registerDrafts(){},refresh:async()=>{},go};
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:'disabled'}),{status:404,headers:{'Content-Type':'application/json'}});
 root=createRoot(document.getElementById('root'));await act(async()=>{render();await tick()});
}
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
const pressed=text=>button(text).getAttribute('aria-pressed');
const rows=()=>document.querySelectorAll('.pf-task-open').length;
const click=async element=>{assert.ok(element,'requested control exists');await act(async()=>{element.click();await tick()})};
const back=async()=>{await act(async()=>{history.back();await tick();await tick()})};

await mount('view=project&project=p1&tab=tasks&node=node_sales');
assert.equal(pressed('全部任務'),'true');assert.equal(rows(),21);
await click(button('逾期'));assert.equal(rows(),5);
await click(document.querySelector('.pf-task-open'));
assert.ok(document.querySelector('.task-inspector'),'local drawer opens');assert.equal(rows(),5);
await click(document.querySelector('[aria-label="關閉任務"]'));
assert.equal(document.querySelector('.task-inspector'),null);
assert.equal(rows(),5,'closing the drawer keeps the five overdue results');
assert.equal(pressed('全部任務'),'true');assert.equal(pressed('逾期'),'true');assert.equal(c.route.section,'all-tasks');
await click(button('逾期'));assert.equal(rows(),21);
await click(button('此節點'));assert.equal(rows(),2,'scope toggle returns to the node');assert.equal(pressed('此節點'),'true');assert.equal(c.route.all_tasks,undefined);
await click(button('全部任務'));assert.equal(rows(),21);


await mount('view=project&project=p1&tab=tasks&node=node_sales');
await click(button('逾期'));assert.equal(rows(),5);assert.match(location.hash,/task_filters=overdue/);
await click(document.querySelector('.pf-task-open'));const opened=c.route.task;
await click([...document.querySelectorAll('.task-inspector button')].find(b=>b.textContent.trim()==='查看節點檔案'));
assert.equal(c.route.tab,'files');assert.equal(document.querySelector('.task-inspector'),null);assert.equal(rows(),0);
await back();
assert.equal(c.route.task,opened);assert.ok(document.querySelector('.task-inspector'),'history restores the drawer');
assert.equal(rows(),5,'overdue filter survives Files and Back');assert.equal(pressed('逾期'),'true');assert.equal(pressed('全部任務'),'true');
await act(async()=>{document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick()});
assert.equal(document.querySelector('.task-inspector'),null);assert.equal(rows(),5);
const row=[...document.querySelectorAll('[data-assignment-task]')].find(li=>li.dataset.assignmentTask===opened).querySelector('.pf-task-open');
assert.equal(document.activeElement,row,'focus returns to the reopened row');

await act(async()=>root.unmount());console.log('Task list context checks passed');
