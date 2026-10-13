import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>');
for(const k of ['window','document','HTMLElement'])globalThis[k]=dom.window[k];
const React=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export * from './src/design'; export {Primary} from './src/appCommon';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.disabled-reasons-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let ui;try{ui=await import(path.href)}finally{await fs.unlink(path)}
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const root=createRoot(document.getElementById('root'));
const render=async(scoped,disabled)=>React.act(async()=>root.render(React.createElement(scoped?(ui.DisabledActionReasons?.Provider||React.Fragment):React.Fragment,scoped&&ui.DisabledActionReasons?{value:true}:null,
 React.createElement(ui.Button,{variant:'primary',disabled,'aria-describedby':'existing'},'Save'),
 React.createElement(ui.Primary,{disabled,disabledReason:'前置成果尚未交付'},'Complete'),
 React.createElement(ui.Button,{disabled},'Secondary'),
 React.createElement('p',{id:'existing'},'Existing help'))));
await render(true,true);
const buttons=[...document.querySelectorAll('button')];
for(const b of buttons.slice(0,2)){
 const ids=b.getAttribute('aria-describedby')?.split(' ')||[];
 assert.ok(ids.length,'disabled primary action has a description');
 const reason=ids.map(id=>document.getElementById(id)?.textContent).join(' ');
 assert.ok(reason.includes(b.textContent==='Save'?'目前無法操作':'前置成果尚未交付'),reason);
}
assert.ok(buttons[0].getAttribute('aria-describedby').includes('existing'));
assert.equal(buttons[2].getAttribute('aria-describedby'),null);
await render(true,false);
assert.equal(document.querySelectorAll('.disabled-action-reason').length,0);
await render(false,true);
assert.equal(document.querySelectorAll('.disabled-action-reason').length,0);
await React.act(async()=>root.unmount());
console.log('Disabled primary reasons: scoped, visible, associated, enabled and secondary behavior passed');
