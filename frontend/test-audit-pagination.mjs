// Issue #49: render the real component with bounded, exact, and legacy audit totals.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const k of ['window','document','location','HTMLElement','Event'])Object.defineProperty(globalThis,k,{value:dom.window[k],configurable:true,writable:true});
const React=(await import('react')).default,{act}=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['src/AuditTrail.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external'});
const dir=await fs.mkdtemp(new URL('./.audit-pagination-',import.meta.url));
let AuditTrail;
try{
 await fs.writeFile(`${dir}/AuditTrail.mjs`,bundle.outputFiles[0].text);
 ({AuditTrail}=await import(`file://${dir}/AuditTrail.mjs`));
}finally{await fs.rm(dir,{recursive:true,force:true})}
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
let calls=[];
globalThis.fetch=url=>new Promise(resolve=>calls.push({url:String(url),reply:(status,body)=>resolve({ok:status<400,status,text:async()=>JSON.stringify(body)})}));
const root=createRoot(document.getElementById('root'));
const w={version:1,users:[],events:Array.from({length:31},(_,i)=>({id:`legacy-${i}`,project_id:'A',message:`legacy ${i}`}))};
const show=async()=>{calls=[];await act(async()=>root.render(null));await act(async()=>root.render(React.createElement(AuditTrail,{w,p:{id:'A'}})))};
const settle=async(status,body)=>act(async()=>{calls.at(-1).reply(status,body);await new Promise(r=>setTimeout(r,0))});
const text=()=>document.getElementById('root').textContent;
const next=()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='下一頁');
const page=(n,total,has_more)=>({items:Array.from({length:n},(_,i)=>({id:`row-${i}`,action:'task_update'})),total,...(has_more===undefined?{}:{has_more})});
try{
 await show();await settle(200,page(30,31,true));
 assert.ok(text().includes('至少 31 筆')&&!text().includes('共 31 筆'));
 assert.equal(next().disabled,false);
 await act(async()=>next().click());
 assert.equal(new URL(calls.at(-1).url,'http://localhost').searchParams.get('offset'),'30');
 await settle(200,page(30,61,true));
 assert.ok(text().includes('至少 61 筆'));assert.equal(next().disabled,false);
 await act(async()=>next().click());await settle(200,page(2,62,false));
 assert.ok(text().includes('共 62 筆')&&!text().includes('至少'));assert.equal(next().disabled,true);
 // has_more controls navigation even if the count alone would imply another page.
 await show();await settle(200,page(30,80,false));assert.equal(next().disabled,true);
 await show();await settle(200,page(0,0,false));assert.ok(text().includes('共 0 筆'));assert.equal(next().disabled,true);
 // Earlier APIs have exact totals but no has_more; retain their pagination contract.
 await show();await settle(200,page(30,31));assert.ok(text().includes('共 31 筆'));assert.equal(next().disabled,false);
 await act(async()=>next().click());await settle(200,page(1,31));assert.equal(next().disabled,true);
 await show();await settle(404,{detail:'not found'});assert.ok(text().includes('共 31 筆'));assert.equal(next().disabled,false);
 await act(async()=>next().click());await settle(404,{detail:'not found'});assert.equal(next().disabled,true);
 console.log('audit pagination: lower bounds, exact/empty totals, has_more navigation, older API and legacy fallback passed');
}finally{await act(async()=>root.unmount());dom.window.close()}
