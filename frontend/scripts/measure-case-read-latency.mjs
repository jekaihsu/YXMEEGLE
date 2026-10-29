// Run from frontend: node scripts/measure-case-read-latency.mjs (about 26 seconds).
// Isolates the case snapshot timeout/retry path; it is not a browser or Lark benchmark.
import {execFileSync} from 'node:child_process';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture} from '../fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const {project,user,workspace}=projectFixture();
const c={w:{...workspace,scope:'shell'},s:{user,workspace_id:'offline',features:{}},route:{view:'project',project:project.id,tab:'files'},go(){},registerDrafts(){},notify(){}};
const results=[];
for(const version of ['before','after']){
 const source=version==='before'?execFileSync('git',['show','425c192:frontend/src/ProjectDetail.tsx'],{encoding:'utf8'}):await fs.readFile('src/ProjectDetail.tsx','utf8');
 const result=await build({stdin:{contents:source,resolveDir:process.cwd()+'/src',sourcefile:version+'.tsx',loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
 const path=new URL('./.round2-'+version+'.mjs',import.meta.url);await fs.writeFile(path,result.outputFiles[0].text);
 const ui=await import(path.href);await fs.unlink(path);
 for(const mode of ['cold','warm']){
  let calls=0,completed=0;const delays=[];
  globalThis.fetch=async()=>{const delay=mode==='warm'?10:calls===0?10100:5100;calls++;delays.push(delay);await new Promise(r=>setTimeout(r,delay));completed++;return new Response(JSON.stringify({...workspace,scope:'project',project}));};
  const root=createRoot(document.getElementById('root'));const start=performance.now();
  await act(async()=>root.render(React.createElement(ui.ProjectDetailGate,{c:{...c,reloadVersion:mode}})));
  while((completed<calls||!document.body.textContent.includes('文件與交付'))&&!document.querySelector('[role=alert]'))await act(async()=>{await new Promise(r=>setTimeout(r,50))});
  const row={version,mode,settled_ms:Math.round(performance.now()-start),requests:calls,delays_ms:delays,success:document.body.textContent.includes('文件與交付')};results.push(row);console.log(JSON.stringify(row));await act(async()=>root.unmount());
 }
}
await fs.writeFile('../.runtime/case-detail-perf/latency-reproduction.json',JSON.stringify(results,null,2));dom.window.close();
