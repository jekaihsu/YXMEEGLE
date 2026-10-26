import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {projectFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=project&project=p1&tab=items'});
for(const key of ['window','document','location','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const bundle=await build({stdin:{contents:"export {WorkItemsTab} from './src/WorkItemsTab';export {invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.work-items-source-labels.mjs',import.meta.url);await writeFile(file,bundle.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await unlink(file)}
const fixture=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
const {project,workspace,user}=projectFixture();let payload;
globalThis.fetch=async url=>new Response(JSON.stringify(url.endsWith('/progress')?payload:{}),{headers:{'content-type':'application/json'}});
const c={w:workspace,s:{user},route:{view:'project',project:project.id,tab:'items'},go(){}};
const root=createRoot(document.getElementById('root'));
try{
 for(const [status,assignmentStale,label] of [
  ['ready',false,'來源回報，完成量待核對'],['fresh',false,'來源回報，完成量待核對'],
  ['partial',false,'部分來源'],['unknown',false,'狀態未知'],['loading',false,'來源載入中'],
  ['unlocated',false,'來源未定位'],['stale',false,'來源過期，待核對'],['fresh',true,'來源過期，待核對']
 ]){
  await act(async()=>root.render(null));ui.invalidateSessionEpoch();
  payload=structuredClone(fixture);payload.project_id=project.id;Object.assign(payload.sources,{source_status:status,reports_status:'ok',reports_stale:false});
  const assignments={state:{kind:'ready',data:{stale:assignmentStale}}};
  await act(async()=>root.render(React.createElement(ui.WorkItemsTab,{c,p:project,assignments,selectedKey:'field'})));
  assert.equal(document.querySelector('.wi-evidence')?.textContent,label,`${status}/${assignmentStale} evidence label`);
  assert.equal(!!document.querySelector('.wi-notice')?.textContent.includes('上次成功來源資料'),status==='stale'||assignmentStale,`${status} stale notice`);
 }
 console.log('PASS work item source label table and stale assignment warning');
}finally{await act(async()=>root.unmount())}
