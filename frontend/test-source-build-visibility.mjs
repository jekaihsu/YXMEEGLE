import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=sources'});
for(const key of ['window','document','location','Event'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const bundle=await build({stdin:{contents:"export {SourceHealthPage} from './src/IntegratedPages';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.source-build-visibility.mjs',import.meta.url);await writeFile(file,bundle.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await unlink(file)}
globalThis.fetch=async url=>new Response(JSON.stringify(url==='/api/health'?{build:{git_sha:'a'.repeat(40),dirty:false}}:{page_state:{states:['unknown']},sources:[]}),{headers:{'content-type':'application/json'}});
const root=createRoot(document.getElementById('root'));
try{
 for(const role of ['manager','pm','member','demo','test']){
  const c={s:{user:{id:role,role}},w:{version:1},route:{view:'sources'},go(){}};
  await act(async()=>root.render(React.createElement(ui.SourceHealthPage,{c})));
  assert.equal(document.querySelector('[aria-label="部署版本"]')?.textContent??null,role==='manager'?'版本 aaaaaaa':null,`${role} build label visibility`);
  assert.ok(document.querySelector('[aria-label="來源健康診斷"]'),`${role} retains source diagnostics`);
 }
 console.log('PASS only managers see the build label; every role retains source diagnostics');
}finally{await act(async()=>root.unmount())}
