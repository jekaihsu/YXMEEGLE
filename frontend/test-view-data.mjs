import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';

const bundle=await build({stdin:{contents:"export {useViewData} from './src/viewData'; export {api,ApiError,invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.view-data-test-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let useViewData,api,ApiError,invalidateSessionEpoch;
try{({useViewData,api,ApiError,invalidateSessionEpoch}=await import(path.href))}finally{await fs.unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const name of ['window','document','Event'])globalThis[name]=dom.window[name];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const json=(data,etag)=>new Response(JSON.stringify(data),{headers:etag?{ETag:etag}:{}});
const unchanged=()=>new Response(null,{status:304});
let requests=[];
globalThis.fetch=(url,init)=>new Promise(resolve=>requests.push({url,init,resolve}));
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(resolve=>setTimeout(resolve,0))});
let state;
function Probe({view='a',version=1}){
 state=useViewData(view,(signal,current)=>api('/api/'+view,{signal,etag:true},current),[version]);
 return React.createElement('div',{className:state.loading&&!state.data?'skeleton skeleton-row':undefined},state.error||state.data?.label||'loading');
}
let root=createRoot(document.getElementById('root'));
const render=(props)=>flush(()=>root.render(React.createElement(Probe,props)));
const answer=(request,response)=>flush(()=>request.resolve(response));

await render();
assert.equal(requests.length,1);
assert.equal(document.querySelector('.skeleton')!==null,true);
assert.equal(requests[0].init.credentials,'same-origin');
assert.equal(requests[0].init.headers.has('If-None-Match'),false);
await answer(requests[0],json({label:'first'},'W/"a1"'));
assert.equal(state.data.label,'first');
assert.equal(state.loading,false);

await render({version:2});
assert.equal(requests.length,2,'reloadVersion refetches');
assert.equal(requests[0].init.signal.aborted,true);
assert.equal(requests[1].init.headers.get('If-None-Match'),'W/"a1"');
assert.equal(state.loading,true);
assert.equal(state.data.label,'first','refresh keeps stale data');
assert.equal(document.querySelector('.skeleton'),null);
await answer(requests[1],unchanged());
assert.equal(state.data.label,'first','304 returns cached body without parsing');
assert.equal(state.loading,false);

await flush(()=>state.reload());
const stale=requests.at(-1);
await render({version:3});
const fresh=requests.at(-1);
assert.equal(stale.init.signal.aborted,true);
await answer(fresh,json({label:'newest'},'W/"a3"'));
await answer(stale,json({label:'stale'},'W/"stale"'));
assert.equal(state.data.label,'newest','old reload results are discarded even when fetch ignores abort');
await flush(()=>state.reload());
assert.equal(requests.at(-1).init.headers.get('If-None-Match'),'W/"a3"','old reload cannot poison the ETag cache');
await answer(requests.at(-1),new Response('{"detail":"failed"}',{status:503}));
assert.equal(state.error,'failed');
assert.equal(state.data.label,'newest','refresh error preserves data');
await flush(()=>state.reload());
assert.equal(state.error,'');
await answer(requests.at(-1),unchanged());

await render({view:'b'});
const oldRoute=requests.at(-1);
assert.equal(state.data,undefined,'project switch hides previous project immediately');
assert.equal(oldRoute.init.headers.has('If-None-Match'),false,'cache is isolated by URL');
await render({view:'c'});
const currentRoute=requests.at(-1);
assert.equal(oldRoute.init.signal.aborted,true,'route switch aborts');
await answer(oldRoute,json({label:'private-b'},'"b1"'));
assert.equal(state.data,undefined);
await answer(currentRoute,json({label:'private-c'},'"c1"'));
assert.equal(state.data.label,'private-c');

await flush(()=>state.reload());
const oldEpoch=requests.at(-1);
invalidateSessionEpoch();
await answer(oldEpoch,json({label:'private-old-session'},'"old"'));
assert.notEqual(state.data?.label,'private-old-session','stale epoch is discarded');
await render({view:'c'});
const newEpoch=requests.at(-1);
assert.equal(state.data,undefined,'new epoch clears visible data');
assert.equal(newEpoch.init.headers.has('If-None-Match'),false,'new epoch cannot reuse private ETags');
await answer(newEpoch,json({label:'new-session'},'"new"'));
await flush(()=>state.reload());
const unmounted=requests.at(-1);
await flush(()=>root.unmount());
assert.equal(unmounted.init.signal.aborted,true,'unmount aborts');
await answer(unmounted,json({label:'late-unmounted'},'"bad"'));

// Remount validates that late unmounted responses never changed the cached body.
root=createRoot(document.getElementById('root'));
await render({view:'c'});
assert.equal(requests.at(-1).init.headers.get('If-None-Match'),'"new"');
await answer(requests.at(-1),unchanged());
assert.equal(state.data.label,'new-session');
await flush(()=>root.unmount());

// Plain calls retain the existing behavior; cache reload bypasses the validator.
for(const init of [undefined,{etag:true,cache:'reload'},{etag:true,cache:'no-store'}]){
 const pending=api('/api/c',init);
 const request=requests.at(-1);
 assert.equal(request.init.headers.has('If-None-Match'),false);
 request.resolve(json({label:'uncached'}));
 await pending;
}
// A successful response without ETag removes the previous validator.
const missing=api('/api/c',{etag:true});
requests.at(-1).resolve(unchanged());
await assert.rejects(missing,error=>error instanceof ApiError&&error.status===304);
const post=api('/api/c',{method:'POST',etag:true,body:'{}',headers:new Headers({'X-Test':'kept'})});
assert.equal(requests.at(-1).init.headers.has('If-None-Match'),false,'mutations are never conditional');
assert.equal(requests.at(-1).init.headers.get('X-Test'),'kept');
requests.at(-1).resolve(json({ok:true},'"post"'));await post;

// Session changes during JSON body reads must also prevent cache writes.
let releaseBody;
const delayedBody=new Promise(resolve=>{releaseBody=resolve});
const bodyRead=api('/api/body',{etag:true});
requests.at(-1).resolve({status:200,ok:true,headers:new Headers({ETag:'"private"'}),text:()=>delayedBody});
await Promise.resolve();invalidateSessionEpoch();
releaseBody('{"label":"old-body"}');await bodyRead;
const nextBody=api('/api/body',{etag:true});
assert.equal(requests.at(-1).init.headers.has('If-None-Match'),false);
requests.at(-1).resolve(json({label:'current-body'}));await nextBody;

// StrictMode cleanup aborts the first request; only its replacement is accepted.
invalidateSessionEpoch();
root=createRoot(document.getElementById('root'));
const count=requests.length;
await flush(()=>root.render(React.createElement(React.StrictMode,null,React.createElement(Probe))));
assert.equal(requests.length,count+2);
assert.equal(requests[count].init.signal.aborted,true);
await answer(requests[count],json({label:'strict-stale'},'"stale"'));
await answer(requests[count+1],json({label:'strict-current'},'"current"'));
assert.equal(state.data.label,'strict-current');
await flush(()=>root.unmount());dom.window.close();
console.log('View data: abort, route/reload races, session isolation, ETag/304, errors and StrictMode passed');
