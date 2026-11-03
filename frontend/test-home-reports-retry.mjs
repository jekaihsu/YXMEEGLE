import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {fakeClock} from './fake-clock-fixture.mjs';
import {homeReportFixture} from './home-reports-fixture.mjs';
const b=await build({stdin:{contents:"export {useHomeReports} from './src/useHomeReports';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.home-retry-test.mjs',import.meta.url);await fs.writeFile(file,b.outputFiles[0].text);let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','Event'])globalThis[key]=dom.window[key];globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const clock=fakeClock(dom.window);let requests=[],queue=[],read;
const fixture=homeReportFixture();
globalThis.fetch=async(url,init)=>{requests.push({url,signal:init.signal});const [status,body]=queue.shift()??[200,fixture];return new Response(JSON.stringify(body),{status})};
const c={s:{workspace_id:'retry-test',mode:'lark',user:{id:'pm',role:'pm'}},reloadVersion:0};
function Probe({today,version=0}){read=m.useHomeReports({...c,reloadVersion:version},'company',['attention'],today);return React.createElement('p',null,read.loading?'loading':read.error||read.data?.week||'empty')}
const root=createRoot(document.getElementById('root'));
const render=(today='2026-10-18',version=0)=>act(async()=>root.render(React.createElement(Probe,{today,version})));
const advance=ms=>act(async()=>clock.advance(ms));
const reset=async()=>{await act(async()=>root.render(null));requests=[];queue=[]};
const warming=(seconds=1)=>[503,{detail:'warming',warming:true,retry_after:seconds}];
try{
 await render();assert.equal(requests.length,1);await render('2026-10-17');await render('2026-10-19');assert.equal(requests.length,1,'week rollover never refreshes an open report');
 for(const response of [warming(),warming(20),[503,{warming:false,retry_after:1}],[500,{warming:true,retry_after:1}],[503,{warming:true}]]){
  await reset();queue=[response];await render();assert.equal(read.loading,false);assert.equal(read.data,undefined);
  await advance(86400000);assert.equal(requests.length,1,'warming and failures never schedule retries');
  for(const event of ['focus','online','pointerdown','keydown','wheel'])window.dispatchEvent(new Event(event));document.dispatchEvent(new Event('visibilitychange'));
  assert.equal(requests.length,1);assert.equal(read.error,'週報資料暫時無法更新；已保留上次資料。');
  await render('2026-10-19',1);assert.equal(requests.length,2,'explicit generation retries exactly once');assert.equal(read.data.week,'2026-10-12');
 }
 await reset();queue=[warming()];await render();await act(async()=>root.render(null));assert.equal(clock.timers.size,0);await advance(1000);assert.equal(requests.length,1);assert.equal(requests[0].signal.aborted,true);
 console.log('PASS report rollover 1→1; warming/failures +24h/events 1→1; explicit refresh 1→2; unmount aborts');
}finally{await act(async()=>root.unmount());clock.restore()}
