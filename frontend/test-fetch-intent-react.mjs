import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {usePageResource} from './src/viewData'; export {createPageData} from './src/pageData';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.fetch-intent-react-bundle.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);
let usePageResource,createPageData;try{({usePageResource,createPageData}=await import(path.href))}finally{await fs.unlink(path)}
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
 await act(async()=>owner.close());assert.equal(document.body.textContent,'LoadingLoading');
}finally{await act(async()=>root.unmount());dom.window.close()}
console.log('Fetch-intent React adapter: StrictMode readers coalesce, writes publish, unknown outcomes retain request ID, close clears visible data');
