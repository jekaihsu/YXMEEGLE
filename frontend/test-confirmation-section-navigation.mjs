import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {confirmationFixture} from './fixtures/confirmation-detail.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=confirmation&ctx=retained'});
for(const k of ['window','document','location','HTMLElement'])globalThis[k]=dom.window[k];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {CaseDetail} from './src/CaseDetail'; export {buildCaseDetailView} from './src/caseDetailView';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.confirmation-navigation.mjs',import.meta.url);await writeFile(path,bundle.outputFiles[0].text);let ui;try{ui=await import(path.href)}finally{await unlink(path)}
const root=createRoot(document.getElementById('root'));const view=ui.buildCaseDetailView(confirmationFixture());
await React.act(async()=>root.render(React.createElement(ui.CaseDetail,{view})));
const hash=location.hash;let scrolled=[];HTMLElement.prototype.scrollIntoView=function(){scrolled.push(this.id)};
for(const control of document.querySelectorAll('nav[aria-label="章節快速導覽"] button, nav[aria-label="章節快速導覽"] a')){
 await React.act(async()=>control.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true,cancelable:true})));
 await new Promise(resolve=>setTimeout(resolve,0));
 assert.equal(location.hash,hash,'section navigation must preserve the hash router route');
 assert.equal(scrolled.length,1,'section control must scroll');
 const target=document.getElementById(scrolled.pop());assert.match(target.id,/^confirmation-section-[a-z_]+$/);
 assert.equal(document.activeElement,target,'keyboard focus follows the section');
}
assert.equal(document.querySelectorAll('nav[aria-label="章節快速導覽"] button').length,7);
await React.act(async()=>root.unmount());console.log('confirmation navigation: seven sections scroll/focus without changing route');
