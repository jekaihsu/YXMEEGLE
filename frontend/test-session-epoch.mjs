// Exercise real App closures and React state; expose context only in the test bundle.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build,transform} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({entryPoints:['src/App.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'},plugins:[{name:'observe-app-context',setup(b){b.onLoad({filter:/\/App\.tsx$/},async({path})=>({contents:(await fs.readFile(path,'utf8')).replace(' const overdue=w?', ' window.epochContext={w,s,busy,error,completionMoment,run,upload,refresh,logout};\n const overdue=w?'),loader:'tsx'}))}}]});
// File URL keeps external React imports resolved from this directory.
const bundlePath=new URL('./.epoch-test-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let App;try{App=(await import(bundlePath.href)).default}finally{await fs.unlink(bundlePath)}
const fixture=await fs.readFile('../docs/review3/reproductions/browser/fixture.tsx','utf8');
const dataSource=fixture.slice(fixture.indexOf('const a:any='),fixture.indexOf('let actor=a;'));
const {code}=await transform(dataSource+'\nreturn {a,b,workspace};',{loader:'ts'});
const {a,b,workspace}=new Function(code)();
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}});
let checks=0;
async function scenario(kind,change,status=200){
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=projects'});
 for(const key of ['window','document','location','history','sessionStorage','FormData','Event'])globalThis[key]=dom.window[key];
 globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 let session={user:a,users:[a,b],mode:'lark',environment:'production',workspace_id:'workspace-A',auth_configured:true};
 let current={...workspace,version:10};let release;let calls=0;
 globalThis.fetch=async(url)=>{
  if(url==='/api/session')return json(session);
  if(url==='/api/workspace')return json(current);
  if(url==='/api/logout')return json({});
  if(url==='/api/actions'||url==='/api/files'){calls++;return new Promise(resolve=>{release=resolve})}
  throw Error('Unexpected endpoint '+url);
 };
 const root=createRoot(document.getElementById('root'));
 const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(resolve=>setTimeout(resolve,0))});
 await flush(()=>root.render(React.createElement(App)));
 let pending;await flush(()=>{pending=kind==='run'?window.epochContext.run('task_start',{}, {project_id:'pA',node_id:'nA'}):window.epochContext.upload(new FormData())});
 assert.equal(calls,1);
 const oldRelease=release;
 if(change){
  if(change==='logout')await flush(()=>window.epochContext.logout());
  if(change==='expiry')await flush(()=>window.dispatchEvent(new Event('yx:session-expired')));
  if(change==='actor')session={...session,user:b};
  if(change==='workspace')session={...session,workspace_id:'workspace-B'};
  if(change==='environment')session={...session,environment:'trial'};
  if(change==='mode')session={...session,mode:'demo'};
  if(change==='recovery')session={...session,access_mode:'recovery'};
  current={...workspace,workspace_id:session.workspace_id,environment:session.environment,version:1,projects:[]};
  await flush(()=>window.epochContext.refresh());
  if(change==='recovery'){assert.equal(window.epochContext.w,undefined);session={...session,access_mode:undefined};await flush(()=>window.epochContext.refresh())}
  assert.equal(window.epochContext.w.version,1,'new epoch accepts lower version');
  assert.equal(window.epochContext.w.projects.length,0);
  let newer;await flush(()=>{newer=window.epochContext.upload(new FormData())});
  const newRelease=release;
  let result;await flush(async()=>{oldRelease(json(status===200?{...workspace,version:99,projects:workspace.projects.map(p=>({...p,nodes:p.nodes.map(n=>({...n,status:'completed',tasks:n.tasks.map(t=>({...t,status:'completed'}))}))}))}:{detail:'OLD_ERROR'},status));result=await pending});
  assert.equal(result,kind==='upload'?false:undefined,'stale result is not returned to callers');
  assert.equal(window.epochContext.w.projects.length,0,'old data stays cleared');
  assert.equal(window.epochContext.s.user.id,session.user.id,'stale 401 cannot expire new session');
  assert.equal(window.epochContext.error,'');
  assert.equal(window.epochContext.completionMoment,null);
  assert.equal(window.epochContext.busy,true,'old finally cannot unlock newer mutation');
  assert.ok(!document.body.textContent.includes('已儲存，工作台已更新'));
  assert.ok(!document.body.textContent.includes('檔案已上傳'));
  await flush(async()=>{newRelease(json({...current,version:2}));await newer});
  assert.equal(window.epochContext.w.version,2);
 }else{
  await flush(async()=>{oldRelease(json({...workspace,version:11}));await pending});
  assert.equal(window.epochContext.w.version,11);
  assert.ok(document.body.textContent.includes(kind==='run'?'已儲存，工作台已更新':'檔案已上傳'));
  current={...workspace,version:9};await flush(()=>window.epochContext.refresh());
  if(change==='recovery'){assert.equal(window.epochContext.w,undefined);session={...session,access_mode:undefined};await flush(()=>window.epochContext.refresh())}
  assert.equal(window.epochContext.w.version,11,'same epoch rejects older version');
 }
 assert.equal(window.epochContext.busy,false);
 await flush(()=>root.unmount());dom.window.close();checks++;
}
for(const kind of ['run','upload']){
 for(const change of ['actor','workspace','environment','mode','recovery','logout','expiry'])await scenario(kind,change);
 for(const status of [401,409,500])await scenario(kind,'actor',status);
 await scenario(kind,null);
}
console.log(`Session epoch: ${checks} App regression scenarios passed`);
