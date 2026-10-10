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
globalThis.fetch=async()=>new Response('{"ok":"中"}',{status:200,headers:{'Server-Timing':'identity;dur=1.0, total;dur=2.0'}});
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
perfFirstRender();await new Promise(r=>setTimeout(r,10));
assert.ok(window.__yxPerf.firstRenderMs>=0);
assert.equal(performance.getEntriesByName('yx:fetch->first-render').length,1);
console.log=log;console.log('perf tests passed');
