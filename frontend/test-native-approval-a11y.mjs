// Real NativeApprovalControls: focus restoration, alert/status semantics and action availability.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({entryPoints:['src/NativeApprovalControls.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.native-approval-a11y-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let mod;try{mod=await import(bundlePath.href)}finally{await fs.unlink(bundlePath)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','location','history','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
let reply={status:200,body:{}},duringRequest=null,gate=null;
globalThis.fetch=async()=>{duringRequest?.();if(gate)await gate;return new Response(JSON.stringify(reply.body),{status:reply.status,headers:{'content-type':'application/json'}})};
const project={id:'p1',concurrency_version:7,execution_allowed:true};
const base={w:{version:1,projects:[project],environment:'production',approval_connection:{native_submit:{by_type:{extension:{available:true}}}}},s:{mode:'lark',user:{id:'u1'}},busy:false};
const root=createRoot(document.getElementById('root'));
let item,onRefresh=()=>{};
const render=(over={})=>act(async()=>root.render(React.createElement(mod.NativeApprovalControls,{c:{...base,...over,refresh:async()=>{onRefresh()}},kind:'extension',item,canSubmit:true})));
const btn=a=>document.querySelector(`button[data-action="${a}"]`);
const notCreated={id:'r1',project_id:'p1',status:'draft',native_binding:{status:'not_created',creation_outcome:'not_created',not_created_proof:'documented_api_rejection',creation_rejection:{http_status:400,api_code:1390001,uuid:'k'},payload:{uuid:'k',open_id:'u1'}}};
const submitted={id:'r1',project_id:'p1',status:'pending',native_binding:{status:'submitted',attempted:true,payload:{open_id:'u1'}}};
const click=b=>act(async()=>{b.focus();b.click()});
const settle=async()=>act(async()=>{await new Promise(r=>setTimeout(r,0))});

// Poll: button is blurred while disabled/busy; focus returns to the same button.
item=submitted;reply={status:200,body:{}};await render();
let release;gate=new Promise(r=>{release=r});
duringRequest=()=>document.activeElement.blur();
await click(btn('poll'));duringRequest=null;
assert.equal(document.querySelector('section').getAttribute('aria-busy'),'true');
assert.ok(document.querySelector('[role=status]').textContent.includes('正在處理'),'busy stays in live status');
assert.equal(btn('poll').disabled,true);
gate=null;await act(async()=>{release();await new Promise(r=>setTimeout(r,0))});
assert.equal(document.activeElement,btn('poll'),'poll restores focus');
assert.ok(document.querySelector('[role=status]').textContent.includes('已查回'));
assert.equal(document.querySelector('[role=alert]'),null,'success is not an alert');

// 503 / 409 recoverable failures are announced via role=alert, keeping the refresh.
let refreshed=0;onRefresh=()=>{refreshed++};
for(const status of [503,409]){
  reply={status,body:{detail:`recoverable ${status}`}};
  await click(btn('poll'));
  assert.equal(document.querySelector('[role=alert]').textContent,`recoverable ${status}`);
  assert.equal(document.querySelector('[role=status]').textContent,'');
  assert.equal(document.activeElement,btn('poll'));
}
assert.equal(refreshed,2);
reply={status:200,body:{}};await click(btn('poll'));
assert.equal(document.querySelector('[role=alert]'),null,'alert clears after success');

// Declined confirm keeps/returns focus on the trigger.
const confirms=[];window.confirm=()=>confirms.shift();
item={...submitted,native_binding:{...submitted.native_binding}};await render();
confirms.push(false);await click(btn('cancel'));
assert.equal(document.activeElement,btn('cancel'));

// Declined confirm after focus moved away must not leave restoration intent: a later render, even
// one that unmounts the old control, cannot steal focus back from the unrelated element.
const outside=document.createElement('input');document.body.append(outside);
for(const [action,exit] of [['cancel',()=>outside.focus()],['cancel',()=>document.activeElement.blur()]]){
  window.confirm=()=>{exit();return false};
  await click(btn(action));
  const parked=document.activeElement;
  await render({busy:true});await render();
  assert.equal(document.activeElement,parked,'declined confirm must not steal focus on later renders');
  outside.focus();
}
// Focus leaving the section clears stale restoration state even if the control later unmounts.
window.confirm=()=>true;
let hold;gate=new Promise(r=>{hold=r});
duringRequest=()=>outside.focus();
await click(btn('cancel'));duringRequest=null;
item={id:'r1',project_id:'p1',status:'canceled'};
gate=null;await act(async()=>{hold();await new Promise(r=>setTimeout(r,0))});
assert.equal(document.activeElement,outside,'focus that left the section stays outside');
// Later focus loss (outside element blurs) must not resurrect the stale control and pull focus back in.
document.activeElement.blur();await render();
assert.equal(document.activeElement,document.body,'stale restoration must not steal focus after it left the section');
// onBlur alone (no render while focus is outside) must drop the stale target before the control unmounts.
item={...submitted,native_binding:{...submitted.native_binding}};await render();
btn('cancel').focus();outside.focus();document.activeElement.blur();
item={id:'r1',project_id:'p1',status:'canceled'};await render();
assert.equal(document.activeElement,document.body,'onBlur leaving the section clears stale restoration');
outside.remove();window.confirm=()=>confirms.shift();
item={...submitted,native_binding:{...submitted.native_binding}};await render();

// Abandon unmounts the focused control: focus must land on a live element, not <body>.
item=notCreated;await render();
assert.ok(btn('submit')&&btn('abandon'),'recovery actions available to original applicant');
const done={id:'r1',project_id:'p1',status:'canceled'};
onRefresh=()=>{item=done;root.render(React.createElement(mod.NativeApprovalControls,{c:{...base,refresh:async()=>{}},kind:'extension',item,canSubmit:true}))};
confirms.push(true);await click(btn('abandon'));await settle();
assert.equal(btn('abandon'),null);
assert.equal(document.activeElement,document.querySelector('h3'),'focus falls back to heading');
assert.equal(document.querySelector('h3').getAttribute('tabindex'),'-1');

// Availability: closed connection disables submit, non-applicant gets no abandon, unknown revoke is poll-only.
item=notCreated;onRefresh=()=>{};
await render({w:{...base.w,approval_connection:{native_submit:{by_type:{extension:{available:false}}}}}});
assert.equal(btn('submit').disabled,true);
await render({s:{mode:'lark',user:{id:'other'}}});
assert.equal(btn('abandon'),null);
item={id:'r1',project_id:'p1',status:'pending',native_binding:{status:'outcome_unknown',attempted:true,cancel_attempted:true,payload:{open_id:'u1'}}};
await render();
assert.deepEqual([...document.querySelectorAll('button')].map(b=>b.dataset.action),['poll']);
await render({busy:true});
assert.equal(btn('poll').disabled,true);
console.log('native approval a11y checks passed');
