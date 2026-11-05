// Exercise real api() boundaries with a local transport that deliberately ignores abort.
import assert from 'node:assert/strict';
import {build} from 'esbuild';
const {outputFiles:[out]}=await build({stdin:{contents:"export {api,ApiError,getPendingMutations} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm'});
const {api,ApiError,getPendingMutations}=await import('data:text/javascript;base64,'+Buffer.from(out.text).toString('base64'));
globalThis.window={dispatchEvent(){}};
const timers=new Map();let nextTimer=0;
const set=globalThis.setTimeout,clear=globalThis.clearTimeout;
globalThis.setTimeout=(callback,ms)=>{const id=++nextTimer;timers.set(id,{callback,ms});return id};
globalThis.clearTimeout=id=>timers.delete(id);
try{
 for(const stage of ['headers','body']){
  let calls=0,networkSignal;
  globalThis.fetch=(_url,init)=>{calls++;networkSignal=init.signal;return stage==='headers'?new Promise(()=>{}):Promise.resolve({status:200,ok:true,text:()=>new Promise(()=>{})})};
  const controller=new AbortController();
  const read=api('/local',{signal:controller.signal,timeoutMs:0});
  const rejected=assert.rejects(read,error=>error.name==='AbortError');
  await Promise.resolve();controller.abort();await rejected;
  assert.equal(calls,1);assert.ok(networkSignal.aborted);assert.equal(timers.size,0);
 }
 for(const stage of ['headers','body']){
  let signal;
  globalThis.fetch=(_url,init)=>{signal=init.signal;return stage==='headers'?new Promise(()=>{}):Promise.resolve({status:200,ok:true,text:()=>new Promise(()=>{})})};
  const read=api('/local');
  const rejected=assert.rejects(read,error=>error instanceof ApiError&&error.status===408&&error.code==='client_timeout');
  await Promise.resolve();assert.equal(timers.size,1);
  const timer=[...timers.values()][0];assert.equal(timer.ms,30000);timer.callback();await rejected;
  assert.ok(signal.aborted);assert.equal(timers.size,0);
 }
 let calls=0;
 globalThis.fetch=async()=>{calls++;return new Response('{"ok":true}')};
 for(const init of [{timeoutMs:0},{timeoutMs:4000},undefined]){
  assert.deepEqual(await api('/local',init),{ok:true});assert.equal(timers.size,0);
 }
 const controller=new AbortController();controller.abort();
 const before=calls;
 await assert.rejects(api('/local',{signal:controller.signal}),e=>e.name==='AbortError');
 await assert.rejects(api('/local',{method:'POST',signal:controller.signal}),e=>e.name==='AbortError');
 assert.equal(calls,before,'already cancelled callers do not send network requests');
 assert.equal(getPendingMutations(),0);assert.equal(timers.size,0);
 // Errors and mutations stay single-attempt; callers own their retry/recovery policy.
 globalThis.fetch=async()=>{calls++;return new Response('{"detail":"warming"}',{status:503})};
 const beforeError=calls;
 await assert.rejects(api('/local'),e=>e.status===503);
 assert.equal(calls,beforeError+1);
 globalThis.fetch=async(_url,init)=>{assert.equal(init.signal,undefined);assert.equal(timers.size,0);return new Response('{"ok":true}')};
 await api('/local',{method:'POST',body:'{}'});
 assert.equal(getPendingMutations(),0);
 console.log('API cancellation: bounded headers/body, default deadline, opt-out, pre-abort, mutation and retry contracts passed');
}finally{globalThis.setTimeout=set;globalThis.clearTimeout=clear}
