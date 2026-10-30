import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {fakeClock} from './fake-clock-fixture.mjs';
const bundle=await build({stdin:{contents:"export {useHomePanels} from './src/useHomePanels';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',packages:'external'});
const file=new URL('./.home-query-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await fs.unlink(file)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','Event'])globalThis[key]=dom.window[key];globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const clock=fakeClock(dom.window);const requests=[];
const body={panel:'assigned',scope:'mine',readState:'complete',snapshot_version:'v1',as_of:null,freshness:{status:'fresh',last_success_at:null,refreshing:false},counts:{node_assignments:0,tasks:0,local_workflow:0,complete:true},items:[],next_cursor:null,has_more:false,complete:true,total_count:17,manager_view_available:false};
globalThis.fetch=(url,init)=>new Promise(resolve=>requests.push({url,signal:init.signal,resolve}));
const c={s:{workspace_id:'a',user:{id:'me'},features:{}},w:{version:1},reloadVersion:0};let read;
function Probe({q,version=1}){read=ui.useHomePanels({...c,w:{version}},{panel:'assigned',q});return React.createElement('p',null,read.body?.total_count??'skeleton')}
const root=createRoot(document.getElementById('root'));const render=(q,version)=>act(async()=>root.render(React.createElement(Probe,{q,version})));
const reply=n=>new Response(JSON.stringify({...body,total_count:n}));
try{
 await render('');await act(async()=>requests[0].resolve(reply(17)));
 await render('a');await render('ab');await act(async()=>clock.advance(249));
 assert.equal(requests.length,1,'typing waits for the debounce');
 assert.equal(document.querySelector('p').textContent,'17','previous body stays visible');
 await act(async()=>clock.advance(1));assert.equal(requests.length,2);assert.match(requests[1].url,/q=ab/);assert.equal(read.pending,true);
 await render('abc');await act(async()=>clock.advance(250));assert.equal(requests[1].signal.aborted,true,'superseded request aborts');
 await act(async()=>requests[2].resolve(reply(23)));assert.equal(document.querySelector('p').textContent,'23');
 await render('abc',2);assert.equal(document.querySelector('p').textContent,'23','workspace version never blanks the body');
 const beforeIdle=requests.length;
 await act(async()=>clock.advance(600000));
 assert.equal(requests.length,beforeIdle,'an unattended visible home page does not keep reading');
 await act(async()=>window.dispatchEvent(new Event('pointerdown')));
 assert.equal(requests.length,beforeIdle+1,'resuming interaction refreshes immediately');
 await act(async()=>requests.at(-1).resolve(reply(29)));
 assert.equal(document.querySelector('p').textContent,'29');
 console.log('PASS home query debounce, cancellation, retained body and workspace version');
}finally{await act(async()=>root.unmount());clock.restore()}
