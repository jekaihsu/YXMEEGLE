// Run from frontend/: node src/reports/test-loading.mjs
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';

const bundle=await build({stdin:{contents:"export {useReport,clearReportCache} from './src/reports/useReport';export {invalidateSessionEpoch} from './src/api';export {default as ReportsPage} from './src/reports/ReportsPage';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const path=new URL('./.test-loading-bundle.mjs',import.meta.url);
await writeFile(path,bundle.outputFiles[0].text);
let useReport,clearReportCache,invalidateSessionEpoch,ReportsPage;
try{({useReport,clearReportCache,invalidateSessionEpoch,ReportsPage}=await import(path.href))}finally{await unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
dom.window.HTMLElement.prototype.scrollIntoView=()=>{};
Object.assign(globalThis,{window:dom.window,document:dom.window.document,location:dom.window.location,Event:dom.window.Event,IS_REACT_ACT_ENVIRONMENT:true});
const requests=[];
globalThis.fetch=(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}));
let states={};
function Reader({id,pm='shared',reverse=false}){
 const state=useReport('sales',reverse?{limit:50,pm}:{pm,limit:50});states[id]=state;
 return React.createElement('div',{'data-reader':id},state.loading?'loading':state.error||state.data?.value);
}
const root=createRoot(document.getElementById('root'));
const render=children=>act(async()=>root.render(children));
const pair=(pm='shared')=>[React.createElement(Reader,{key:'a',id:'a',pm}),React.createElement(Reader,{key:'b',id:'b',pm,reverse:true})];
const reply=(index,body,status=200)=>act(async()=>requests[index].resolve(new Response(JSON.stringify(body),{status})));
try{
 await render(pair());
 assert.equal(requests.length,1,'identical simultaneous queries share one request, regardless of key order');
 await render(React.createElement(Reader,{key:'b',id:'b',reverse:true}));
 assert.equal(requests[0].options.signal.aborted,false,'one departing reader must not cancel the other');
 await reply(0,{value:'shared result'});
 assert.equal(document.body.textContent,'shared result');
 await render(pair());
 assert.equal(requests.length,1,'resolved data is cached for both readers');

 await render(pair('cancelled'));
 assert.equal(requests.length,2);
 await render(null);
 assert.equal(requests[1].options.signal.aborted,true,'the last departing reader cancels the request');
 await render(pair('cancelled'));
 assert.equal(requests.length,3,'a cancelled flight cannot capture new subscribers');
 await reply(1,{value:'obsolete'});
 assert.equal(document.body.textContent,'loadingloading');
 await reply(2,{value:'fresh'});
 assert.equal(document.body.textContent,'freshfresh');

 await render(pair('failed'));
 await reply(3,{detail:'offline'},503);
 assert.equal(document.body.textContent,'offlineoffline');
 await act(async()=>{states.a.retry();states.b.retry()});
 assert.equal(requests.length,5,'simultaneous retries share a new request after failure');
 await reply(4,{value:'recovered'});
 assert.equal(document.body.textContent,'recoveredrecovered');

 await render(pair('session'));
 const previous=requests.length-1;
 invalidateSessionEpoch();
 await render([React.createElement(Reader,{key:'new-a',id:'new-a',pm:'session'}),React.createElement(Reader,{key:'new-b',id:'new-b',pm:'session'})]);
 assert.equal(requests.length,previous+2,'a new session cannot subscribe to an old flight');
 await reply(previous,{value:'old session'});
 assert.equal(document.body.textContent,'loadingloading');
 await reply(previous+1,{value:'new session'});
 assert.equal(document.body.textContent,'new sessionnew session');

 await render(pair('unauthorized'));
 let expired=0;const onExpired=()=>expired++;
 window.addEventListener('yx:session-expired',onExpired);
 await render(React.createElement(Reader,{key:'b',id:'b',pm:'unauthorized',reverse:true}));
 await reply(requests.length-1,{detail:'expired'},401);
 assert.equal(expired,1,'session expiration uses remaining subscribers, including after the owner leaves');
 window.removeEventListener('yx:session-expired',onExpired);
 await render(pair('warming'));
 const warming=requests.length-1;
 await reply(warming,{detail:'warming',warming:true,retry_after:.01},503);
 assert.equal(states.a.warming,true);assert.equal(states.b.warming,true);
 await act(async()=>new Promise(resolve=>setTimeout(resolve,30)));
 assert.equal(requests.length,warming+2,'warming retries share the next request');
 await reply(warming+1,{value:'warmed'});
 assert.equal(document.body.textContent,'warmedwarmed');
 console.log('Reports dedupe: 2 concurrent readers → 1 request; cache, cancellation, retry and session isolation passed.');

 await render(null);clearReportCache();
 const start=requests.length;
 await render(React.createElement(ReportsPage,{tab:'sales'}));
 assert.deepEqual(requests.slice(start).map(r=>r.url.split('?')[0]),['/api/reports/sales'],'inactive tabs must not load data');
 await render(React.createElement(ReportsPage,{tab:'sources'}));
 assert.deepEqual(requests.slice(start).map(r=>r.url.split('?')[0]),['/api/reports/sales','/api/reports/sources']);
 assert.equal(requests[start].options.signal.aborted,true);
 console.log('Reports lazy tabs: only the active tab requests data; switching cancels unused work.');
}finally{await act(async()=>root.unmount())}
