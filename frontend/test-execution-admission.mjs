// Synthetic-only check of admission display, handling entry and manager-only queue.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
// DOM globals must exist before React loads so its event-support detection sees them.
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=company'});
for(const key of ['window','document','location','history','sessionStorage','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const {default:React,act}=await import('react');
const {createRoot}=await import('react-dom/client');
const load=async(entry,name)=>{const b=await build({entryPoints:[entry],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
 const path=new URL(`./.${name}-bundle.mjs`,import.meta.url);await fs.writeFile(path,b.outputFiles[0].text);try{return await import(path.href)}finally{await fs.unlink(path)}};
const {AdmissionCell,ExecutionAdmissionQueue}=await load('src/ExecutionAdmission.tsx','adm');
const {CompanyCockpit}=await load('src/CompanyCockpit.tsx','cockpit');
const rules=await load('src/admissionRules.ts','rules');
let checks=0;const ok=(c,m)=>{assert.ok(c,m);checks++};
const proj=(id,over={})=>({id,code:id,name:'合成 '+id,case_visibility:'source_reference',execution_system:'pending',execution_system_label:'待確認歸屬',execution_allowed:false,execution_readonly_reason:'等待管理員核定案件歸屬',...over});
const projects=[proj('SYN-P1'),proj('SYN-P2'),proj('SYN-M',{execution_system:'meegle',execution_system_label:'Meegle 舊案（唯讀參考）',execution_readonly_reason:'舊案留在 Meegle 完成'}),
 proj('SYN-W',{execution_system:'workbench',execution_system_label:'工作台執行',execution_allowed:true,execution_readonly_reason:null}),proj('SYN-X',{case_visibility:'excluded_history'})];
ok(rules.pendingAdmissionQueue(projects,'pm').length===0&&rules.pendingAdmissionQueue(projects,undefined).length===0,'non-managers get no queue');
ok(rules.pendingAdmissionQueue(projects,'manager').map(p=>p.id).join()==='SYN-P1,SYN-P2','only pending source_reference cases are queued');
ok(rules.admissionState(projects[0],'pm').handling==='request_manager_review'&&rules.admissionState(projects[0],'manager').handling==='manager_assign','handling depends on role');
ok(rules.admissionState(projects[2],'manager').handling==='none','Meegle case is not a pending decision');
const root=createRoot(document.getElementById('root'));
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(r=>setTimeout(r,0))});
const text=el=>document.querySelector(el).textContent;
await flush(()=>root.render(React.createElement(AdmissionCell,{p:projects[0],role:'pm'})));
ok(text('.admission-cell').includes('待確認歸屬')&&text('.admission-cell').includes('等待管理員核定案件歸屬')&&text('.admission-cell').includes('申請核定')&&text('.admission-cell').includes('無權自行指派'),'non-manager sees system, exact reason and request-review message');
ok(!document.querySelector('.admission-cell a'),'non-manager has no assignment entry');
await flush(()=>root.render(React.createElement(AdmissionCell,{p:projects[0],role:'manager'})));
ok(!!document.querySelector('.admission-cell a[href*="SYN-P1"]'),'manager has a handling entry to the case');
await flush(()=>root.render(React.createElement(AdmissionCell,{p:projects[3],role:'manager'})));
ok(text('.admission-cell')==='工作台執行'&&!document.querySelector('.admission-reason'),'admitted case shows no block reason');
const calls=[];const run=async(action,payload,scope)=>{calls.push({action,payload,scope});return {}};
const w={environment:'production',projects};
await flush(()=>root.render(React.createElement(ExecutionAdmissionQueue,{w,s:{user:{role:'pm'}},run,busy:false})));
ok(!document.querySelector('.admission-queue'),'non-manager does not see the queue');
await flush(()=>root.render(React.createElement(ExecutionAdmissionQueue,{w,s:{user:{role:'manager'}},run,busy:false})));
ok(document.querySelectorAll('.admission-queue li').length===2&&!document.querySelector('.admission-queue li select').value&&document.querySelector('.admission-queue li button').disabled,'queue lists pending cases, no default target, submit disabled');
ok(!/批次|全部核准/.test(document.querySelector('.admission-queue').textContent.replace('不提供批次核准','')),'no bulk control');
const set=(el,v,proto)=>{Object.getOwnPropertyDescriptor(proto,'value').set.call(el,v);for(const t of ['input','change'])el.dispatchEvent(new dom.window.Event(t,{bubbles:true}))};
const li=document.querySelector('.admission-queue li');
await flush(()=>set(li.querySelector('select'),'workbench',dom.window.HTMLSelectElement.prototype));
await flush(()=>set(li.querySelector('input'),'合成核定依據',dom.window.HTMLInputElement.prototype));
await flush(()=>li.querySelector('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));
ok(calls.length===1&&calls[0].action==='case_execution_assign'&&calls[0].scope.project_id==='SYN-P1'&&calls[0].payload.execution_system==='workbench','submits exactly one single-case assignment');
const payload={as_of:'2026-10-06',checked_at:'2026-10-06T01:00:00Z',date_basis:'synthetic',source:{status:'ready',mapping_status:'ready',last_success_at:null},
 totals:{cases:1,confirmed_cases:1,intake_records:0,workbench_cases:0,deliveries_confirmed:0,tasks_total:0,tasks_completed:0,tasks_overdue:0,pending_local_reviews:0,pending_native_reviews:0,source_status_counts:{},execution_status_counts:{}},
 missing:{task_due_date:0,group:0,source_status:0},groups:[],cases:[{case_type:'formal',id:'SYN-P1',code:'SYN-P1',name:'合成',group:'',source_status:'執行中',execution_status:'pending',execution_system:'pending',execution_system_label:'待確認歸屬',execution_readonly_reason:'等待管理員核定案件歸屬',case_visibility:'source_reference',tasks_total:0,tasks_completed:0,tasks_overdue:0,pending_local_reviews:0,pending_native_reviews:0}],
 pagination:{offset:0,limit:40,total:1,has_more:false}};
globalThis.fetch=async()=>new Response(JSON.stringify(payload),{status:200,headers:{'content-type':'application/json'}});
await flush(()=>root.render(React.createElement(CompanyCockpit,{refreshVersion:0,role:'pm'})));
const cell=document.querySelector('.cockpit-case-table tbody .admission-cell');
ok(!!cell&&cell.textContent.includes('待確認歸屬')&&cell.textContent.includes('等待管理員核定案件歸屬')&&cell.textContent.includes('無權自行指派'),'cockpit row shows execution_system, exact reason and request-review message');
console.log(`Execution admission: ${checks} checks passed`);process.exit(0);
