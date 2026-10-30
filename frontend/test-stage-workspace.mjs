import assert from 'node:assert/strict';
import {writeFile,unlink,readFile} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture,embeddedAssignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','MouseEvent','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','Element','Node','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetail} from './src/ProjectDetail'; export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.stage-workspace.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));progress.project_id='p1';
const tick=(ms=15)=>new Promise(r=>setTimeout(r,ms));
const can={assign:true,edit_status:true,cancel:true,edit_details:true,claim:false};
const mk=(id,over={})=>({id,record_id:id,revision:`rev-${id}-1`,title:`任務 ${id}`,detail:'',assignee:{open_id:'ou_wei',name:'合成 陳威廷'},assigned_by:null,department:'控制',deadline:'2026-10-25',status:'待處理',done_at:null,created_at:null,can:{...can},...over});
let root,c,fixture,calls,mode,holdDetail,tasksByNode;
const jsonResponse=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
async function mount({node,task,tab='overview',tasks,embedded=true,assign=true,filters,detailStatus,project}={}){
 if(root)await act(async()=>root.unmount());ui.invalidateSessionEpoch();
 const base=projectFixture();Object.assign(base.project,project||{});fixture=embeddedAssignmentFixture();mode={detailStatus};holdDetail=null;
 tasksByNode=tasks||{control:[mk('c1',{status:'已完成'}),mk('c2',{status:'已完成'}),mk('c3',{status:'已完成'}),mk('c4',{assignee:null}),mk('c5',{status:'進行中'})],field:[mk('f1',{assignee:null,deadline:'2026-10-10'})],pm:[]};
 for(const n of fixture.list.nodes){
  const rows=tasksByNode[n.key]||[];fixture.list.node_details[n.key]={tasks:rows,assignable_people:[{open_id:'ou_anna',name:'合成 林安娜',departments:['控制']},{open_id:'ou_wei',name:'合成 陳威廷',departments:['控制']}]};
  n.tasks={done:rows.filter(t=>t.status==='已完成').length,total:rows.length};n.departments=['控制'];
  n.derived_status=n.key==='control'?'進行中':['sales','pm','confirmation'].includes(n.key)?'已完成':'未開始';
 }
 fixture.list.summary.current_node='control';
 if(!assign)for(const rows of Object.values(fixture.list.node_details))rows.tasks.forEach(t=>t.can.assign=false);
 if(!embedded)fixture.list.node_details=undefined;
 calls=[];
 c={w:base.workspace,s:{user:{...base.user,role:'manager'},mode:'lark',workspace_id:'stage-ws',features:{node_assignment:true}},route:{view:'project',project:'p1',tab,node,task,task_filters:filters},busy:false,run:async()=>true,notify(){},registerDrafts(){},refresh:async()=>{},go(route){c={...c,route};root.render(React.createElement(ui.ProjectDetail,{c}))}};
 const detailOf=key=>({...fixture.list,node:fixture.list.nodes.find(n=>n.key===key),can:fixture.list.can[key],tasks:tasksByNode[key]||[],assignable_people:[{open_id:'ou_anna',name:'合成 林安娜',departments:['控制']},{open_id:'ou_wei',name:'合成 陳威廷',departments:['控制']}]});
 globalThis.fetch=async(url,init={})=>{const method=init.method||'GET';calls.push({url,method,body:init.body?JSON.parse(init.body):null});
  if(url.endsWith('/progress'))return jsonResponse(progress);
  if(url.endsWith('/node-assignments'))return jsonResponse(fixture.list);
  if(url.includes('/node-assignments/nodes/')){
   const key=url.split('/nodes/')[1].split('/')[0];
   if(method==='GET'){if(mode.detailStatus)return jsonResponse({detail:'合成讀取失敗'},mode.detailStatus);if(holdDetail&&holdDetail.key===key)await holdDetail.promise;return jsonResponse(detailOf(key))}
   const id=url.split('/').at(-1),row=tasksByNode[key].find(t=>t.id===id),patch=JSON.parse(init.body);
   if(mode.patch==='conflict'){row.assignee={open_id:'ou_anna',name:'合成 林安娜'};row.revision='rev-newer';return jsonResponse({detail:'已被更新',code:'revision_conflict'},409)}
   if(mode.patch==='forbidden'){row.can.assign=false;return jsonResponse({detail:'沒有指派權限',code:'forbidden'},403)}
   if(mode.patch==='unknown'){return jsonResponse({detail:'未知',code:'outcome_unknown'},502)}
   if(mode.patch==='unknown-applied-partial'){row.assignee={open_id:patch.assignee_open_id,name:'合成 林安娜'};row.revision='rev-partial';return jsonResponse({detail:'未知',code:'outcome_unknown'},502)}
   if(mode.patch==='invalid')return jsonResponse({detail:[{loc:['body','assignee_open_id'],msg:'此人員已停用'}]},422);
   if('assignee_open_id' in patch)row.assignee=patch.assignee_open_id?{open_id:patch.assignee_open_id,name:'合成 林安娜'}:null;if('deadline' in patch)row.deadline=patch.deadline;row.revision=`${row.revision}x`;
   return jsonResponse(detailOf(key));
  }
  if(url.endsWith('/sop-tasks'))return jsonResponse({code:'sop_import_forbidden'},403);
  return jsonResponse({detail:'disabled'},404);
 };
 root=createRoot(document.getElementById('root'));await act(async()=>{root.render(React.createElement(ui.ProjectDetail,{c}));await tick(40)});
}
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
const click=async el=>{assert.ok(el,'control exists');await act(async()=>{el.click();await tick()})};
const setInput=async(el,v)=>act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));await tick()});
const dialog=()=>document.querySelector('.task-drawer[role=dialog]');
const writes=()=>calls.filter(r=>r.method!=='GET');
const rowOf=id=>document.querySelector(`[data-assignment-task="${id}"]`);
async function pickPerson(name){
 await click(dialog().querySelector('.assignee-picker button'));
 const option=[...document.querySelectorAll('[role=option]')].find(o=>o.textContent.includes(name));await click(option);
}
async function openDrawer(id,label='指派'){await click([...rowOf(id).querySelectorAll('button')].find(b=>b.textContent.trim()===label));assert.ok(dialog(),'drawer opens')}
const results=[];
async function check(id,fn){try{await fn();results.push(['PASS',id])}catch(error){results.push(['FAIL',id,error.message.split('\n')[0]]);console.error(error)}}

await check('Concept B defaults to action-first and stage selection never changes the current stage',async()=>{
 await mount({tab:'flow',node:'control'});
 assert.equal(button('行動優先').getAttribute('aria-pressed'),'true');
 assert.equal(document.querySelector('.pf-stage-workspace'),null);
 await click(button('階段導覽'));
 assert.equal(document.querySelectorAll('.pf-stage-nav .pf-node').length,9);
 await click(document.querySelector('.pf-stage-nav .pf-node[aria-label^="PM"]'));
 assert.equal(c.route.node,'pm');
 assert.equal(fixture.list.summary.current_node,'control');
 assert.match(document.querySelector('.pf-stage-nav .pf-node[aria-label^="控制"] .pf-stage-marker').textContent,/目前階段/);
 assert.equal(document.querySelector('.pf-stage-nav .pf-node[aria-label^="PM"]').getAttribute('aria-current'),'step');
 assert.match(document.querySelector('#flow-tasks h3').textContent,/PM/);
 await click(button('行動優先'));
 assert.equal(c.route.node,'pm');assert.equal(writes().length,0);
});
await check('overview DOM places tasks before the selectable diagram, node facts and evidence',async()=>{
 await mount();
 const tasks=document.querySelector('#flow-tasks'),diagram=document.querySelector('.pf-diagram'),detail=document.querySelector('.pf-stage-detail'),evidence=document.querySelector('#flow-evidence');
 const precedes=(a,b)=>assert.ok(a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING);
 precedes(document.querySelector('.cs-summary'),tasks);precedes(tasks,diagram);precedes(diagram,detail);precedes(detail,evidence);
 assert.equal(tasks.contains(evidence),false);
 await click(document.querySelector('.pf-node[aria-label^="PM"]'));
 assert.match(document.querySelector('#flow-tasks h3').textContent,/PM/);
});
await check('T01 opening, selecting nodes and switching tabs cause zero writes',async()=>{
 await mount();assert.ok(document.querySelector('.cs-summary'));
 assert.match(document.querySelector('.cs-summary').textContent,/目前階段控制/);
 await click(document.querySelector('.pf-node[aria-label^="PM"]'));await click(document.querySelector('.pf-node[aria-label^="控制"]'));
 await act(async()=>{React.startTransition(()=>c.go({...c.route,tab:'flow'}));await tick(40)});
 assert.equal(writes().length,0);assert.ok(calls.length>0);
});
await check('T02 selecting another node keeps the current stage and offers the way back',async()=>{
 await mount();await click(document.querySelector('.pf-node[aria-label^="PM"]'));
 assert.match(document.querySelector('#flow-selected h2').textContent,/PM/);assert.match(document.querySelector('.nc-eyebrow').textContent,/目前選取的節點/);
 assert.match(document.querySelector('.cs-summary').textContent,/目前階段控制/);
 assert.match(document.querySelector('.nc-diff').textContent,/目前階段：控制/);
 await click(button('回到目前階段'));assert.equal(c.route.node,'control');assert.equal(document.querySelector('.nc-diff'),null);
});
await check('T04/T05 the node card shows 3 / 5 and 60% while the unassigned task is both pending and unassigned',async()=>{
 await mount({node:'control'});
 const card=document.querySelector('#flow-selected').textContent;assert.match(card,/任務完成數：3 \/ 5 已完成/);assert.match(card,/60%/);
 assert.match(rowOf('c4').textContent,/任務狀態：待處理/);assert.match(rowOf('c4').textContent,/尚未指派/);assert.doesNotMatch(rowOf('c4').textContent,/受阻/);
 assert.match(document.querySelector('#flow-selected').textContent,/節點狀態：進行中/);
});
await check('T07 without the assign capability the reason is explained and no request can start',async()=>{
 await mount({node:'control',assign:false});
 const trigger=[...rowOf('c4').querySelectorAll('button')].find(b=>b.textContent.trim()==='指派');assert.ok(trigger.disabled);
 assert.match(rowOf('c4').textContent+document.querySelector('.disabled-action-reason,[role=tooltip]')?.textContent,/無指派權限/);assert.equal(writes().length,0);
});
await check('T08 saving an executor sends one request, refreshes the list and returns focus',async()=>{
 await mount({node:'control'});await openDrawer('c4');
 assert.match(dialog().textContent,/最新讀取版本/);assert.match(dialog().textContent,/任務 c4/);
 await pickPerson('林安娜');
 const save=[...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存');
 await act(async()=>{save.click();save.click();await tick(40)});
 assert.equal(writes().length,1);assert.equal(writes()[0].method,'PATCH');assert.deepEqual(Object.keys(writes()[0].body).sort(),['assignee_open_id','expected_revision','request_id']);
 assert.equal(dialog(),null);assert.match(rowOf('c4').textContent,/林安娜/);assert.doesNotMatch(rowOf('c4').textContent,/尚未指派/);
 await act(async()=>{await tick(30)});assert.ok(rowOf('c4').contains(document.activeElement),'focus returns to the row trigger '+document.activeElement.outerHTML.slice(0,120));
});
await check('T09 an unsaved draft asks before closing and discarding sends nothing',async()=>{
 await mount({node:'control'});await openDrawer('c4');await pickPerson('林安娜');
 await click(button('取消'));assert.ok(dialog().querySelector('[role=alertdialog]'));
 await click(button('保留編輯'));assert.ok(dialog());
 await act(async()=>{document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick()});assert.ok(dialog().querySelector('[role=alertdialog]'));
 await click(button('放棄變更'));assert.equal(dialog(),null);assert.equal(writes().length,0);
 await openDrawer('c4');await click(button('取消'));assert.equal(dialog(),null,'an untouched drawer closes at once');
});
await check('T10 a rejected candidate shows a field error and a summary, keeps the draft and leaves the list',async()=>{
 await mount({node:'control'});await openDrawer('c4');await pickPerson('林安娜');mode.patch='invalid';
 await click([...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存'));
 assert.ok(dialog());assert.match(dialog().textContent,/此人員已停用/);assert.ok(dialog().querySelector('.ad-summary'));assert.match(dialog().querySelector('.assignee-picker button').textContent,/林安娜/);
 assert.match(rowOf('c4').textContent,/尚未指派/);
});
await check('T11 a stale revision shows the conflict with the latest value and does not overwrite silently',async()=>{
 await mount({node:'control'});await openDrawer('c4');await pickPerson('陳威廷');mode.patch='conflict';
 await click([...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存'));await act(async()=>{await tick(40)});
 assert.match(dialog().textContent,/此任務已被他人修改/);assert.match(dialog().querySelector('.ad-diff').textContent,/陳威廷/);assert.match(dialog().querySelector('.ad-diff').textContent,/林安娜/);
 assert.equal(writes().length,1);mode.patch='';
 await click(button('以最新值重新檢查'));assert.equal(writes().length,1,'no automatic resubmit');
 await click([...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存'));assert.equal(writes().length,2);assert.equal(writes()[1].body.expected_revision,'rev-newer');
});
await check('T12 a capability revoked during save stops writing and reloads capabilities',async()=>{
 await mount({node:'control'});await openDrawer('c4');await pickPerson('林安娜');mode.patch='forbidden';
 await click([...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存'));await act(async()=>{await tick(40)});
 assert.match(dialog().textContent,/權限已變更/);assert.ok([...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存').disabled);assert.equal(writes().length,1);
 assert.ok(calls.filter(r=>r.method==='GET'&&r.url.endsWith('/node-assignments')).length>=2,'capabilities re-read');
});
await check('T13 an unknown outcome verifies the result before a same-request retry',async()=>{
 await mount({node:'control'});await openDrawer('c4');await pickPerson('林安娜');mode.patch='unknown';
 await click([...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存'));await act(async()=>{await tick(40)});
 assert.match(dialog().textContent,/儲存結果不明/);const inDialog=t=>[...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()===t);assert.ok(inDialog('重試同一操作').disabled);assert.equal(writes().length,1);
 await click(inDialog('查詢最新結果'));await act(async()=>{await tick(40)});
 assert.match(dialog().textContent,/尚未套用/);assert.equal(inDialog('重試同一操作').disabled,false);mode.patch='';
 await click(inDialog('重試同一操作'));await act(async()=>{await tick(40)});
 assert.equal(writes().length,2);assert.equal(writes()[1].body.request_id,writes()[0].body.request_id);assert.equal(dialog(),null);
});
await check('T23 executor saved but deadline not saved is reported field by field, never as full success',async()=>{
 await mount({node:'control'});await openDrawer('c4');await pickPerson('林安娜');await setInput(dialog().querySelector('input[type=date]'),'2026-12-01');mode.patch='unknown-applied-partial';
 await click([...dialog().querySelectorAll('button')].find(b=>b.textContent.trim()==='儲存'));await act(async()=>{await tick(40)});
 await click(button('查詢最新結果'));await act(async()=>{await tick(40)});
 assert.match(dialog().textContent,/只有部分欄位已儲存/);assert.match(dialog().textContent,/執行人：已儲存/);assert.match(dialog().textContent,/期限：尚未儲存/);
});
await check('T19 a deep link to a task in another stage selects it, states the stage difference and does not move the current stage',async()=>{
 await mount({node:'control',task:'f1'});await act(async()=>{await tick(60)});
 assert.equal(c.route.node,'field');assert.match(document.querySelector('#flow-selected h2').textContent,/外業/);
 assert.match(document.querySelector('.st-note[role=status]').textContent,/不是目前階段「控制」/);assert.match(document.querySelector('.cs-summary').textContent,/目前階段控制/);
 await mount({node:'control',task:'zzz-missing'});await act(async()=>{await tick(60)});assert.match(document.body.textContent,/找不到此 Lark 任務/);
});
await check('T20 a late response for node A never overwrites the newer selection B',async()=>{
 await mount({embedded:false,node:'control'});await act(async()=>{await tick(60)});
 let release;holdDetail={key:'pm',promise:new Promise(r=>release=r)};
 tasksByNode.pm=[mk('p1',{title:'PM 舊回應任務'})];fixture.list.nodes.find(n=>n.key==='pm').tasks={done:0,total:1};
 await click(document.querySelector('.pf-node[aria-label^="PM"]'));
 tasksByNode.field=[mk('f1',{title:'外業任務 B'})];
 await click(document.querySelector('.pf-node[aria-label^="外業"]'));await act(async()=>{await tick(60)});
 release();await act(async()=>{await tick(60)});
 assert.match(document.querySelector('#flow-selected h2').textContent,/外業/);assert.doesNotMatch(document.querySelector('#flow-tasks').textContent,/PM 舊回應任務/);
});
await check('T21 failure, zero tasks and an empty filter use three different messages',async()=>{
 await mount({embedded:false,node:'control',detailStatus:500});await act(async()=>{await tick(60)});
 assert.match(document.querySelector('#flow-tasks').textContent,/任務來源暫不可用|讀取失敗/);assert.doesNotMatch(document.querySelector('#flow-tasks').textContent,/此節點尚無可顯示任務/);
 await mount({node:'pm'});await act(async()=>{await tick(40)});
 assert.match(document.querySelector('#flow-tasks').textContent,/此節點尚無可顯示任務/);
 await mount({node:'control',filters:'blocked'});await act(async()=>{await tick(40)});
 assert.match(document.querySelector('#flow-tasks').textContent,/沒有符合條件的任務/);assert.match(document.querySelector('#flow-tasks').textContent,/此來源未提供任務阻礙資訊/);
 assert.match(document.querySelector('.st-count').textContent,/符合條件 0 項 · 節點共 5 項/);
 await click(document.querySelector('.st-applied button'));assert.match(document.querySelector('.st-count').textContent,/符合條件 5 項/);
});
await check('T22 the drawer takes focus, keeps Tab inside and closes with Escape back to its trigger',async()=>{
 await mount({node:'control'});const trigger=[...rowOf('c4').querySelectorAll('button')].find(b=>b.textContent.trim()==='指派');trigger.focus();
 await click(trigger);assert.ok(dialog().contains(document.activeElement));
 for(let i=0;i<12;i++){await act(async()=>{document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));await tick(5)});}
 assert.ok(dialog().contains(document.activeElement)||document.activeElement===dialog());
 await act(async()=>{document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick(20)});
 assert.equal(dialog(),null);await act(async()=>{await tick(30)});assert.ok(rowOf('c4').contains(document.activeElement));
});
await check('other stages are collapsed by default, expand on demand and are labelled read-only context',async()=>{
 await mount({node:'control'});
 const toggle=document.querySelector('.st-group[data-node=field] button');assert.equal(toggle.getAttribute('aria-expanded'),'false');assert.equal(document.querySelector('[data-assignment-task="f1"]'),null);
 await click(toggle);assert.equal(toggle.getAttribute('aria-expanded'),'true');assert.ok(document.querySelector('[data-assignment-task="f1"]'));
});

await check('P2 case status and source record status are labelled as different layers and never share a label',async()=>{
 await mount({node:'control',project:{status:'paused',source_status:'待確認單'}});
 const header=document.querySelector('.pds-case-status').textContent;
 assert.match(header,/案件狀態暫停中/);assert.match(document.querySelector('.pds-case-status').title,/案件狀態描述整體案件；節點狀態描述此階段；任務狀態描述單項工作/);
 const labels=[...document.querySelectorAll('.po-sidebar dt')].map(d=>d.textContent);
 assert.ok(labels.includes('來源紀錄狀態'));assert.ok(!labels.includes('案件狀態'),'sidebar no longer calls the source status 案件狀態');
 const side=[...document.querySelectorAll('.po-sidebar dl>div')].find(d=>d.querySelector('dt').textContent==='來源紀錄狀態').textContent;
 assert.match(side,/待確認單/);assert.match(side,/不等於案件狀態/);
 assert.match(document.querySelector('#flow-selected').textContent,/節點狀態：/);assert.match(rowOf('c4').textContent,/任務狀態：/);
});
await act(async()=>root.unmount());
for(const r of results)console.log(r.join(' '));
if(results.some(r=>r[0]==='FAIL'))process.exit(1);
