// Mount the real FinancialApprovalRequests and switch case/user/workspace without remounting the parent.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const k of ['window','document','sessionStorage','HTMLElement','Event'])globalThis[k]=dom.window[k];
// react-dom must load after the DOM globals exist or it disables DOM event handling.
const React=(await import('react')).default,{act}=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['src/NativeApprovalControls.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.financial-draft-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let FinancialApprovalRequests;try{({FinancialApprovalRequests}=await import(bundlePath.href))}finally{await fs.unlink(bundlePath)}
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const project=id=>({id,pm_id:'u1',admin_id:'u1',supervisor_id:'u1',status:'active',execution_allowed:true,files:[],evidence:[{id:`${id}-ev`,name:`${id} evidence`,status:'accepted',storage:'remote'}],
 nodes:[{id:`${id}-pricing`,key:'pricing',name:`${id} pricing`,owner_id:'u1',collaborator_ids:[],tasks:[]}]});
const projects={A:project('case-A'),B:project('case-B')};
const ws=wid=>({workspace_id:wid,environment:'production',version:1,projects:Object.values(projects),financial_requests:[],approval_connection:{}});
const ctx=(uid,wid)=>({s:{user:{id:uid,can_business_override:true},mode:'lark',environment:'production',workspace_id:wid},w:ws(wid),busy:false,refresh:async()=>{}});
const root=createRoot(document.getElementById('root'));
const show=async(uid,wid,p)=>act(async()=>root.render(React.createElement(FinancialApprovalRequests,{c:ctx(uid,wid),p})));
const setValue=async(el,v)=>act(async()=>{
 const proto=el.tagName==='TEXTAREA'?dom.window.HTMLTextAreaElement.prototype:dom.window.HTMLSelectElement.prototype;
 Object.getOwnPropertyDescriptor(proto,'value').set.call(el,v);
 el.dispatchEvent(new dom.window.Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));
});
const reason=()=>document.querySelector('textarea');
const href=()=>[...document.querySelectorAll('a')].find(a=>a.textContent.includes('返回交付'))?.getAttribute('href');
const payables=()=>document.querySelectorAll('select')[2];
const box=()=>document.querySelector('fieldset input[type=checkbox]');

await show('u1','w1',projects.A);
await setValue(reason(),'ONLY_CASE_A_REASON');
await setValue(payables(),'all_settled');
await act(async()=>box().click());
assert.equal(box().checked,true);
assert.match(href(),/project=case-A&node=case-A-pricing/);

await show('u1','w1',projects.B);
assert.equal(reason().value,'','case-B must not show case-A reason');
assert.equal(payables().value,'unknown');
assert.equal(box().checked,false);
assert.match(href(),/project=case-B&node=case-B-pricing/);
assert.ok(!href().includes('case-A'));

await show('u1','w1',projects.A);
assert.equal(reason().value,'ONLY_CASE_A_REASON','case-A draft restored');
assert.equal(payables().value,'unknown','non-persisted state resets; reason restored from storage');

await show('u2','w1',projects.A);
assert.equal(reason().value,'','other user sees no residue');
await show('u1','w2',projects.A);
assert.equal(reason().value,'','other workspace sees no residue');
await setValue(reason(),'W2_REASON');
await show('u1','w1',projects.A);
assert.equal(reason().value,'ONLY_CASE_A_REASON');
console.log('financial draft scope: ok');
