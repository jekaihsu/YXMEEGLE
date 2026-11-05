import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {usePageResource} from './src/viewData'; export {createPageData,usePageOwner} from './src/pageData'; export {api,invalidateSessionEpoch,epochListenerCount} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'},plugins:[{name:'epoch-observer',setup(b){b.onLoad({filter:/\/api\.ts$/},async({path})=>({contents:await fs.readFile(path,'utf8')+'\nexport const epochListenerCount=()=>epochListeners.size;',loader:'ts'}))}}]});
const path=new URL('./.fetch-intent-react-bundle.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);
let usePageResource,createPageData,usePageOwner,invalidateSessionEpoch,epochListenerCount,api;try{({usePageResource,createPageData,usePageOwner,invalidateSessionEpoch,epochListenerCount,api}=await import(path.href))}finally{await fs.unlink(path)}
const dom=new JSDOM('<div id="root"></div>');for(const key of ['window','document','Event'])globalThis[key]=dom.window[key];globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const owner=createPageData({workspace:'a',identityFingerprint:'a',openId:'1'}),resource={endpoint:'/fixture'};let calls=0;
const load=async()=>({data:++calls,snapshotId:null,fetchedAt:null,verifiedAt:null,changedAt:null,completeness:'complete',localRevision:null,empty:false,stale:false});
function Reader(){const state=usePageResource(owner,resource,{reason:'initial_open'},load);return React.createElement('span',null,state.kind==='Ready'?state.value.data:state.kind)}
const root=createRoot(document.getElementById('root'));
try{
 await act(async()=>root.render(React.createElement(React.StrictMode,null,React.createElement(Reader),React.createElement(Reader))));
 assert.equal(calls,1);assert.equal(document.body.textContent,'11');
 await act(async()=>owner.ownWriteCommitted('write',[resource]));assert.equal(document.body.textContent,'22');assert.equal(calls,2);
 await act(async()=>owner.unknownOutcome(resource,'request-id'));assert.equal(document.body.textContent,'UnknownOutcomeUnknownOutcome');
 await act(async()=>owner.close());assert.equal(document.body.textContent,'ClosedClosed');
}finally{await act(async()=>root.unmount());dom.window.close()}
console.log('Fetch-intent React adapter: StrictMode readers coalesce, writes publish, unknown outcomes retain request ID, close clears visible data');

const mount=document.createElement('div');document.body.append(mount);const app=createRoot(mount);
let currentOwner,deny=false;const scope={workspace:'same',identityFingerprint:'same-grants',openId:'same-case'};
function Owned(){currentOwner=usePageOwner(scope);const state=usePageResource(currentOwner,resource,{reason:'initial_open'},async()=>{if(deny)throw {status:401};return load()});return React.createElement('output',null,state.kind==='Ready'?state.value.data:state.kind)}
const baseline=epochListenerCount();
await act(async()=>app.render(React.createElement(React.StrictMode,null,React.createElement(Owned))));
assert.equal(mount.textContent,'3');assert.equal(epochListenerCount(),baseline+2,'StrictMode discarded render and effect replay do not leak owners');
const before=currentOwner;await act(async()=>invalidateSessionEpoch());assert.notEqual(currentOwner,before);assert.equal(mount.textContent,'4','identical scope reloads on epoch change');
deny=true;await act(async()=>{await currentOwner.read(resource,{reason:'explicit_refresh',id:'denied'},async()=>{throw {status:401}}).catch(()=>{})});assert.equal(mount.textContent,'Denied');
await act(async()=>invalidateSessionEpoch());assert.equal(mount.textContent,'Denied','new epoch can settle to Denied instead of permanent Loading');
deny=false;await act(async()=>invalidateSessionEpoch());assert.equal(mount.textContent,'5','Denied -> session change -> successful identical scope');
await act(async()=>app.unmount());await new Promise(setImmediate);assert.equal(epochListenerCount(),baseline,'real unmount unsubscribes');assert.equal(currentOwner.state(resource).kind,'Closed');
const manual=createPageData(scope);await manual.read(resource,{reason:'initial_open'},load);assert.equal(epochListenerCount(),baseline+1);manual.close();assert.equal(epochListenerCount(),baseline,'close unsubscribes immediately');
console.log('K2 owner hook: StrictMode, epoch rekey, Denied recovery and subscription disposal passed');

// Exercise api.ts's synchronous 401 -> session-expired -> epoch-change path.
let httpCalls=0;globalThis.fetch=async()=>++httpCalls===1?new Response(JSON.stringify({detail:'expired'}),{status:401}):new Response(JSON.stringify({data:'signed-in'}));
const expired=()=>invalidateSessionEpoch();window.addEventListener('yx:session-expired',expired,{once:true});
const loginMount=document.createElement('div');document.body.append(loginMount);const loginRoot=createRoot(loginMount);
function LoginOwner(){const owner=usePageOwner(scope);const state=usePageResource(owner,resource,{reason:'initial_open'},async(signal,current)=>({...await load(),data:(await api('/login-fixture',{signal},current)).data}));return React.createElement('span',null,state.kind==='Ready'?state.value.data:state.kind)}
await act(async()=>loginRoot.render(React.createElement(React.StrictMode,null,React.createElement(LoginOwner))));
assert.equal(httpCalls,2);assert.equal(loginMount.textContent,'signed-in','401 epoch change reopens identical scope and settles');
await act(async()=>loginRoot.unmount());await new Promise(setImmediate);window.removeEventListener('yx:session-expired',expired);
