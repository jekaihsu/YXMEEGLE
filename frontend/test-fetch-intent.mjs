import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {mock} from 'node:test';
const bundle=await build({stdin:{contents:"export * from './src/pageData'; export {api,invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm'});
const {createPageData,normalizeQuery,api,invalidateSessionEpoch}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
globalThis.window=new EventTarget();globalThis.document=new EventTarget();
const value=data=>({data,snapshotId:null,fetchedAt:null,verifiedAt:null,changedAt:null,completeness:'complete',localRevision:null,empty:false,stale:false});
const scope={workspace:'a',identityFingerprint:'actor+grants',openId:'case:1'};
const resource={endpoint:'/api/a',query:{b:2,a:'1'}};
const owner=createPageData(scope);
assert.equal(normalizeQuery({a:'1',b:2}),normalizeQuery(resource.query));
assert.notEqual(normalizeQuery({a:1}),normalizeQuery({a:'1'}));
let calls=0;const load=async()=>value(++calls);
const first=owner.read(resource,{reason:'initial_open'},load);
assert.equal(first,owner.read({...resource,query:{a:'1',b:2}},{reason:'initial_open'},load));
await first;assert.equal(calls,1);
mock.timers.enable({apis:['Date','setTimeout','setInterval'],now:Date.parse('2026-11-02T15:59:00Z')});
try{
 for(let i=0;i<1440;i++){
  mock.timers.tick(60000);
  for(const name of ['focus','visibilitychange','online','pointerdown','keydown','wheel']){window.dispatchEvent(new Event(name));document.dispatchEvent(new Event(name))}
  await owner.read(resource,{reason:'initial_open'},load);
 }
 assert.equal(calls,1,'24h, midnight, events and repeated readers stay pinned');
}finally{mock.timers.reset()}
await owner.read(resource,{reason:'explicit_refresh',id:'click-1'},load);assert.equal(calls,2);
await owner.read(resource,{reason:'explicit_refresh',id:'click-1'},load);assert.equal(calls,2);
const other={endpoint:'/api/b'};await owner.read(other,{reason:'user_query_change'},load);
await owner.ownWriteCommitted('write-1',[resource,resource,{endpoint:'/api/unopened'}]);assert.equal(calls,4);
await owner.ownWriteCommitted('write-1',[resource]);assert.equal(calls,4);
assert.equal(owner.state(other).value.data,3,'unrelated resources stay pinned');
owner.seed(resource,value(99),'write-2',load);
await owner.ownWriteCommitted('write-2',[resource]);assert.equal(calls,4,'authoritative write response avoids reread');
owner.unknownOutcome(resource,'ambiguous-1');assert.deepEqual(owner.state(resource),{kind:'UnknownOutcome',requestId:'ambiguous-1'});
assert.equal(calls,4);
await assert.rejects(owner.read(resource,{reason:'initial_open'},load),/ambiguous-1/);
await owner.read(resource,{reason:'own_write_outcome_unknown_recovery',id:'ambiguous-1:user-click'},load);assert.equal(calls,5);
await owner.read(resource,{reason:'own_write_outcome_unknown_recovery',id:'ambiguous-1:user-click'},load);assert.equal(calls,5);
await assert.rejects(owner.read(resource,{reason:'focus'},load),/Invalid fetch intent/);
await assert.rejects(owner.read(resource,{reason:'explicit_refresh'},load),/Invalid fetch intent/);
for(const field of ['workspace','identityFingerprint','openId']){
 const next=createPageData({...scope,[field]:'different'});assert.notEqual(next.key(resource),owner.key(resource));next.close();
}
let release,signal;const blocked={endpoint:'/blocked'};
const pending=owner.read(blocked,{reason:'initial_open'},async s=>{signal=s;return new Promise(resolve=>release=resolve)});
const aborted=assert.rejects(pending,e=>e.name==='AbortError');await Promise.resolve();
owner.seed(blocked,value('write-wins'),'w',load);await aborted;assert(signal.aborted);release(value('old-read'));await Promise.resolve();assert.equal(owner.state(blocked).value.data,'write-wins');
let fail;const failure=owner.read({endpoint:'/failure'},{reason:'initial_open'},()=>new Promise((_,reject)=>fail=reject));
const closedFailure=assert.rejects(failure,e=>e.name==='AbortError');await Promise.resolve();owner.close();await closedFailure;fail(new Error('old failure'));
const next=createPageData({...scope,openId:'case:2'});assert.equal(next.state(blocked).kind,'Loading');
let sessionSignal;const sessionRead=next.read(resource,{reason:'initial_open'},s=>{sessionSignal=s;return new Promise(()=>{})});const sessionAbort=assert.rejects(sessionRead,e=>e.name==='AbortError');await Promise.resolve();invalidateSessionEpoch();await sessionAbort;assert(sessionSignal.aborted);
await assert.rejects(next.read(resource,{reason:'initial_open'},load),e=>e.name==='AbortError');
const broken=createPageData(scope);let failures=0;const bad=()=>{failures++;return Promise.reject(new Error('offline'))};
await assert.rejects(broken.read(resource,{reason:'initial_open'},bad));await assert.rejects(broken.read(resource,{reason:'initial_open'},bad));assert.equal(failures,1);
await assert.rejects(broken.read(other,{reason:'initial_open'},async()=>({...value([]),empty:true,completeness:'partial'})),/Empty requires/);broken.close();
let requests=[];globalThis.fetch=(url,init)=>new Promise(resolve=>requests.push({url,init,resolve}));
const ok=(data,etag)=>new Response(JSON.stringify(data),{headers:{ETag:etag}});
const a=api('/same',{etag:true,cacheScope:'scope-a'});requests.at(-1).resolve(ok({private:'a'},'"a"'));await a;
const b=api('/same',{etag:true,cacheScope:'scope-b'});assert(!requests.at(-1).init.headers.has('If-None-Match'));requests.at(-1).resolve(new Response(null,{status:304}));await assert.rejects(b);
let current=true;const old304=api('/same',{etag:true,cacheScope:'scope-a'},()=>current);current=false;requests.at(-1).resolve(new Response(null,{status:304}));await assert.rejects(old304,e=>e.name==='AbortError');
const epoch304=api('/same',{etag:true,cacheScope:'scope-a'});invalidateSessionEpoch();requests.at(-1).resolve(new Response(null,{status:304}));await assert.rejects(epoch304,e=>e.name==='AbortError');
console.log('Fetch intents: pinned 24h/events, single-flight, dependency writes, scope/epoch cancellation, unknown outcome, stale failures and 304 isolation passed');

const dependencies=createPageData(scope);const counts={a:0,b:0,c:0};
const resources=Object.keys(counts).map(name=>({endpoint:'/dependency/'+name}));
for(const [i,name] of Object.keys(counts).entries())await dependencies.read(resources[i],{reason:'initial_open'},async()=>value(++counts[name]));
await dependencies.ownWriteCommitted('affected-a-b',[resources[0],resources[1],resources[0]]);assert.deepEqual(counts,{a:2,b:2,c:1});dependencies.close();

const versions=createPageData(scope);
versions.seed(resource,{...value('new'),localRevision:3},'write-new',load);
versions.seed(resource,{...value('old'),localRevision:2},'write-old',load);
assert.equal(versions.state(resource).value.data,'new','older authoritative response cannot regress a numeric resource revision');versions.close();
