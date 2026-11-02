import assert from 'node:assert/strict';
import {build} from 'esbuild';import {writeFile,unlink} from 'node:fs/promises';import {fileURLToPath} from 'node:url';
import React,{act} from 'react';import {createRoot} from 'react-dom/client';import {JSDOM} from 'jsdom';
const dir=fileURLToPath(new URL('../../',import.meta.url));
const b=await build({stdin:{contents:"export {useReport} from './src/reports/useReport';export {invalidateSessionEpoch} from './src/api';export {default as ReportsPage} from './src/reports/ReportsPage';",resolveDir:dir},bundle:true,write:false,platform:'node',format:'esm',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const tmp=new URL('../../.reports-loading.mjs',import.meta.url);await writeFile(tmp,b.outputFiles[0].text);let m;try{m=await import(tmp.href)}finally{await unlink(tmp)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});for(const k of ['window','document','location','localStorage'])globalThis[k]=dom.window[k];globalThis.IS_REACT_ACT_ENVIRONMENT=true;dom.window.HTMLElement.prototype.scrollIntoView=()=>{};
const requests=[],states={};globalThis.fetch=(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}));
const root=createRoot(document.getElementById('root')),flush=fn=>act(async()=>{fn?.();await new Promise(setImmediate)});
const render=el=>flush(()=>root.render(el));const reply=(i,data,status=200)=>flush(()=>requests[i].resolve(new Response(JSON.stringify(data),{status})));
function Reader({id,pm}){const state=m.useReport('sales',{pm});states[id]=state;return React.createElement('span',null,state.loading?'loading':state.error??state.data?.value)}
try{
 const reader=(id,pm)=>React.createElement(Reader,{key:id,id,pm});
 await render([reader('a','same'),reader('b','same')]);assert.equal(requests.length,2,'independent mounted report opens have independent owners');
 await render(reader('b','same'));assert.equal(requests[0].options.signal.aborted,true);assert.equal(requests[1].options.signal.aborted,false);await reply(0,{value:'discarded'});await reply(1,{value:'retained'});assert.equal(document.body.textContent,'retained');
 await render(reader('b','other'));assert.equal(requests.length,3);await reply(2,{value:'other'});await render(reader('b','same'));assert.equal(requests.length,3,'query return inside one open reuses its snapshot');assert.equal(document.body.textContent,'retained');
 await flush(()=>states.b.retry());assert.equal(requests.length,4);await reply(3,{detail:'offline'},503);assert.equal(states.b.previous.value,'retained');assert.equal(states.b.error,'offline');
 await flush(()=>states.b.retry());await reply(4,{value:'recovered'});assert.equal(document.body.textContent,'recovered');
 await render(reader('b','warming'));const warming=requests.length-1;await reply(warming,{warming:true},503);assert.equal(states.b.warming,true);await flush(()=>{});assert.equal(requests.length,warming+1,'warming never schedules a retry');await flush(()=>states.b.retry());assert.equal(requests.length,warming+2);await reply(warming+1,{value:'warmed'});
 await flush(()=>m.invalidateSessionEpoch());const next=requests.length-1;assert.equal(states.b.data,undefined);await reply(next,{value:'new session'});assert.equal(document.body.textContent,'new session');
 await render(null);const start=requests.length;
 await render(React.createElement(m.ReportsPage,{tab:'sales'}));assert.deepEqual(requests.slice(start).map(r=>r.url.split('?')[0]),['/api/reports/sales']);
 await render(React.createElement(m.ReportsPage,{tab:'sources'}));assert.equal(requests.at(-1).url.split('?')[0],'/api/reports/sources');
 console.log('Report opens: independent owners, query return reuse, cancellation, retry retention, manual warming retry, epoch isolation and lazy tabs passed');
}finally{await flush(()=>root.unmount());await flush(()=>requests.forEach(r=>r.resolve(new Response('{}'))));dom.window.close()}
