import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {renderToStaticMarkup} from 'react-dom/server';
import {a,b} from './session-epoch-fixture.mjs';
const bundle=await build({stdin:{contents:"export {default as App} from './src/App'; export {routeLoaders} from './src/routeLoader'; export {parseRoute} from './src/api'; export {HOWTO_SECTIONS} from './src/howToContent'; export {RouteSkeleton} from './src/RouteSkeleton';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',packages:'external',jsx:'automatic',loader:{'.css':'empty'}});
const path=new URL('./.howto-test.mjs',import.meta.url);await fs.writeFile(path,bundle.outputFiles[0].text);
let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
const route=ui.parseRoute('#view=howto&section=assign');
assert.equal(route.view,'howto');assert.equal(route.section,'assign');
const pageModule=await ui.routeLoaders.HowToUse();
const doc=new JSDOM(renderToStaticMarkup(React.createElement(pageModule.default))).window.document;
assert.equal(doc.querySelector('h1').textContent,'使用說明');
const sections=[...doc.querySelectorAll('.howto-section')];
const links=[...doc.querySelectorAll('nav[aria-label="使用說明目錄"] a')];
assert.equal(sections.length,8);assert.equal(links.length,8);
assert.equal(new Set(sections.map(s=>s.id)).size,8,'section ids are unique');
for(const [index,link] of links.entries()){
 const target=ui.parseRoute(link.getAttribute('href'));
 assert.equal(target.view,'howto');assert.equal(target.section,sections[index].id);
 assert.equal(link.textContent,sections[index].querySelector('h2').textContent.slice(2));
}
for(const section of sections){
 assert.ok(section.querySelector('h2').textContent.trim());
 assert.ok(section.querySelector('figure figcaption').textContent.trim());
 const steps=[...section.querySelectorAll('.howto-steps li')];
 assert.ok(steps.length>=2&&steps.length<=5);assert.ok(steps.every(step=>step.textContent.trim()));
 assert.ok(section.querySelector('img'),'every section has a screenshot');
 assert.equal(section.tabIndex,-1,'anchor destinations can receive keyboard focus');
}
for(const img of doc.querySelectorAll('img')){
 assert.ok(img.alt.trim(),'image alt is non-empty');
 const src=img.getAttribute('src');assert.match(src,/^\/howto\/[\w-]+\.webp$/);
 const file=await fs.readFile(new URL(`./public${src}`,import.meta.url));
 assert.equal(file.subarray(0,4).toString(),'RIFF');assert.equal(file.subarray(8,12).toString(),'WEBP');
 assert.ok(file.length<200000,`${src} exceeds 200 KB`);
}
assert.match(renderToStaticMarkup(React.createElement(ui.RouteSkeleton,{route,title:'使用說明'})),/正在載入使用說明/);
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=howto',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','localStorage','FormData','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
window.scrollTo=()=>{};window.HTMLElement.prototype.scrollIntoView=()=>{};globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const json=value=>new Response(JSON.stringify(value),{headers:{'content-type':'application/json'}});
let session;
globalThis.fetch=url=>url==='/api/session'?new Promise(resolve=>{session=resolve}):new Promise(()=>{});
const flush=async fn=>act(async()=>{await fn?.();await new Promise(resolve=>setTimeout(resolve,20))});
const root=createRoot(document.getElementById('root'));
try{
 await flush(()=>root.render(React.createElement(ui.App)));
 await flush(()=>session(json({user:a,users:[a,b],mode:'lark',environment:'production',workspace_id:'A',auth_configured:true})));
 assert.equal(document.querySelector('main h1').textContent,'使用說明','the actual App route renders the lazy page without waiting for workspace data');
 assert.equal(document.querySelectorAll('main.workspace').length,1,'one main landmark');
 assert.equal([...document.querySelectorAll('.nav-item')].find(el=>el.textContent==='使用說明').getAttribute('aria-current'),'page');
 await flush(()=>{location.hash='view=howto&section=assign'});
 assert.equal(document.activeElement.id,'assign','TOC destination receives focus');
 await flush(()=>{location.hash='view=howto'});
 assert.equal(document.querySelectorAll('.howto-section').length,8);
 assert.equal(document.activeElement.id,'howto-title','returning to the TOC restores focus at the top');
}finally{await flush(()=>root.unmount());dom.window.close()}
console.log('How-to: App route/lazy loader, skeleton, sidebar, 8 matching TOC anchors, focus, 2–5 steps per section and 9 accessible image files (<200 KB) passed');
