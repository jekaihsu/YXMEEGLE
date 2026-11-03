import assert from 'node:assert/strict';
import {writeFile,unlink,readFile} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture,embeddedAssignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','KeyboardEvent','MouseEvent','HTMLElement','HTMLInputElement','HTMLSelectElement','HTMLTextAreaElement','HTMLDetailsElement','Element','Node','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.cancelAnimationFrame=clearTimeout;globalThis.getComputedStyle=dom.window.getComputedStyle;
HTMLElement.prototype.scrollIntoView=function(){};globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetailGate as ProjectDetail} from './src/ProjectDetail'; export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.stage-workspace.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));progress.project_id='p1';
const tick=(ms=15)=>new Promise(r=>setTimeout(r,ms));
const can={assign:true,edit_status:true,cancel:true,edit_details:true,claim:false};
const mk=(id,over={})=>({id,record_id:id,revision:`rev-${id}-1`,title:`任務 ${id}`,detail:'',assignee:{open_id:'ou_wei',name:'合成 陳威廷'},assigned_by:null,department:'控制',deadline:'2026-10-25',status:'待處理',done_at:null,created_at:null,can:{...can},...over});
let root,c,fixture,calls,mode,holdDetail,tasksByNode;
const jsonResponse=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
async function mount({node,task,tab='overview',tasks,embedded=true,assign=true,filters,detailStatus,project,section,stale=false,configure}={}){
 if(root)await act(async()=>root.unmount());ui.invalidateSessionEpoch();
 const base=projectFixture();Object.assign(base.project,project||{});fixture=embeddedAssignmentFixture();mode={detailStatus};holdDetail=null;
 tasksByNode=tasks||{control:[mk('c1',{status:'已完成'}),mk('c2',{status:'已完成'}),mk('c3',{status:'已完成'}),mk('c4',{assignee:null}),mk('c5',{status:'進行中'})],field:[mk('f1',{assignee:null,deadline:'2026-10-10'})],pm:[]};
 for(const n of fixture.list.nodes){
  const rows=tasksByNode[n.key]||[];fixture.list.node_details[n.key]={tasks:rows,assignable_people:[{open_id:'ou_anna',name:'合成 林安娜',departments:['控制']},{open_id:'ou_wei',name:'合成 陳威廷',departments:['控制']}]};
  n.tasks={done:rows.filter(t=>t.status==='已完成').length,total:rows.length};n.departments=['控制'];
  n.derived_status=n.key==='control'?'進行中':['sales','pm','confirmation'].includes(n.key)?'已完成':'未開始';
 }
 fixture.list.summary.current_node='control';fixture.list.stale=stale;if(stale)fixture.list.writes_enabled=false;
 if(!assign)for(const rows of Object.values(fixture.list.node_details))rows.tasks.forEach(t=>t.can.assign=false);
 if(!embedded)fixture.list.node_details=undefined;
 configure?.(base,fixture);
 calls=[];
 c={w:base.workspace,s:{user:{...base.user,role:'manager'},mode:'lark',workspace_id:'stage-ws',features:{node_assignment:true}},route:{view:'project',project:'p1',tab,node,task,section,task_filters:filters},busy:false,run:async()=>true,notify(){},registerDrafts(){},refresh:async()=>{},go(route){c={...c,route};root.render(React.createElement(ui.ProjectDetail,{c}))}};
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

await mount({tab:'overview',configure(base,f){f.list.nodes.find(n=>n.key==='control').owners=[]}});
assert.match(document.querySelector('.po-next-action').textContent,/前往指派負責人/,'owner entry precedes tasks when capability permits');
assert.equal(document.querySelectorAll('.po-next-action button').length,1);
assert.equal(document.querySelectorAll('.i3-stepper .pf-node').length,9);
await mount({tab:'overview',tasks:{control:[]}});
assert.match(document.querySelector('.po-next-action').textContent,/前往新增任務/);
await mount({tab:'overview',stale:true,configure(base,f){f.list.nodes.find(n=>n.key==='control').owners=[]}});
assert.match(document.querySelector('.po-next-action').textContent,/查看流程與任務/);
assert.doesNotMatch(document.querySelector('.po-next-action').textContent,/前往指派負責人/);
await mount({tab:'overview',project:{code:'115575',name:'精餾塔垂直度測量',client:'亞欣達特殊材料股份有限公司',status:'paused',execution_status:'paused',progress_status:'pending',source_status:'尚未開始',source_lifecycle:{state:'needs_verification',canonical:null,reasons:['blank']}}});
assert.match(document.querySelector('h1').textContent,/精餾塔垂直度測量/);
assert.match(document.querySelector('.po-source-note').textContent,/查看狀態差異/);
assert.match(document.querySelector('.po-next-action').textContent,/查看流程與任務/);
assert.equal(document.querySelectorAll('.pds-status-chip').length,1);
await mount({tab:'flow',tasks:{control:Array.from({length:27},(_,i)=>mk('many'+i,{title:'廠區掃描與數位建模（美國）核對報價範圍與成本 '+i}))}});
assert.equal(document.querySelectorAll('.pf-task-open').length,8);
assert.equal(document.querySelectorAll('.i3-origin').length,8);
assert.equal(document.querySelector('.i3-origin').textContent,'Lark');
await click(button('查看全部（27 項）'));
assert.equal(document.querySelectorAll('.pf-task-open').length,27);
assert.equal(writes().length,0);
assert.match(document.body.textContent,/切換檢視不會啟動節點或變更目前階段/);
await click(document.querySelector('.pf-node[aria-label^="PM"]'));
assert.equal(fixture.list.summary.current_node,'control');assert.equal(writes().length,0);
await mount({tab:'flow',assign:false});
assert.ok(button('指派').disabled);assert.match(rowOf('c4').textContent,/無指派權限/);
await mount({tab:'flow',configure(base){base.project.nodes.find(n=>n.key==='control').requirements=[{key:'dispatch',label:'正式派工確認'},{key:'daily',label:'工作日報'},{key:'report',label:'完工檢核與報告'},{key:'photo',label:'成果照片'}]}});
await act(async()=>{await tick(80)});
assert.match(document.querySelector('.i3-missing').textContent,/缺 4 項 · 正式派工確認、工作日報、完工檢核與報告、成果照片/);
assert.equal(document.querySelectorAll('.delivery-checks .late-text').length,0);
assert.equal(document.querySelector('.i3-stage-rows [data-section=review] small').textContent,'缺交付資料：4');
for(const row of document.querySelectorAll('.i3-stage-rows button:not([data-section=review])'))assert.equal(row.querySelector('small').textContent,'阻礙數：待確認');
assert.ok(document.querySelector('.i3-stage-rows button[data-section="finance"]'));
const switcher=document.querySelector('.i3-more-stage'),content=document.querySelector('.i3-stage-content');
assert.ok(switcher.compareDocumentPosition(content)&Node.DOCUMENT_POSITION_FOLLOWING);
await click(document.querySelector('.i3-stage-rows [data-section=roles]'));
assert.equal(document.querySelector('.i3-stage-rows [data-section=roles]').getAttribute('aria-expanded'),'true');
assert.equal(document.querySelector('.i3-stage-rows [data-section=review]').getAttribute('aria-expanded'),'false');
assert.equal(document.activeElement,document.querySelector('.i3-stage-content>h3'));assert.equal(document.activeElement.textContent,'責任與交接');assert.equal(writes().length,0);
for(const [requirements,evidence,expected] of [
 [[],[],'0'],
 [[{key:'report',label:'完工報告'}],[{node_id:'node_control',key:'report',status:'returned'}],'0'],
 [undefined,[],'待確認'],
 [[{key:'report',label:'完工報告'}],undefined,'待確認']
]){await mount({tab:'flow',configure(base){base.project.nodes.find(n=>n.key==='control').requirements=requirements;base.project.evidence=evidence}});await act(async()=>{await tick(80)});assert.equal(document.querySelector('.i3-stage-rows [data-section=review] small').textContent,'缺交付資料：'+expected)}
await mount({configure(base,f){f.list.nodes.find(n=>n.key==='control').owners=[];f.list.can.control.assign=false;f.list.can.control.claim=true}});
assert.equal(document.querySelector('.po-next-action h3').textContent,'認領節點');await click(button('前往認領節點'));assert.equal(c.route.section,'node-claim');assert.equal(writes().length,0);assert.equal(document.activeElement.dataset.nodeAction,'claim');
await mount({configure(base,f){f.list.nodes.find(n=>n.key==='control').owners=[]}});await click(button('前往指派負責人'));assert.ok(document.querySelector('.pf-node-actions form'));assert.equal(writes().length,0);
await mount({tasks:{control:[]}});await click(button('前往新增任務'));assert.ok(document.querySelector('.pf-node-actions form'));assert.equal(writes().length,0);
await mount({configure(base,f){f.list.nodes=f.list.nodes.slice(0,6);f.list.summary.current_node='control'}});assert.equal(document.querySelectorAll('.i3-stepper .pf-node').length,6);assert.equal(document.querySelector('.pf-chain').style.getPropertyValue('--i3-node-count'),'6');
assert.equal(document.querySelector('.pds-status-chip').textContent,document.querySelector('.cs-stage strong').textContent);
await act(async()=>root.unmount());
console.log('PASS I3: next-action capabilities/fallback, source mismatch, nine nodes, selection without writes, 27-task cap/reveal, origin, denied action reason, missing-evidence consolidation, unknown disclosure counts');
