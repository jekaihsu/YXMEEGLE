import assert from 'node:assert/strict';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {response as dispatchExample} from './qa/dispatch-api-examples.mjs';
import {projectFixture,embeddedAssignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){globalThis.lastScroll=this.id};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetail} from './src/ProjectDetail'; export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.project-flow-ui.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));progress.project_id='p1';
let root,c,fixture,calls,hold,evidenceStatus=200,nodeStatus=200,detailStatus=200,mutationStatus=200;
const tick=()=>new Promise(r=>setTimeout(r,15));
async function mount({tab='flow',node,task,enabled=true,role='manager',dispatch=false,assign=true,evidenceHold=false,embedded=true,parentProject='p1'}={}){
 if(root)await act(async()=>root.unmount());ui.invalidateSessionEpoch();
 const base=projectFixture();fixture=embeddedAssignmentFixture();
 for(const n of fixture.list.nodes){n.departments=['控制'];fixture.list.node_details[n.key].assignable_people.forEach(p=>p.departments=['控制']);}
 fixture.list.node_details.control.tasks.push({...fixture.detail.tasks[0],id:'recUnassigned',title:'尚待指派的核對任務',assignee:null,deadline:'2026-10-01'});
 if(!assign){fixture.list.can.control.assign=false;fixture.list.node_details.control.tasks.forEach(t=>t.can.assign=false)}
 const detailPayloads=fixture.list.node_details;if(!embedded)delete fixture.list.node_details;globalThis.detailPayloads=detailPayloads;
 calls=[];let releaseEvidence;hold=evidenceHold?new Promise(r=>releaseEvidence=r):null;globalThis.releaseEvidence=releaseEvidence;
 c={w:base.workspace,s:{user:{...base.user,role},mode:'lark',workspace_id:'flow-company',features:{node_assignment:enabled,dispatch_write:dispatch}},route:{view:'project',project:'p1',tab,node,task},busy:false,run:async()=>true,notify(){},registerDrafts(){},refresh:async()=>{},go(route){c={...c,route};root.render(React.createElement(ui.ProjectDetail,{c}))}};
 globalThis.fetch=async(url,init={})=>{calls.push({url,method:init.method||'GET',body:init.body?JSON.parse(init.body):null});
  if(url.endsWith('/progress')){if(hold)await hold;return response(evidenceStatus===200?progress:{detail:'合成證據讀取失敗'},evidenceStatus)}
  if(url.endsWith('/node-assignments'))return response(nodeStatus===200?fixture.list:{detail:'合成節點來源失敗'},nodeStatus);
  if(url.includes('/node-assignments/nodes/')){
   const key=url.split('/nodes/')[1].split('/')[0];const node=fixture.list.nodes.find(n=>n.key===key);if((init.method||'GET')==='GET'&&detailStatus!==200)return response({detail:'合成任務明細失敗'},detailStatus);
   if(init.method==='PATCH'){
    if(mutationStatus!==200)return response({detail:'沒有指派權限',code:'forbidden'},mutationStatus);
    const t=fixture.list.node_details[key].tasks.find(t=>t.id===url.split('/').at(-1));const patch=JSON.parse(init.body);t.assignee={open_id:patch.assignee_open_id,name:'林安娜'};
   }
   return response({...fixture.list,node,can:fixture.list.can[key],...detailPayloads[key]});
  }
  if(url.includes('/dispatch/work'))return response({source:{quality:{states:['complete']}},rows:[{task_id:'recObligation',title:'控制義務',project_id:parentProject,kind:'obligation',phase:'正式',status:'待處理',department:'控制',case:{ref:'recCase',code:'C001',name:'合成確認單'},node_position:'控制',source:'v4_task'}]});
  if(url.endsWith('/dispatch/options'))return response({people:[{person_ref:'ou_anna',open_id:'ou_anna',name:'林安娜',active:true,has_lark_account:true}],instruments:[],vehicles:[],cases:[{ref:'recCase',code:'C001',name:'合成確認單'}],departments:['控制'],seats:[],joins:{}});
  if(url.endsWith('/dispatch/previews')){const data=dispatchExample('decision: PM final accepts');data.proposal=JSON.parse(init.body);data.crew=data.proposal.crew.map(person_ref=>({person_ref,name:'林安娜',feasibility:'feasible'}));data.resources=[];data.expires_at='2099-01-01T00:00:00Z';return response(data)}
  if(url.endsWith('/dispatch/commits')){fixture.list.node_details.control.tasks.push({...fixture.detail.tasks[0],id:'recPublished',record_id:'recPublished',title:'已發布的新排班'});return response({command:{command_id:JSON.parse(init.body).command_id,state:'committed',revision:1,task_record_id:'recPublished'}})}
  if(url.endsWith('/sop-tasks'))return globalThis.sopOverview?response(globalThis.sopOverview):response({code:'sop_import_forbidden'},403);
  return response({detail:'disabled'},404);
 };
 root=createRoot(document.getElementById('root'));await act(async()=>{root.render(React.createElement(ui.ProjectDetail,{c}));await tick()});
}
function response(body,status=200){return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}})}
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
const click=async element=>{assert.ok(element,'requested control exists');assert.equal(element.disabled,false,element.textContent);await act(async()=>{element.click();await tick()})};
const value=async(el,v)=>act(async()=>{Object.getOwnPropertyDescriptor(el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(el,v);el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));await tick()});
await mount({node:'control'});
assert.deepEqual([...document.querySelectorAll('.pds-tabs button')].map(b=>b.textContent),['總覽','流程與任務','工項與進度','排程與人員','文件與交付','案件資料']);
assert.equal(document.querySelectorAll('.pf-node').length,9);assert.equal(document.querySelectorAll('[aria-label="流程任務列表"]').length,1);
assert.match(document.querySelector('#flow-evidence').textContent,/實際完成量未知/);
assert.equal(calls.filter(r=>r.url.endsWith('/progress')).length,1);assert.equal(calls.filter(r=>r.url.endsWith('/node-assignments')).length,1);assert.equal(calls.filter(r=>r.url.includes('/nodes/')).length,0);
assert.ok([...document.querySelectorAll('.pf-secondary')].every(d=>!d.open));
await act(async()=>document.querySelector('.pf-node[aria-current]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})));
assert.equal(c.route.node,'mapping');assert.equal(document.activeElement.getAttribute('aria-current'),'step');
await mount({tab:'tasks',node:'control'});assert.equal(button('全部任務').getAttribute('aria-pressed'),'true');
await click(button('未指派'));assert.equal(document.querySelectorAll('.pf-task-open').length,1);assert.match(document.querySelector('.pf-task-open').textContent,/尚待指派/);
await click(button('逾期'));assert.equal(document.querySelectorAll('.pf-task-open').length,1);
await click(button('指派'));assert.equal(document.querySelector('select[aria-label="任務負責人"]').options.length,3);
mutationStatus=403;await value(document.querySelector('select[aria-label="任務負責人"]'),'ou_anna');await click(button('儲存指派'));
assert.match(document.querySelector('.pf-task-picker').textContent,/沒有|權限/);assert.equal(document.querySelector('select[aria-label="任務負責人"]').value,'ou_anna');
mutationStatus=200;await click(button('儲存指派'));const patch=calls.findLast(r=>r.method==='PATCH');assert.deepEqual(Object.keys(patch.body).sort(),['assignee_open_id','expected_revision','request_id']);assert.equal(patch.body.assignee_open_id,'ou_anna');
await mount({node:'control'});await click(button('新增任務'));assert.match(document.querySelector('.ne-form').textContent,/新增節點任務/);
await click(button('建立任務'));assert.match(document.querySelector('.ne-form').textContent,/請填寫任務名稱/);
await mount({node:'control',dispatch:true});await click(button('排班'));assert.match(document.querySelector('[role=dialog]').textContent,/新增排班/);
const field=label=>[...document.querySelectorAll('.dp-field')].find(l=>l.firstElementChild.textContent===label)?.querySelector('input,select');
assert.equal(field('專案編號').value,'p1');assert.equal(field('工程確認單').value,'recCase');assert.equal(field('部門').value,'控制');assert.equal(field('父義務').value,'recObligation');
await value(field('負責人'),'ou_anna');await value(field('預定開始'),'2026-10-19T08:00');await value(field('預定結束'),'2026-10-19T12:00');
await click(button('檢核並預覽'));await click(button('查看核准席位'));await click(button('發布排班'));
assert.equal(calls.filter(r=>r.url.endsWith('/node-assignments')).length,2);assert.equal(calls.filter(r=>r.url.endsWith('/progress')).length,2);
await click(button('關閉'));assert.match(document.querySelector('#flow-tasks').textContent,/已發布的新排班/);
await mount({node:'control',assign:false});const disabledAssign=button('指派');assert.equal(disabledAssign.disabled,true);assert.match(document.getElementById(disabledAssign.getAttribute('aria-describedby')).textContent,/指派權限/);await act(async()=>disabledAssign.click());assert.equal(document.querySelector('.pf-task-picker'),null);
await mount({node:'control',dispatch:true,parentProject:'YX-2026-042'});await click(button('排班'));assert.match(document.querySelector('[role=dialog]').textContent,/尚無可核實的父義務/);assert.equal(document.querySelector('.dp-dialog'),null);
for(const role of ['member','viewer']){await mount({node:'control',dispatch:true,role});assert.equal(button('排班'),undefined);assert.equal(calls.some(r=>r.url.includes('/dispatch/')),false)}
for(const [tab,label] of [['overview','總覽'],['progress','工項與進度'],['flow','流程與任務'],['tasks','流程與任務']]){await mount({tab,node:'control',task:tab==='flow'?'recTask1':undefined});assert.equal(document.querySelector('.pds-tabs [aria-current=page]').textContent,label);if(tab==='flow')assert.match(document.querySelector('[role=dialog]').textContent,/控制點成果核對/)}
evidenceStatus=500;await mount({node:'control'});assert.equal(document.querySelectorAll('.pf-node').length,9);assert.equal(document.querySelectorAll('.pf-task-open').length,2);assert.match(document.querySelector('#flow-evidence').textContent,/讀取失敗/);evidenceStatus=200;await click(button('重試工程證據'));assert.match(document.querySelector('#flow-evidence').textContent,/實際完成量未知/);
await mount({node:'control',evidenceHold:true});assert.equal(document.querySelector('.pf-diagram').getAttribute('aria-busy'),'false');assert.equal(document.querySelectorAll('.pf-task-open').length,2);assert.equal(document.querySelector('#flow-evidence [aria-busy]').getAttribute('aria-busy'),'true');await act(async()=>{globalThis.releaseEvidence();await tick()});assert.match(document.querySelector('#flow-evidence').textContent,/實際完成量未知/);
nodeStatus=500;await mount({node:'control'});assert.equal(document.querySelector('.pf-diagram').getAttribute('aria-busy'),'false');assert.match(document.querySelector('#flow-evidence').textContent,/實際完成量未知/);assert.match(document.querySelector('#flow-tasks').textContent,/來源未完整/);assert.doesNotMatch(document.querySelector('#flow-tasks').textContent,/尚無可見任務/);nodeStatus=200;
await mount({node:'control',embedded:false});await click(button('更新節點與任務'));await click(document.querySelector('.pf-node[aria-label^="外業節點"]'));await click(document.querySelector('.pf-node[aria-label^="控制節點"]'));assert.equal(calls.filter(r=>r.url.endsWith('/nodes/control')).length,2);
detailStatus=500;await mount({node:'control',embedded:false});assert.match(document.querySelector('#flow-tasks').textContent,/來源未完整/);assert.match(document.querySelector('#flow-evidence').textContent,/實際完成量未知/);fixture.list.node_details=globalThis.detailPayloads;await click(button('更新節點與任務'));assert.equal(document.querySelectorAll('.pf-task-open').length,2);assert.doesNotMatch(document.querySelector('#flow-tasks').textContent,/來源未完整/);detailStatus=200;
await mount({enabled:false,node:'node_control'});assert.equal(calls.some(r=>r.url.includes('/node-assignments')),false);assert.equal(document.querySelectorAll('.pf-node').length,9);assert.match(document.querySelector('.pf-legacy').textContent,/本地/);
globalThis.sopOverview=JSON.parse(await readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8')).sop_tasks;
await mount({node:'sales'});assert.equal(document.querySelector('#flow-selected #sop-tasks .pf-task-open strong').textContent,'業主提出報價需求');assert.ok([...document.querySelectorAll('#sop-tasks button')].some(b=>b.textContent==='匯入預設任務'));globalThis.sopOverview=undefined;
await mount({node:'control',embedded:false});assert.equal(document.querySelectorAll('.pf-task-open').length,2);
{
 const realNow=Date.now;Date.now=()=>realNow()+61000;
 const fetchNow=globalThis.fetch;let releaseDetail;const detailHold=new Promise(r=>releaseDetail=r);
 globalThis.fetch=async(url,init)=>{if(url.includes('/node-assignments/nodes/'))await detailHold;return fetchNow(url,init)};
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));await act(async()=>{root.render(React.createElement(ui.ProjectDetail,{c}));await tick()});
 assert.equal(document.querySelectorAll('.pf-task-open').length,2,'revisit shows last-good task rows while revalidating');assert.equal(document.querySelector('[aria-label="任務載入中"]'),null);
 await act(async()=>{releaseDetail();await tick()});assert.equal(document.querySelectorAll('.pf-task-open').length,2);
 detailStatus=403;Date.now=()=>realNow()+122000;
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));await act(async()=>{root.render(React.createElement(ui.ProjectDetail,{c}));await tick()});
 assert.equal(document.querySelectorAll('.pf-task-open').length,0,'forbidden revalidation removes cached task rows');
 assert.match(document.querySelector('#flow-tasks').textContent,/來源未完整/);
 detailStatus=200;Date.now=realNow;
}
await mount({node:'control'});assert.match(document.querySelector('.pf-task-open small').textContent,/Lark 任務/,'rows name their source');
await click(document.querySelector('.pf-task-open'));assert.match(document.querySelector('[role=dialog] [aria-label="任務位置"]').textContent,/Lark 任務/,'drawer names its source');await click(document.querySelector('[role=dialog] [aria-label="關閉"]'));
await act(async()=>root.unmount());console.log('Unified project flow rendered checks passed');
