// Render the real AuditTrail: audit rows/page/error from project A must never appear under project B (pending, 503, 404, success, late A response).
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const k of ['window','document','location','HTMLElement','Event'])Object.defineProperty(globalThis,k,{value:dom.window[k],configurable:true,writable:true});
const React=(await import('react')).default,{act}=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['src/AuditTrail.tsx'],outdir:'.',bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external'});
const dir=new URL('./.audit-bundle/',import.meta.url);await fs.mkdir(dir,{recursive:true});
let AuditTrail;
try{await fs.writeFile(new URL('AuditTrail.js',dir),bundle.outputFiles[0].text);({AuditTrail}=await import(new URL('AuditTrail.js',dir).href))}finally{await fs.rm(dir,{recursive:true,force:true})}
globalThis.IS_REACT_ACT_ENVIRONMENT=true;

// Controllable fetch: each call is recorded and settled by the test, in any order.
let calls=[];
globalThis.fetch=(url,init)=>new Promise(resolve=>{
 const call={url:String(url),pid:new URL(String(url),'http://x').searchParams.get('project_id'),offset:new URL(String(url),'http://x').searchParams.get('offset'),
  reply:(status,body)=>resolve({ok:status<400,status,text:async()=>JSON.stringify(body)}),aborted:false};
 // Deliberately allow replies after abort to exercise the component's stale-response guard.
 init?.signal?.addEventListener('abort',()=>{call.aborted=true});
 calls.push(call)});
const last=pid=>calls.filter(c=>c.pid===pid).at(-1);
const w={version:1,users:[],events:[{id:'E1',project_id:'A',message:'LEGACY_A',at:'t'},{id:'E2',project_id:'B',message:'LEGACY_B',at:'t'}]};
const P=id=>({id,code:id});
const root=createRoot(document.getElementById('root'));
const text=()=>document.getElementById('root').textContent;
const settle=async(call,status,body)=>act(async()=>{call.reply(status,body);await new Promise(r=>setTimeout(r,0))});
const rowsOf=(prefix,n,total)=>({items:Array.from({length:n},(_,i)=>({id:prefix+i,message:`${prefix}_${i}`,created_at:'t'})),total});
const noA=()=>assert.ok(!/AUDIT_A|LEGACY_A/.test(text()),'project A audit leaked: '+text());

// keyed=false is the strongest check: same component instance receives a new project prop (no remount, no effect-clear head start).
for(const keyed of [false,true]){
 const show=async pid=>act(async()=>root.render(React.createElement(AuditTrail,{key:keyed?pid:undefined,w,p:P(pid)})));
 for(const mode of ['pending','503','404','success','late-A']){
  calls=[];await act(async()=>root.render(null));
  await show('A');
  await settle(last('A'),200,rowsOf('AUDIT_A',30,60));
  assert.ok(text().includes('AUDIT_A_0'),'A renders its own rows');
  // go to A page 2 so a leaked page would produce offset=30 for B
  await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent==='下一頁').click()});
  assert.equal(last('A').offset,'30');
  const aPage2=last('A');
  if(mode!=='late-A')await settle(aPage2,200,rowsOf('AUDIT_A2',5,60));
  await show('B');
  noA();assert.ok(!text().includes('AUDIT_A2'));
  assert.equal(last('B').offset,'0','page resets to first on project switch');
  assert.ok(!text().includes('共 60 筆'),'A total not shown under B');
  if(mode==='pending'){noA();continue}
  if(mode==='503'){await settle(last('B'),503,{detail:'B failed'});noA();assert.ok(text().includes('B failed'));assert.ok(!text().includes('AUDIT_A'))}
  if(mode==='404'){await settle(last('B'),404,{detail:'nf'});noA();assert.ok(text().includes('LEGACY_B'));assert.ok(!text().includes('LEGACY_A'))}
  if(mode==='success'){await settle(last('B'),200,rowsOf('AUDIT_B',2,2));noA();assert.ok(text().includes('AUDIT_B_1'));assert.ok(text().includes('共 2 筆'))}
  if(mode==='late-A'){
   // A's still-pending request replies after B, even though its signal was aborted.
   assert.ok(aPage2.aborted);
   await settle(last('B'),200,rowsOf('AUDIT_B',1,1));
   await settle(aPage2,200,rowsOf('AUDIT_A_LATE',3,3));
   noA();assert.ok(!text().includes('AUDIT_A_LATE'));assert.ok(text().includes('AUDIT_B_0'));
  }
  // switching back to A must not reuse B's data either
  await show('A');assert.ok(!text().includes('AUDIT_B'),'B data leaked under A');
  assert.equal(last('A').offset,'0','returning to A also resets its page');
 }
}
// Request ordering: A->B->A quickly; only the latest request's reply is applied, older ones are aborted.
calls=[];await act(async()=>root.render(null));
const show2=async pid=>act(async()=>root.render(React.createElement(AuditTrail,{w,p:P(pid)})));
await show2('A');const a1=last('A');await show2('B');const b1=last('B');await show2('A');const a2=last('A');
assert.ok(a1.aborted&&b1.aborted,'superseded requests are aborted');
await settle(a2,200,rowsOf('AUDIT_A_NEW',1,1));
await settle(b1,200,rowsOf('AUDIT_B_STALE',1,1));await settle(a1,200,rowsOf('AUDIT_A_OLD',1,1));
assert.ok(text().includes('AUDIT_A_NEW')&&!/B_STALE|A_OLD/.test(text()),'only latest request applied: '+text());
// Legacy fallback and errors belong to the request project, just like API rows.
for(const status of [404,503]){
 await act(async()=>root.render(null));calls=[];
 await show2('A');await settle(last('A'),status,{detail:'PRIVATE_A_ERROR'});
 assert.ok(text().includes(status===404?'LEGACY_A':'PRIVATE_A_ERROR'));
 await show2('B');
 assert.ok(!/LEGACY_A|PRIVATE_A_ERROR|舊版活動紀錄/.test(text()),'A fallback/error leaked under B');
 await settle(last('B'),200,rowsOf('AUDIT_B',1,1));
 assert.ok(text().includes('AUDIT_B_0'));
}
// A version refresh can shrink a three-page result below the requested offset.
// Cover both a nonempty first page and an empty result, plus the legacy 404 fallback.
for(const mode of ['api-one','api-empty','legacy']){
 await act(async()=>root.render(null));calls=[];
 const largeEvents=Array.from({length:61},(_,i)=>({id:`E${i}`,project_id:'A',message:`LEGACY_LARGE_${i}`,at:'t'}));
 const showVersion=async(version,events)=>act(async()=>root.render(React.createElement(AuditTrail,{w:{...w,version,events},p:P('A')})));
 await showVersion(1,largeEvents);
 await settle(last('A'),mode==='legacy'?404:200,rowsOf('AUDIT_LARGE',30,61));
 for(const offset of ['30','60']){
  await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent==='下一頁').click()});
  assert.equal(last('A').offset,offset);
  await settle(last('A'),mode==='legacy'?404:200,rowsOf('AUDIT_LARGE',offset==='60'?1:30,61));
 }
 const total=mode==='api-empty'?0:1;
 await showVersion(2,[{id:'SURVIVOR',project_id:'A',message:'LEGACY_SURVIVOR',at:'t'}]);
 const refresh=last('A');assert.equal(refresh.offset,'60');
 assert.ok(!text().includes('共 61 筆'),'old count hidden while refresh is pending');
 await settle(refresh,mode==='legacy'?404:200,{items:[],total});
 const recovery=last('A');assert.notEqual(recovery,refresh,'out-of-range page must refetch');
 assert.equal(recovery.offset,'0','request offset resets to the remaining page');
 await settle(recovery,mode==='legacy'?404:200,rowsOf('AUDIT_SURVIVOR',total,total));
 assert.ok(text().includes(`共 ${total} 筆`),'count reflects refreshed total');
 assert.equal(document.querySelectorAll('article').length,total);
 if(total)assert.ok(text().includes(mode==='legacy'?'LEGACY_SURVIVOR':'AUDIT_SURVIVOR_0'));
 for(const button of document.querySelectorAll('button'))assert.ok(button.disabled,'single-page result disables navigation');
}
console.log('audit trail project switch isolation and shrinking totals: ok');
await act(async()=>root.unmount());
dom.window.close();
