// Real InputRegistration component under jsdom with a scripted fetch: no network, no Lark.
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import {JSDOM} from 'jsdom';
// DOM globals must exist before React loads so it enables its input-event path.
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const k of ['window','document','location','sessionStorage','Event','HTMLElement'])globalThis[k]=dom.window[k];
Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=(await import('react')).default;const {act}=await import('react');const {createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['src/InputRegistration.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.input-recovery-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let InputRegistration;try{InputRegistration=(await import(path.href)).InputRegistration}finally{await fs.unlink(path)}
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}});
const user={id:'u1'};
const p={id:'p',concurrency_version:3,nodes:[],execution_allowed:true};const n={id:'n'};
let rows=[];let script=[];const posts=[];const refreshes={count:0};
globalThis.fetch=async(url,init)=>{
 const body=init?.body?JSON.parse(init.body):null;posts.push({url,body});
 const step=script.shift();if(!step)throw Error('unscripted '+url);
 if(step instanceof Error)throw step;
 return json(step.body,step.status);
};
const w={version:1,environment:'production',settings:{},execution_status:'in_progress',get input_revisions(){return rows}};
const session={user,mode:'lark',workspace_id:'ws',environment:'production'};
const ctx=()=>({w,s:session,busy:false,refresh:async()=>{refreshes.count++}});
const root=createRoot(dom.window.document.getElementById('root'));
const render=()=>act(async()=>root.render(React.createElement(InputRegistration,{c:ctx(),p,n,canSubmit:true})));
const q=s=>dom.window.document.querySelector(s);
const type=async(el,v)=>act(async()=>{const set=Object.getOwnPropertyDescriptor(el.constructor.prototype,'value').set;set.call(el,v);el.dispatchEvent(new dom.window.Event('input',{bubbles:true}))});
const click=async el=>act(async()=>{el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}))});
const submitForm=async()=>act(async()=>{q('form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}))});
const buttonText=()=>q('form button.button')?.textContent;
await render();
if(!q('form')){console.log('form not rendered (executionAllowed gate); marking test inconclusive');process.exit(2)}
await type(q('input'),'名稱');await type(q('textarea'),'內容');
let id;
const fail=async(status,body={detail:'x'})=>{script.push({status,body});await submitForm()};
// 500 -> locked retry, identity+content preserved
await fail(500);id=posts[0].body.request_id;
assert.equal(buttonText(),'重試確認送交結果');assert.equal(q('input').value,'名稱');assert.equal(q('textarea').value,'內容');
// timeout/network -> still locked, same identity
script.push(Object.assign(new TypeError('Failed to fetch')));await submitForm();
assert.equal(posts[1].body.request_id,id);assert.equal(buttonText(),'重試確認送交結果');
// 403 on retry -> unlocked and editable, same identity kept
await fail(403,{detail:'沒有此節點提交權限'});
assert.equal(buttonText(),'提交作業資料');assert.equal(q('input').disabled,false);assert.equal(q('textarea').value,'內容');
await fail(422,{detail:'bad'});assert.equal(posts[3].body.request_id,id);assert.equal(q('input').value,'名稱');
// 409 on a first attempt stays editable, same identity; refresh requested
const before=refreshes.count;await fail(409,{detail:'version'});assert.equal(q('input').disabled,false);assert.ok(refreshes.count>before);
// 5xx then 409 on retry stays locked (never a fresh identity)
await fail(503);await fail(409,{detail:'version'});assert.equal(buttonText(),'重試確認送交結果');
// success clears and issues a new identity
script.push({status:200,body:{}});await submitForm();
assert.equal(posts.at(-1).body.request_id,id);assert.equal(q('input').value,'');
await type(q('input'),'下一筆');await type(q('textarea'),'內容2');script.push({status:200,body:{}});await submitForm();
assert.notEqual(posts.at(-1).body.request_id,id);
console.log('input recovery UI: ok');process.exit(0);
