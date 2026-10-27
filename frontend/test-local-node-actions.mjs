import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','Event','KeyboardEvent','HTMLElement','HTMLSelectElement','HTMLTextAreaElement'])globalThis[key]=dom.window[key];
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {LocalNodeActions} from './src/LocalNodeActions';export {FlowNodeActions} from './src/FlowActions';export {actionRegistry} from './src/nodeWorkbenchModel';export {sopApi,SopError} from './src/sopTaskApi';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.local-node-actions-test.mjs',import.meta.url);await writeFile(file,bundle.outputFiles[0].text);const ui=await import(file.href);await unlink(file);
const button=text=>[...document.querySelectorAll('button')].find(b=>b.textContent===text);
const click=async element=>act(async()=>{element.focus();element.click()});
const local=(can={assign:true,complete:false,reject:false},reason=null)=>({local:{key:'sales',revision:0,can,disabledReason:reason},actions:ui.actionRegistry({can,reason:reason||'',local:true})});
const sop={assignees:[{id:'u1',name:'林先生'}],current:()=>true,reload:async()=>{},assigneeError:''};
test('policy-blocked local actions show one reason without inaccessible buttons',async()=>{
 const root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.LocalNodeActions,{projectId:'p',sop,workbench:local({assign:false,complete:false,reject:false},'此節點尚未納入 SOP 管理')})));
 assert.equal(document.querySelectorAll('button').length,0);assert.equal(document.body.textContent,'此節點尚未納入 SOP 管理');
 await act(async()=>root.unmount());
});
test('409 reloads local node state and preserves the form draft',async()=>{
 const root=createRoot(document.getElementById('root'));let reloads=0;
 ui.sopApi.localNode=async()=>{throw new ui.SopError(409,'node_revision_conflict')};
 await act(async()=>root.render(React.createElement(ui.LocalNodeActions,{projectId:'p',sop:{...sop,reload:async()=>{reloads++}},workbench:local()})));
 await click(button('指派負責人'));
 const select=document.querySelector('select');await act(async()=>{select.value='u1';select.dispatchEvent(new Event('change',{bubbles:true}))});
 await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(reloads,1);assert.equal(select.value,'u1');assert.match(document.querySelector('[role=alert]').textContent,/更新|重新/);
 await click(button('取消'));await new Promise(resolve=>setTimeout(resolve,5));assert.equal(document.activeElement,button('指派負責人'));
 await act(async()=>root.unmount());
});
test('local cancel and Escape return focus without scrolling',async()=>{
 const root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.LocalNodeActions,{projectId:'p',sop,workbench:local()})));
 await click(button('指派負責人'));await act(async()=>document.querySelector('form').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));await new Promise(resolve=>setTimeout(resolve,5));
 assert.equal(document.querySelector('form'),null);assert.equal(document.activeElement,button('指派負責人'));await act(async()=>root.unmount());
});
test('completion confirmation reports all unfinished tasks and hides completed-node completion',async()=>{
 const root=createRoot(document.getElementById('root'));
 const detail={can:{complete:true},node:{derived_status:'進行中',key:'sales',revision:'r'},tasks:[{status:'待處理'},{status:'進行中'},{status:'已完成'},{status:'取消'}]};
 const props={detail,busy:false,error:null,reason:'',mutate:async()=>true};
 await act(async()=>root.render(React.createElement(ui.FlowNodeActions,props)));await click(button('完成節點'));
 assert.match(document.querySelector('.pf-confirm').textContent,/尚有 2 項任務未完成/);
 await act(async()=>root.render(React.createElement(ui.FlowNodeActions,{...props,detail:{...detail,node:{...detail.node,derived_status:'已完成'},can:{complete:true,reject:true}}})));
 assert.equal(button('完成節點'),undefined);await act(async()=>root.unmount());
});
test('remote policy-blocked reason replaces a row of disabled actions',async()=>{
 const root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.FlowNodeActions,{detail:{can:{},node:{derived_status:'待處理'},tasks:[],writes_disabled_reason:'案件尚未啟用 SOP 管理'},busy:false,error:null,reason:'',mutate:async()=>false})));
 assert.equal(document.querySelectorAll('button').length,0);assert.equal(document.body.textContent,'案件尚未啟用 SOP 管理');await act(async()=>root.unmount());
});

test('state-hidden remote actions show one specific reason line',async()=>{
 const root=createRoot(document.getElementById('root'));
 for(const [detail,expected] of [
  [{can:{complete:true},node:{derived_status:'已完成',auto_done:{reason:'來源成果已核實'}},tasks:[]},'來源成果已核實'],
  [{can:{complete:true},node:{derived_status:'略過'},tasks:[]},'略過'],
 ]){
  await act(async()=>root.render(React.createElement(ui.FlowNodeActions,{detail,busy:false,error:null,reason:'',mutate:async()=>false})));
  assert.equal(document.querySelectorAll('button').length,0);
  assert.equal(document.querySelectorAll('.nw-action-reason').length,1);
  assert.equal(document.body.textContent,expected);
 }
 await act(async()=>root.unmount());
});
test('visible remote actions retain specific busy and writes-off reasons',async()=>{
 const root=createRoot(document.getElementById('root'));
 for(const props of [{busy:true,reason:'正在更新節點資料，請稍候。'}, {busy:false,reason:'',writes_disabled_reason:'節點修改尚未開放。'}]){
  await act(async()=>root.render(React.createElement(ui.FlowNodeActions,{detail:{can:{assign:true},node:{derived_status:'進行中'},tasks:[],writes_disabled_reason:props.writes_disabled_reason},...props,error:null,mutate:async()=>false})));
  assert.equal(button('指派負責人').disabled,true);
  assert.equal(button('指派負責人').title,props.reason || props.writes_disabled_reason);
 }
 await act(async()=>root.unmount());
});
