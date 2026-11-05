import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink,readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const source=process.env.YX_FE1_SOURCE||import.meta.dirname;
const b=await build({stdin:{contents:"export {default as Assigned} from './src/AssignedSopTaskPage';",resolveDir:source},bundle:true,write:false,format:'esm',platform:'node',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const file=new URL('./.fe1-owners.mjs',import.meta.url);await writeFile(file,b.outputFiles[0].text);const m=await import(file.href);await unlink(file);
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});for(const key of ['window','document','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});globalThis.IS_REACT_ACT_ENVIRONMENT=true;globalThis.getComputedStyle=dom.window.getComputedStyle;globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);HTMLElement.prototype.scrollIntoView=()=>{};
const example=JSON.parse(await readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url)));let fail=true,reads=0;
globalThis.fetch=async url=>{reads++;return new Response(JSON.stringify(url.endsWith('/sop-assignees')?example.assignees:fail?{code:'temporary',detail:'暫時失敗'}:example.sop_tasks),{status:fail&&!url.endsWith('/sop-assignees')?500:200})};
const c={s:{workspace_id:'test',user:{id:'u',active:true,role:'manager'}},route:{project:'p1',task:'missing'},go(){}};
const root=createRoot(document.getElementById('root'));const render=node=>act(async()=>{root.render(node);await new Promise(r=>setTimeout(r,0))});
try{
 await render(React.createElement(m.Assigned,{c}));assert.match(document.body.textContent,/重試/);assert.equal(reads,2);
 await render(null);fail=false;await render(React.createElement(m.Assigned,{c}));assert.equal(reads,4,'reopening after a failure starts a fresh owner');assert.match(document.body.textContent,/資料時間/);
 await render(null);fail=true;await render(React.createElement(m.Assigned,{c}));fail=false;
 await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent==='重試').click();await new Promise(r=>setTimeout(r,0))});assert.doesNotMatch(document.body.textContent,/重試|暫時失敗/);assert.match(document.body.textContent,/資料時間/);
 console.log('PASS Assigned SOP per-open reads: 2 then 2; explicit retry clears failure; source timestamp visible');
}finally{await render(null);await act(async()=>root.unmount());dom.window.close()}
