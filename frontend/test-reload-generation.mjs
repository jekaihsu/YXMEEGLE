import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;HTMLElement.prototype.scrollIntoView=function(){};
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetailGate} from './src/ProjectDetail';export {readPanel,cachedPanel} from './src/companyDashboardCache';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.reload-generation-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await fs.unlink(file)}
const requests=[];globalThis.fetch=(url)=>new Promise(resolve=>requests.push({url,resolve}));
const response=body=>new Response(JSON.stringify(body));
const root=createRoot(document.getElementById('root'));const {project,user,workspace}=projectFixture();
const c={w:{...workspace,scope:'shell',projects:[]},s:{user,features:{}},route:{view:'project',project:'p1',tab:'logs'},go(){},registerDrafts(){}};
try{
 await act(async()=>root.render(React.createElement(ui.ProjectDetailGate,{c:{...c,reloadVersion:0}})));
 await act(async()=>root.render(React.createElement(ui.ProjectDetailGate,{c:{...c,reloadVersion:1}})));
 assert.equal(requests.length,2,'post-mutation project reload starts a new read');
 const snapshot=name=>({...workspace,project:{...project,name}});
 await act(async()=>requests[1].resolve(response(snapshot('mutation result'))));
 await act(async()=>requests[0].resolve(response(snapshot('old result'))));
 assert.equal(document.querySelector('h1').textContent,'mutation result');
 const a=ui.readPanel('/api/generation',new AbortController().signal,'me',{reloadVersion:0});
 const b=ui.readPanel('/api/generation',new AbortController().signal,'me',{reloadVersion:1});
 const panelRequests=requests.filter(r=>r.url==='/api/generation');
 assert.equal(panelRequests.length,2,'panel reload generation does not attach to the old read');
 panelRequests[1].resolve(response({value:'new'}));await b;
 panelRequests[0].resolve(response({value:'old'}));await a;
 assert.deepEqual(ui.cachedPanel('/api/generation','me'),{value:'new'},'older generation cannot replace the fresh cache');
 console.log('PASS project and panel reload generations isolate pending reads and cache publication');
}finally{await act(async()=>root.unmount())}
