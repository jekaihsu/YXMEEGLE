import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{pretendToBeVisual:true,url:'http://localhost'});
for(const key of ['window','document','HTMLElement','Element','KeyboardEvent','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.getComputedStyle=dom.window.getComputedStyle;
dom.window.HTMLElement.prototype.getClientRects=function(){return [{width:100,height:30}]};
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const built=await build({stdin:{contents:"export {Modal} from './src/appCommon';export {Sheet} from './src/design';export {TaskDrawer} from './src/TaskDrawer';export {useDialogFocus} from './src/useDialogFocus';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.dialog-focus-test.mjs',import.meta.url);await writeFile(path,built.outputFiles[0].text);const ui=await import(path.href);await unlink(path);
const h=React.createElement,root=createRoot(document.getElementById('root'));
function Harness({kind}){
 const [open,setOpen]=React.useState(false);
 return h(React.Fragment,null,h('button',{onClick:()=>setOpen(true)},'開啟'),open&&h(ui[kind],{title:'測試',label:'測試',kind:'legacy',trail:[],onClose:()=>setOpen(false)},h('input',{autoFocus:true,'aria-label':'自動焦點'}),h('button',null,'末項')));
}
// Dialogs must work with the element's DOM even when constructors are not global.
delete globalThis.HTMLElement;delete globalThis.Element;delete globalThis.getComputedStyle;
for(const kind of ['Modal','Sheet','TaskDrawer']){
 await act(async()=>root.render(h(Harness,{kind,key:kind})));
 const trigger=document.querySelector('#root>button');trigger.focus();await act(async()=>trigger.click());
 const panel=document.querySelector('[role=dialog]');
 assert.ok(panel.contains(document.activeElement));
 const controls=panel.querySelectorAll('button,input');
 controls[controls.length-1].focus();
 await act(async()=>document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true})));
 assert.equal(document.activeElement,controls[0],kind+' traps Tab without DOM globals');
 await act(async()=>document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
 assert.equal(document.querySelector('[role=dialog]'),null);assert.equal(document.activeElement,trigger,kind+' restores pre-mount focus despite autoFocus');
}
// AppShell enables the mounted hook when mobile navigation opens.
function Toggle(){const [open,setOpen]=React.useState(false);const ref=ui.useDialogFocus(()=>setOpen(false),open);return h(React.Fragment,null,h('button',{onClick:()=>setOpen(true)},'導覽'),open&&h('nav',{ref,role:'dialog',tabIndex:-1},h('button',null,'首頁')))}
await act(async()=>root.render(h(Toggle)));const trigger=document.querySelector('#root>button');trigger.focus();await act(async()=>trigger.click());await act(async()=>document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));assert.equal(document.activeElement,trigger);
await act(async()=>root.unmount());console.log('Dialog focus: Modal, Sheet, TaskDrawer and enabled navigation pass');
