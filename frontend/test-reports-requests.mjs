import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
const bundle=await build({stdin:{contents:"export {useReport} from './src/reports/useReport';export {invalidateSessionEpoch} from './src/api';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',packages:'external',jsx:'automatic'});
const path=new URL('./.reports-requests-bundle.mjs',import.meta.url);await writeFile(path,bundle.outputFiles[0].text);let useReport,invalidateSessionEpoch;try{({useReport,invalidateSessionEpoch}=await import(path.href))}finally{await unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});Object.assign(globalThis,{window:dom.window,document:dom.window.document,location:dom.window.location,IS_REACT_ACT_ENVIRONMENT:true});
const pending=[];globalThis.fetch=(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}));
function View({group}){const state=useReport('review',{group});return React.createElement('div',null,state.loading?'loading':state.error||state.data?.value)}
const root=createRoot(document.getElementById('root'));const render=group=>act(async()=>root.render(React.createElement(View,{group})));const reply=(i,value)=>act(async()=>pending[i].resolve(new Response(JSON.stringify({value}),{status:200})));
await render('一組');await render('二組');assert.equal(pending[0].options.signal.aborted,true);await reply(1,'current');await reply(0,'old');assert.equal(document.body.textContent,'current');
await render('一組');await reply(2,'cached one');await render('二組');assert.equal(pending.length,3);assert.equal(document.body.textContent,'current');await render('三組');invalidateSessionEpoch();await reply(3,'wrong session');assert.equal(document.body.textContent,'loading');
await act(async()=>root.unmount());assert.equal(pending[3].options.signal.aborted,true);
console.log('Reports stale responses, session epoch and unmount cancellation passed.');
