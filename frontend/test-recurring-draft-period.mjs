// Render the real Operations Routines call site: the same recurring record in a new period must not inherit the old draft.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const k of ['window','document','sessionStorage','location','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','Event','FormData'])Object.defineProperty(globalThis,k,{value:dom.window[k],configurable:true,writable:true});
const React=(await import('react')).default,{act}=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['src/Operations.tsx','src/FormDraft.tsx','src/ProjectRoleAssignment.tsx'],outdir:'.',bundle:true,splitting:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const dir=new URL('./.recurring-bundle/',import.meta.url);await fs.mkdir(dir,{recursive:true});
let Routines,DraftNamespace,ProjectRoleAssignment;
try{
 for(const f of bundle.outputFiles)await fs.writeFile(new URL(f.path.split('/').pop(),dir),f.text);
 const names=bundle.outputFiles.map(f=>f.path.split('/').pop());
 ({Routines}=await import(new URL(names.find(n=>n==='Operations.js'),dir).href));
 ({ProjectRoleAssignment}=await import(new URL('ProjectRoleAssignment.js',dir).href));
 ({DraftNamespace}=await import(new URL(names.find(n=>n==='FormDraft.js'),dir).href));
}finally{await fs.rm(dir,{recursive:true,force:true})}
globalThis.IS_REACT_ACT_ENVIRONMENT=true;

const rec=(id,due,extra={})=>({id,project_id:'P1',kind:'weekly_review',owner_id:'u1',status:'active',due_date:due,history:[],title:'週檢討',...extra});
const ctx=recurring=>({busy:false,run:async()=>undefined,refresh:async()=>{},s:{user:{id:'u1',role:'manager'}},
 w:{users:[{id:'u1',name:'U'}],projects:[{id:'P1',code:'C1',pm_id:'u1',supervisor_id:'u1'}],recurring,jobs:[]}});
const root=createRoot(document.getElementById('root'));
const show=async recurring=>act(async()=>root.render(React.createElement(DraftNamespace.Provider,{value:'u1:w1'},React.createElement(Routines,{c:ctx(recurring)}))));
const rows=()=>[...document.querySelectorAll('tbody tr')];
const area=i=>rows()[i].querySelector('textarea,input[name="evidence"]');
const type=async(i,v)=>act(async()=>{const el=area(i);Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'value').set.call(el,v);el.dispatchEvent(new dom.window.Event('input',{bubbles:true}))});
const keys=()=>Object.keys(sessionStorage).filter(k=>k.startsWith('yx:draft:v2:'));
const restore=i=>[...rows()[i].querySelectorAll('button')].find(b=>b.textContent==='恢復暫存文字');

await show([rec('R1','2026-10-05')]);
await type(0,'PERIOD_ONE_NOTES');
assert.equal(keys().length,1);
assert.ok(keys()[0].includes(encodeURIComponent('recurring:R1:weekly_review:2026-10-05')),'key carries the period due date');

// Same record, next period (due date advanced after an accepted completion): old draft is not offered.
await show([rec('R1','2026-10-12',{history:[{id:'H1',status:'accepted',evidence:'x'}]})]);
assert.equal(restore(0),undefined,'next period must not offer the previous period draft');
assert.equal(area(0).value,'','next period must reset the live input without a parent remount');
await type(0,'PERIOD_TWO_NOTES');
assert.equal(keys().length,2);

// Returning to the original period still finds its own draft; a different record in the same period is isolated.
await act(async()=>root.render(null));
await show([rec('R1','2026-10-05'),rec('R2','2026-10-05')]);
assert.ok(restore(0),'same record+period restores');
assert.equal(restore(1),undefined,'other record in same period is isolated');
console.log('recurring draft period identity: ok');

// A real block-bodied call site must return its save result so only successful saves clear the draft.
sessionStorage.clear();
let saved;
const c=ctx([]);c.run=async()=>saved;
const p={id:'P1',pm_id:'u1',admin_id:'u1',sales_id:'u1',quotation_id:'u1',assistant_id:'u1',supervisor_id:'u1',issuer_ids:[]};
const n={id:'N1',owner_id:'u1',supervisor_id:'u1',reviewers:[]};
await act(async()=>root.render(React.createElement(DraftNamespace.Provider,{value:'u1:w1'},React.createElement(ProjectRoleAssignment,{c,p,n}))));
const select=document.querySelector('select');
await act(async()=>select.dispatchEvent(new dom.window.Event('change',{bubbles:true})));
assert.equal(keys().length,1);
await act(async()=>document.querySelector('form').requestSubmit());
assert.equal(keys().length,1,'failed role save retains the draft');
saved={version:2};
await act(async()=>document.querySelector('form').requestSubmit());
assert.equal(keys().length,0,'successful role save clears its draft');
console.log('real action form save cleanup: ok');
