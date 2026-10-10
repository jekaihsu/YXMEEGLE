// Real ApprovalDetail: 查詢狀態 refresh and inline confirm focus/alert semantics.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','location','history','sessionStorage','FormData','Event','getComputedStyle'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
// React reads the DOM at import time (input events), so load it after globals exist.
const {default:React,act}=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['src/App.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.approval-detail-a11y-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let mod;try{mod=await import(bundlePath.href)}finally{await fs.unlink(bundlePath)}
let reply={status:200,body:{}},gate=null,duringRequest=null;
globalThis.fetch=async()=>{duringRequest?.();if(gate)await gate;return new Response(JSON.stringify(reply.body),{status:reply.status,headers:{'content-type':'application/json'}})};
const project={id:'p1',code:'P1',concurrency_version:1,execution_allowed:true,pm_id:'u1',admin_id:'u1',nodes:[]};
const w={version:1,projects:[project],users:[],environment:'production',approval_connection:{native_submit:{by_type:{extension:{available:true,simulation_available:true}}}}};
let approval={id:'a1',project_id:'p1',type:'extension',status:'pending',title:'T',reason:'R',created_by:'u1',created_at:'2026-01-01T00:00:00Z',task_ids:[],dates:[],lark_status:'pending',history:[]};
let session={mode:'lark',user:{id:'u1',role:'manager'}};
const runs=[];let runResult={};
const root=createRoot(document.getElementById('root'));
let refreshed=0;
const render=(over={})=>act(async()=>root.render(React.createElement(mod.ApprovalDetail,{c:{w,s:session,busy:false,refresh:async()=>{refreshed++},run:async(a)=>{runs.push(a);return runResult},go(){},route:{},...over},approval,onClose(){}})));
const q=sel=>document.querySelector(sel);
const queryBtn=()=>[...document.querySelectorAll('button')].find(b=>b.textContent.includes('查詢狀態'));
const setInstance=async v=>act(async()=>{const i=q('input[aria-label="Lark 審批實例代碼"]');const set=Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set;set.call(i,v);i.dispatchEvent(new dom.window.Event('input',{bubbles:true}))});
await render();
await setInstance('INST');
const status=()=>[...document.querySelectorAll('[role=status]')].find(e=>e.closest('.simulation-panel'));
// Success: focus lost while disabled/loading returns to the query button; result is polite status.
let release;gate=new Promise(r=>{release=r});
duringRequest=()=>document.activeElement.blur();
queryBtn().focus();
await act(async()=>{queryBtn().click()});duringRequest=null;
assert.equal(queryBtn().disabled,true);assert.equal(queryBtn().getAttribute('aria-busy'),'true');
assert.ok(status().textContent.includes('正在查詢'));
gate=null;await act(async()=>{release();await new Promise(r=>setTimeout(r,0))});
assert.equal(document.activeElement,queryBtn(),'focus restored after completion');
assert.ok(status().textContent.includes('已讀取'));assert.equal(q('.simulation-panel [role=alert]'),null);
// Failure is role=alert, status stays empty, focus restored.
reply={status:503,body:{detail:'查詢失敗 503'}};
await act(async()=>{queryBtn().focus();queryBtn().click()});await act(async()=>{await new Promise(r=>setTimeout(r,0))});
assert.equal(q('.simulation-panel [role=alert]').textContent,'查詢失敗 503');
assert.equal(status().textContent,'');
assert.equal(document.activeElement,queryBtn());
// Focus the user moved elsewhere is never stolen.
const other=q('input[aria-label="Lark 審批實例代碼"]');
reply={status:200,body:{}};duringRequest=()=>other.focus();
await act(async()=>{queryBtn().focus();queryBtn().click()});duringRequest=null;await act(async()=>{await new Promise(r=>setTimeout(r,0))});
assert.equal(document.activeElement,other,'moved focus is preserved');
assert.equal(q('.simulation-panel [role=alert]'),null,'alert clears after success');

// Inline confirm: cancel and successful confirm both return focus to a live control.
approval={...approval,status:'approved',lark_status:'approved'};
await render();
const opener=()=>[...document.querySelectorAll('footer button')].find(b=>b.textContent.includes('套用新期限'));
await act(async()=>{opener().focus();opener().click()});
assert.ok(q('.confirmation-inline'));
const cancel=()=>[...document.querySelectorAll('.confirmation-inline button')].find(b=>b.textContent==='取消');
await act(async()=>{cancel().focus();cancel().click()});
assert.equal(q('.confirmation-inline'),null);
assert.equal(document.activeElement,opener(),'cancel returns focus to opener');
await act(async()=>{opener().click()});
const ok=()=>[...document.querySelectorAll('.confirmation-inline button')].find(b=>b.textContent.includes('確認操作'));
runResult=undefined;await act(async()=>{ok().focus();ok().click()});
assert.ok(q('.confirmation-inline'),'failed confirm keeps inline controls for retry');
assert.deepEqual(runs.at(-1),'approval_execute');
runResult={};
approval={...approval};
await act(async()=>{ok().focus();ok().click()});await act(async()=>{await new Promise(r=>setTimeout(r,0))});
assert.equal(q('.confirmation-inline'),null);
assert.notEqual(document.activeElement,document.body,'focus not lost to body after confirm');
console.log('approval detail a11y checks passed');
