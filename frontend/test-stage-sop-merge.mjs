import assert from 'node:assert/strict';
import {writeFile,unlink,readFile} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1&node=node_sales',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','Element','Node','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetail} from './src/ProjectDetail'; export {parseRoute,normalizeRoute,invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.stage-sop-merge.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const example=JSON.parse(await readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8')).sop_tasks;
const tick=()=>new Promise(r=>setTimeout(r,20));
const ME='ou_anna';
// Synthetic mixed case: 2 local-flow tasks + 10 SOP checklist tasks on 業務 (12 in total).
const sopStates=['pending','pending','in_progress','blocked','done','done','pending','pending','pending','pending'];
function sopOverview(){
 const tasks=sopStates.map((state,i)=>({...structuredClone(example.tasks[0]),id:`sop-${i}`,title:`SOP 任務 ${i+1}`,state,participants:i===2?{executor:ME}:i<5?{executor:'ou_other'}:{},due_date:null,dueDate:null,overdue:false}));
 const done=sopStates.filter(s=>s==='done').length;
 return {...structuredClone(example),tasks,case_counts:{...example.case_counts,done,total:10},node_counts:{...example.node_counts,sales:{done,total:10,unresolved:0,not_applicable:0,archived:0}},allowed_actions:{...example.allowed_actions}};
}
const localTask=(id,over)=>({id,title:`本地流程 ${id}`,owner_id:'',status:'pending',required:true,start_date:null,due_date:null,original_due_date:null,started_at:null,completed_at:null,points:null,work_item_id:'',description:'',input:'',output:'',comments:[],revision:1,...over});
let root,c;
async function mount(hash){
 if(root)await act(async()=>root.unmount());ui.invalidateSessionEpoch();location.hash=hash;await tick();
 const base=projectFixture();base.user.id=ME;
 for(const n of base.project.nodes)n.tasks=n.key==='sales'?[localTask('l1',{owner_id:ME}),localTask('l2',{owner_id:''})]:[];
 c={w:base.workspace,s:{user:{...base.user,capabilities:['sop_task_read']},mode:'demo',workspace_id:'mixed',features:{node_assignment:false}},route:ui.parseRoute(location.hash),busy:false,run:async()=>undefined,notify(){},registerDrafts(){},refresh:async()=>{},go(next){c={...c,route:ui.normalizeRoute(next)};root.render(React.createElement(ui.ProjectDetail,{c}))}};
 globalThis.fetch=async url=>url.endsWith('/sop-tasks')?new Response(JSON.stringify(sopOverview()),{status:200,headers:{'Content-Type':'application/json'}}):new Response(JSON.stringify({detail:'disabled'}),{status:404,headers:{'Content-Type':'application/json'}});
 root=createRoot(document.getElementById('root'));await act(async()=>{root.render(React.createElement(ui.ProjectDetail,{c}));await tick();await tick()});
}
const button=text=>[...document.querySelectorAll('#flow-tasks .pf-filters button')].find(b=>b.textContent.trim()===text);
const click=async el=>{assert.ok(el);await act(async()=>{el.click();await tick()})};
const ids=()=>[...document.querySelectorAll('#flow-tasks > .pf-task-list [data-assignment-task]')].map(li=>li.dataset.assignmentTask);
const count=()=>document.querySelector('.st-count').textContent;

await mount('view=project&project=p1&node=node_sales');
assert.match(count(),/符合條件 12 項 · 節點共 12 項/,'before the fix this list showed only the 2 local-flow tasks');
assert.equal(ids().length,12);assert.match(document.querySelector('#flow-selected').textContent,/任務完成數：2 \/ 12 已完成/);
assert.equal(document.querySelector('.st-note[role=status]')?.textContent.includes('不一致')??false,false,'rows and node total agree');
const statuses=[...document.querySelectorAll('#flow-tasks > .pf-task-list .st-meta > span:first-child')].map(s=>s.textContent);
assert.ok(statuses.every(s=>/^任務狀態：(待處理|進行中|已完成|受阻)$/.test(s)),'one status dictionary: '+[...new Set(statuses)].join(','));
assert.equal(statuses.filter(s=>s==='任務狀態：待處理').length,8,'local 尚未開始 and SOP 待處理 read the same');
await click(button('我的任務'));assert.deepEqual(ids().sort(),['l1','sop-2'],'my tasks come from both sources');assert.match(count(),/符合條件 2 項 · 節點共 12 項/);
await click(button('我的任務'));await click(button('未指派'));assert.equal(ids().length,1+5,'local l2 plus five SOP tasks without an executor');
await click(button('未指派'));await click(button('受阻'));assert.deepEqual(ids(),['sop-3'],'SOP blocked state is a known blocker');assert.equal(document.querySelector('.st-note')?.textContent.includes('未提供任務阻礙資訊')??false,false);
await click(button('受阻'));await click(button('待處理'));assert.equal(ids().length,10,'待處理 = everything not done: 12 minus two done');
await click(button('未指派'));assert.equal(ids().length,5,'filters combine with AND (l2 and four open SOP tasks without an executor)');assert.match(document.querySelector('.st-applied').textContent,/待處理 ＋ 未指派/);
await click(button('全部'));assert.equal(ids().length,12);
assert.ok([...document.querySelectorAll('#sop-tasks .pf-task-list')].every(list=>list.closest('details.st-sop-tools:not([open])')),'any old SOP list sits inside the folded tools, so only one list is visible');
const tools=document.querySelector('.st-sop-tools');assert.ok(tools&&!tools.open,'old SOP tools are folded');
await act(async()=>root.unmount());console.log('PASS mixed local-flow + SOP task list: 12 rows, one dictionary, filters agree with the node total');
