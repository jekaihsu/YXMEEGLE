import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {JSDOM} from 'jsdom';

const homeGraph=await build({entryPoints:['src/HomeDispatchCard.tsx'],absWorkingDir:import.meta.dirname,bundle:true,write:false,metafile:true,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
assert.equal(Object.keys(homeGraph.metafile.inputs).some(file=>file.endsWith('/DispatchBoard.tsx')||file.endsWith('/DispatchBoard.css')),false,'home must not pull in the board UI or CSS');
const bundle=await build({stdin:{contents:"export {useDispatchBoardRead} from './src/dispatchBoardRead';export {HomeDispatchFrame} from './src/HomeDispatchCard';export {DispatchBoardFrame} from './src/DispatchBoard';export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.dispatch-loading-test.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let m;try{m=await import(path.href)}finally{await fs.unlink(path)}
const {variants}=JSON.parse(await fs.readFile(new URL('./fixtures/dispatchBoardSample.json',import.meta.url),'utf8'));
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'});
for(const key of ['window','document','Event','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const requests=[];
globalThis.fetch=(url,init)=>new Promise(resolve=>requests.push({url,init,resolve}));
const flush=async(fn=()=>{})=>act(async()=>{await fn();await new Promise(resolve=>setTimeout(resolve,0))});
const root=createRoot(document.getElementById('root'));
const states={};
const renders=[];
function Probe({id,from,board=false,version=0}){
 const read=m.useDispatchBoardRead(from,version);states[id]=read;
 renders.push({id,from,title:read.data?.slots[0]?.work_content,loading:read.loading});
 return React.createElement(board?m.DispatchBoardFrame:m.HomeDispatchFrame,{from,read,onWeek(){}});
}
const render=(items)=>flush(()=>root.render(items.map(props=>React.createElement(Probe,{key:props.id,...props}))));
const answer=(index,title,status=200,wrongWeek=false)=>flush(()=>{
 const request=requests[index],query=new URL(request.url,'http://localhost').searchParams;
 const body=structuredClone(variants.loaded);body.window={from:query.get('from'),to:query.get('to'),tz:'Asia/Taipei'};body.slots[0].work_content=title;
 if(wrongWeek)body.window={from:'2026-07-27',to:'2026-08-02',tz:'Asia/Taipei'};
 request.resolve(new Response(JSON.stringify(status===200?body:{detail:'offline'}),{status}));
});
const a={id:'home',from:'2026-07-27'},b={id:'board',from:'2026-07-27',board:true};
try{
 await render([a,b]);assert.equal(requests.length,1,'home and board share a passive request');
 await render([b]);assert.equal(requests[0].init.signal.aborted,false,'removing one reader keeps the shared request alive');
 await answer(0,'Week A');assert.equal(states.board.data.slots[0].work_content,'Week A');
 await render([]);
 const mark=renders.length;
 await render([b]);assert.equal(requests.length,2);
 assert.equal(renders[mark].title,'Week A','cached data is present in the first render after home/board navigation');
 assert.equal(states.board.loading,true);assert.equal(states.board.stale,true);
 assert.ok(document.body.textContent.includes('上次成功快照，資料待更新'));
 assert.equal(document.querySelector('.db-skeleton'),null);
 await answer(1,'Week A refreshed');
 await render([{...b,from:'2026-08-03'}]);assert.equal(states.board.data,undefined,'unvisited weeks cannot display a different week');
 await answer(2,'Week B');
 await render([b]);assert.equal(states.board.data.slots[0].work_content,'Week A refreshed');
 await answer(3,'ignored',503);assert.equal(states.board.data.slots[0].work_content,'Week A refreshed');
 assert.ok(document.body.textContent.includes('已保留上次成功資料。'));
 assert.ok([...document.querySelectorAll('button')].some(el=>el.textContent==='重試'));
 // A post-publish reload cannot join the passive read another component started.
 await render([a,b]);const passive=requests.length-1;
 await flush(()=>states.board.reload());const fresh=requests.length-1;
 assert.equal(fresh,passive+1);assert.equal(requests[fresh].init.headers.has('If-None-Match'),false);
 await answer(fresh,'Published');await answer(passive,'Before publish');
 assert.equal(states.board.data.slots[0].work_content,'Published');
 await render([]);await render([a]);assert.equal(states.home.data.slots[0].work_content,'Published','older passive response cannot overwrite the snapshot');
 assert.ok(document.body.textContent.includes('上次成功快照，資料待更新。'));
 assert.ok(document.body.textContent.includes('更新中'));
 await answer(requests.length-1,'Published');
 const previous=requests.length;await render([{...a,version:1}]);assert.equal(requests.length,previous+1,'reloadVersion starts a new read');
 await answer(requests.length-1,'Version refresh');
 await flush(()=>states.home.reload());const oldSession=requests.length-1;
 await flush(()=>m.invalidateSessionEpoch());
 assert.equal(requests[oldSession].init.signal.aborted,true,'session change aborts pending dispatch reads');
 await answer(oldSession,'Private old session');
 assert.equal(states.home.data,undefined,'logout clears visible snapshots immediately');
 await answer(requests.length-1,'New session');assert.equal(states.home.data.slots[0].work_content,'New session');
 await render([{...a,from:'2026-08-03'}]);assert.equal(states.home.data,undefined,'logout also clears other weeks');
 await answer(requests.length-1,'No access',403);assert.deepEqual(states.home.data.source.quality.states,['forbidden']);
 await render([]);await render([{...a,from:'2026-08-03'}]);assert.equal(states.home.data,undefined,'forbidden responses are not cached as snapshots');
 await answer(requests.length-1,'Wrong week',200,true);
 assert.equal(states.home.data,undefined);
 assert.equal(states.home.error,'回應週次與目前查詢不符，請重試。');
 await flush(()=>states.home.reload());const unmounted=requests.length-1;
 await render([]);assert.equal(requests[unmounted].init.signal.aborted,true,'last reader leaving aborts the read');
}finally{await flush(()=>root.unmount());dom.window.close()}
console.log('Dispatch loading: shared readers, first-render week snapshots, visible revalidation, retry, fresh post-publish reload, response races and session clearing passed');
