import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {a,workspace} from './session-epoch-fixture.mjs';
const bundle=await build({stdin:{contents:"export {default as App} from './src/App';export {disabledRouteFeature,parseRoute} from './src/api';",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.ux-disabled-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let mod;try{mod=await import(path.href)}finally{await fs.unlink(path)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=approvals'});
for(const key of ['window','document','location','history','sessionStorage','Event','FormData'])globalThis[key]=dom.window[key];
window.scrollTo=()=>{};
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const requests=[];
globalThis.fetch=async url=>{requests.push(url);return new Response(JSON.stringify(url==='/api/session'?{user:a,users:[a],mode:'lark',environment:'production',features:{change_extension:false,routines:false}}:workspace))};
const root=createRoot(document.getElementById('root'));
const flush=fn=>act(async()=>{fn?.();await new Promise(resolve=>setTimeout(resolve,0))});
try{
 await flush(()=>root.render(React.createElement(mod.App)));
 for(const hash of ['#view=approvals','#view=routines','#view=project&project=pA&tab=operations&section=routines','#view=project&project=pA&tab=approvals&approval=private']){
  await flush(()=>{location.hash=hash;window.dispatchEvent(new Event('hashchange'))});
  assert.match(document.querySelector('main.workspace').textContent,/尚未開放/);
  assert.ok([...document.querySelectorAll('button')].some(button=>button.textContent==='回首頁'));
 }
 assert.ok(!document.querySelector('[aria-label="主要導覽"]').textContent.includes('變更與展延'));
 assert.ok(!document.querySelector('[aria-label="主要導覽"]').textContent.includes('追蹤與檢討'));
 assert.ok(!document.querySelector('.mobile-tabs').textContent.includes('變更與展延'));
 assert.equal(document.querySelector('.topbar .data-freshness'),null);
 assert.equal(document.querySelector('.notification-button'),null);
 assert.equal(document.querySelector('.topbar .demo-tag'),null);
 assert.equal(mod.disabledRouteFeature(mod.parseRoute('#view=project&project=pA&tab=approvals'),{}),undefined);
 assert.equal(mod.disabledRouteFeature(mod.parseRoute('#view=approvals'),{change_extension:true}),undefined);
 assert.ok(!requests.some(url=>String(url).includes('/native-approvals/')||String(url).includes('/ops-sync/')));
 console.log('UX disabled routes, aliases, navigation and topbar checks passed');
}finally{await flush(()=>root.unmount());dom.window.close()}
