// Verify ?perf=1 timing is opt-in: no globals, marks or logs when off; a full summary when on.
import assert from 'node:assert/strict';
import {build} from 'esbuild';
let n=0;
const load=async(search)=>{
 globalThis.location={search};globalThis.window={dispatchEvent(){}};
 const {outputFiles:[out]}=await build({stdin:{contents:"export * from './src/api';",resolveDir:process.cwd(),loader:'ts'},bundle:true,write:false,format:'esm'});
 return import('data:text/javascript;base64,'+Buffer.from(out.text+`\n//${n++}`).toString('base64'));
};
const logs=[];const log=console.log;console.log=(...a)=>logs.push(a);
const marks=()=>performance.getEntriesByType('mark').filter(m=>m.name.startsWith('yx:')).length;
globalThis.fetch=async()=>new Response('{"ok":"中"}',{status:200,headers:{'Server-Timing':'identity;dur=1.0, total;dur=2.0','X-Request-Id':'test-request'}});
globalThis.requestAnimationFrame=cb=>setTimeout(cb,0);
for(const search of ['','?perf=0']){
 const {api}=await load(search);
 assert.deepEqual(await api('/api/workspace'),{ok:'中'});
 assert.equal(window.__yxPerf,undefined);assert.equal(logs.length,0);assert.equal(marks(),0,'no marks when perf is off');
}
const {api,perfFirstRender}=await load('?perf=1');
assert.deepEqual(await api('/api/workspace'),{ok:'中'});
const [req]=window.__yxPerf.requests;
assert.equal(req.url,'/api/workspace');assert.equal(req.status,200);assert.equal(req.bytes,12);
assert.equal(req.serverTiming,'identity;dur=1.0, total;dur=2.0');
assert.ok(req.headersMs>=0&&req.parseMs>=0);
assert.equal(req.requestId,'test-request');assert.equal(req.serverTotalMs,2);
assert.equal(req.browserWaitMs,req.headersMs);assert.equal(req.outsideServerMs,Math.max(0,req.browserTotalMs-2));
perfFirstRender();await new Promise(r=>setTimeout(r,10));
assert.ok(window.__yxPerf.firstRenderMs>=0);
assert.equal(performance.getEntriesByName('yx:fetch->first-render').length,1);
let conditional=0;
globalThis.fetch=async()=>++conditional===1
 ? new Response('{"ok":true}',{headers:{'ETag':'"v1"','Server-Timing':'total;dur=1','X-Request-Id':'initial'}})
 : new Response(null,{status:304,headers:{'Server-Timing':'total;dur=2','X-Request-Id':'revalidated'}});
assert.deepEqual(await api('/conditional',{etag:true}),{ok:true});
assert.deepEqual(await api('/conditional',{etag:true}),{ok:true});
const revalidated=window.__yxPerf.requests.at(-1);
assert.equal(revalidated.status,304);assert.equal(revalidated.requestId,'revalidated');
assert.equal(revalidated.bytes,0);assert.equal(revalidated.serverTotalMs,2);
assert.ok(revalidated.browserTotalMs>=0);
const freshBody={freshness:{server_time:'2026-10-29T00:00:00Z',datasets:{sources:{as_of:'2026-10-29T00:00:00Z',age_seconds:0,ttl_seconds:60,status:'fresh'}}}};
let freshCalls=0;
globalThis.fetch=async()=>++freshCalls===1
 ? new Response(JSON.stringify(freshBody),{headers:{'ETag':'"age"','Date':'Thu, 29 Oct 2026 00:00:30 GMT'}})
 : new Response(null,{status:304,headers:{'Date':'Thu, 29 Oct 2026 00:01:30 GMT'}});
const fresh=await api('/freshness',{etag:true});
assert.equal(fresh.freshness.datasets.sources.age_seconds,30);
assert.equal(fresh.freshness.datasets.sources.status,'fresh');
const older=await api('/freshness',{etag:true});
assert.equal(older.freshness.datasets.sources.age_seconds,90);
assert.equal(older.freshness.datasets.sources.status,'stale');
assert.equal(older.freshness.datasets.sources.as_of,freshBody.freshness.datasets.sources.as_of);
console.log=log;console.log('perf tests passed');
