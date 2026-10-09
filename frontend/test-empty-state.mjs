import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({entryPoints:['src/appCommon.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.empty-test-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let Empty;try{Empty=(await import(bundlePath.href)).Empty}finally{await fs.unlink(bundlePath)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','location'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const root=createRoot(document.getElementById('root'));
try{
 await act(async()=>root.render(React.createElement(Empty)));
 assert.equal(document.querySelector('h3').textContent,'目前沒有資料');
 assert.equal(document.querySelector('p'),null);
 assert.equal(document.querySelector('button'),null);
 let returned=false;
 await act(async()=>root.render(React.createElement(Empty,{title:'找不到這個頁面',detail:'請返回工作總覽。',action:React.createElement('button',{onClick:()=>{returned=true}},'返回工作總覽')})));
 assert.equal(document.querySelector('h3').textContent,'找不到這個頁面');
 assert.equal(document.querySelector('p').textContent,'請返回工作總覽。');
 await act(async()=>document.querySelector('button').dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true})));
 assert.equal(returned,true,'the empty-state action returns control to its caller');
 console.log('Empty state: default content, optional detail and working return action PASS');
}finally{await act(async()=>root.unmount());dom.window.close()}
