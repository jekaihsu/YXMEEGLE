import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/',pretendToBeVisual:true});
for(const key of ['window','document','Event','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {useFlowDetails} from './src/useFlowDetails';export {DetailRefreshProvider} from './src/detailRefresh';export {nodeReadBlock} from './src/nodeReadBlock';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const path=new URL('./.case-node-perf.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const fixture=assignmentFixture(),calls=[];let latest,selected='control',list=fixture.list;
globalThis.fetch=async url=>{calls.push(url);const key=url.split('/').at(-1);return new Response(JSON.stringify({...fixture.detail,node:fixture.list.nodes.find(n=>n.key===key)}),{headers:{'Content-Type':'application/json'}})};
function Probe(){latest=ui.useFlowDetails('p1',list,selected,true,1);return null}
const root=createRoot(document.getElementById('root'));
const render=()=>act(async()=>root.render(React.createElement(ui.DetailRefreshProvider,null,React.createElement(Probe))));
try{
 assert.match(ui.nodeReadBlock({state:{kind:'ready'},refreshing:false,pending:''},{...fixture.list,stale:true,fetched_at:'2026-11-03T10:00:00+08:00'}),/資料待更新.*重新讀取.*資料時間/);
 assert.equal(ui.nodeReadBlock({state:{kind:'ready'},refreshing:false,pending:''},fixture.list),'','unrelated evidence reads do not gate selected-node actions');
 await render();assert.equal(calls.length,1,'overview/all-tasks fallback reads only selected node; budget 1');assert(latest.details.control);
 selected='field';await render();assert.equal(calls.length,2);selected='control';await render();assert.equal(calls.length,2,'selected node read once per open generation');
 await act(async()=>{window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('online'))});assert.equal(calls.length,2);
 list={...list,node_details:Object.fromEntries(list.nodes.map(n=>[n.key,{tasks:[],assignable_people:[]}]))};await render();assert.equal(calls.length,2,'embedded batch needs zero extra reads');
 console.log('PASS selected detail request budget, reuse, embedded batch and no automatic refetch');
}finally{await act(async()=>root.unmount());dom.window.close()}
