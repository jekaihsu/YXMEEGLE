// Native approval actions must send the owning project's CAS version, never the workspace version.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({entryPoints:['src/NativeApprovalControls.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.native-approval-test-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let mod;try{mod=await import(bundlePath.href)}finally{await fs.unlink(bundlePath)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','location','history','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const project={id:'p1',concurrency_version:7,execution_allowed:true};
const other={id:'p2',concurrency_version:3,execution_allowed:true};
let refreshed=0;const requests=[];let reply={status:200,body:{}};
globalThis.fetch=async(url,init)=>{requests.push({url,body:JSON.parse(init.body)});return new Response(JSON.stringify(reply.body),{status:reply.status,headers:{'content-type':'application/json'}})};
const c={w:{version:99,projects:[other,project],environment:'production',approval_connection:{native_submit:{by_type:{extension:{available:true}}}}},s:{mode:'lark',user:{id:'u1'}},busy:false,refresh:async()=>{refreshed++}};
const root=createRoot(document.getElementById('root'));
await act(async()=>root.render(React.createElement(mod.NativeApprovalControls,{c,kind:'extension',item:{id:'r1',project_id:'p1',status:'draft'},canSubmit:true})));
const click=async()=>{await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent.includes('核對送審設定')).click()})};
await click();
assert.equal(requests.length,1);
assert.equal(requests[0].url,'/api/native-approvals/extension/r1/prepare');
assert.deepEqual(requests[0].body,{project_version:7});
// A stale-version rejection refreshes the workspace and surfaces the server message.
reply={status:409,body:{detail:'此案件已被更新，請核對最新內容後重試'}};
await click();
assert.equal(refreshed,2);
assert.ok(document.body.textContent.includes('此案件已被更新'));
console.log('native approval project-version checks passed');
