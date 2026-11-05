import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import fs from 'node:fs/promises';
const dom=new JSDOM('<div id="root"></div>');
globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export * from './src/CaseStatus';export * from './src/stageModel';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const file=new URL('./.progress-status-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);
let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
for(const [name,project,label,chip] of [
 ['unverified empty case',{execution_status:'paused',progress_status:'pending'},'尚未開始',true],
 ['unverified started case',{execution_status:'paused',progress_status:'in_progress'},'進行中',true],
 ['real stop',{execution_status:'paused',progress_status:'paused'},'暫停中',false],
 ['old payload',{execution_status:'paused'},'暫停中',false],
 ['shell progress with legacy alias',{status:'paused',progress_status:'pending'},'尚未開始',true],
 ['legacy status alias',{status:'pending'},'尚未開始',false],
 ['engineering complete',{execution_status:'engineering_complete',progress_status:'engineering_complete'},'工程完成、財務待結',false],
])test(name,async()=>{
 const root=createRoot(document.getElementById('root'));
 try{await React.act(async()=>root.render(React.createElement(m.CaseStatus,{project})));
 assert.equal(m.caseStatusLabel(project),label);assert.equal(document.querySelector('small')?.textContent??null,chip?'來源狀態待核對':null);
 assert.equal(document.getElementById('root').textContent,label+(chip?'來源狀態待核對':''));
 }finally{await React.act(async()=>root.unmount())}
});
test('source review stage title retains a blocker without a pause label or action',()=>{
 const ctx={workflow:'ready',currentKnown:true,finished:false};
 const step=m.stageNextStep({ctx,today:'2026-11-02',fresh:true,block:{kind:'source',reason:'來源案件狀態待核對'}});
 assert.deepEqual(step,{kind:'none',title:'來源案件狀態待核對',reasons:[]});
});
