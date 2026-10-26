import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {useProjectProgress} from './src/useProjectProgress';export {invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external'});
const file=new URL('./.project-progress-retry-test.mjs',import.meta.url);await writeFile(file,bundle.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await unlink(file)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const key of ['window','document','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const fixture=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
let payload,read,calls;
globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify(payload),{headers:{'content-type':'application/json'}})};
function Probe(){read=ui.useProjectProgress(fixture.project_id);return React.createElement('p',null,read.state.kind)}
const root=createRoot(document.getElementById('root'));
try{
 for(const [sourceStatus,reportsStatus,reportsStale,expected] of [
  ['fresh','ok',false,'ready'],['fresh','restricted',null,'ready'],['fresh','disabled',null,'ready'],
  ['fresh','cold',true,'ready'],['partial','ok',false,'ready'],['fresh','unavailable',true,'ready'],
  ['stale','ok',false,'error'],['unknown','ok',false,'error'],['loading','ok',false,'error']
 ]){
  await act(async()=>root.render(null));ui.invalidateSessionEpoch();calls=0;
  payload=structuredClone(fixture);Object.assign(payload.sources,{source_status:sourceStatus,source_synced_at:'2026-10-26T00:00:00Z',reports_status:reportsStatus,reports_stale:reportsStale});
  await act(async()=>root.render(React.createElement(Probe)));
  assert.equal(read.state.kind,'ready');
  await act(async()=>read.retry());
  assert.equal(calls,2,'retry performs a fresh HTTP read');
  assert.equal(read.state.kind,expected,`${sourceStatus}/${reportsStatus} retry state`);
  if(expected==='ready')assert.deepEqual(read.state,{kind:'ready',data:payload});
  else assert.deepEqual(read.state,{kind:'error',message:'無法更新工程證據，請重試。',lastGoodAt:'2026-10-26T00:00:00Z'});
 }
 console.log('PASS progress retry states keep source freshness independent from report availability');
}finally{await act(async()=>root.unmount())}
