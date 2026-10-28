import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/',pretendToBeVisual:true});
for(const key of ['window','document','location','Event','KeyboardEvent','MouseEvent','Node','HTMLElement','HTMLInputElement','navigator','DOMException'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react');const {act}=React;const {createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {AssigneePicker} from './src/AssigneePicker';export {AssignmentTaskInspector} from './src/AssignmentTaskInspector';export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.assignee-picker-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);let ui;try{ui=await import(file.href)}finally{await fs.unlink(file)}
let root;const requests=[],chosen=[];
const response=people=>({ok:true,status:200,headers:new Headers(),text:async()=>JSON.stringify({people,next_cursor:null})});
async function flush(){await act(async()=>{await new Promise(resolve=>setTimeout(resolve,0))})}
async function mount(projectId){root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(ui.AssigneePicker,{projectId,nodeKey:'pm',title:'核對',value:'',onChange:id=>chosen.push(id)})))}
async function click(node){await act(async()=>node.dispatchEvent(new MouseEvent('click',{bubbles:true})))}
async function key(value){await act(async()=>document.querySelector('[role=combobox]').dispatchEvent(new KeyboardEvent('keydown',{key:value,bubbles:true})))}
async function search(value){await act(async()=>{const input=document.querySelector('[role=combobox]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}))})}
afterEach(async()=>{if(root)await act(async()=>root.unmount());ui.invalidateSessionEpoch();requests.length=0;chosen.length=0});

test('team default, 250ms search across teams, keyboard selection and clearing',async()=>{
 globalThis.fetch=async(url,init)=>{requests.push({url,init});return response(new URL(url,'http://localhost').searchParams.get('q')?[{id:'outside',name:'其他組王同仁',teams:['控制']}]:[{id:'team',name:'同組林同仁',teams:['PM']}])};
 await mount('picker-default');await click(document.querySelector('button'));await flush();
 assert.equal(requests.length,1);assert.match(requests[0].url,/node_key=pm/);assert.match(requests[0].url,/scope=team/);
 assert.match(document.querySelector('[role=listbox]').textContent,/同組林同仁/);
 await search('王');assert.equal(requests.length,1);
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,280))});await flush();
 assert.equal(requests.length,2);assert.match(requests[1].url,/scope=all/);assert.equal(new URL(requests[1].url,'http://localhost').searchParams.get('q'),'王');
 await key('ArrowDown');assert.match(document.querySelector('[data-active=true]').textContent,/其他組王同仁/);
 await key('Enter');assert.deepEqual(chosen,['outside']);assert.equal(document.querySelector('[role=listbox]'),null);
 assert.equal(document.activeElement.getAttribute('aria-label'),'task: 核對');
 await click(document.querySelector('button'));await flush();await key('Home');await key('Enter');assert.deepEqual(chosen,['outside','']);
});

test('aborts stale search and ignores its late response; session change closes picker',async()=>{
 let oldResolve;globalThis.fetch=(url,init)=>{requests.push({url,init});if(new URL(url,'http://localhost').searchParams.get('q')==='old')return new Promise(resolve=>{oldResolve=resolve});return Promise.resolve(response([{id:'new',name:'最新人員'}]))};
 await mount('picker-stale');await click(document.querySelector('button'));await flush();await search('old');await act(async()=>{await new Promise(resolve=>setTimeout(resolve,280))});
 assert.equal(requests.length,2);await search('new');assert.equal(requests[1].init.signal.aborted,true);
 await act(async()=>{await new Promise(resolve=>setTimeout(resolve,280))});await flush();await act(async()=>oldResolve(response([{id:'old',name:'過期人員'}])));await flush();
 assert.match(document.querySelector('[role=listbox]').textContent,/最新人員/);assert.doesNotMatch(document.querySelector('[role=listbox]').textContent,/過期人員/);
 await act(async()=>ui.invalidateSessionEpoch());assert.equal(document.querySelector('[role=listbox]'),null);
});

test('loading, empty and error states are announced',async()=>{
 let resolve;globalThis.fetch=()=>new Promise(done=>{resolve=done});await mount('picker-empty');await click(document.querySelector('button'));
 assert.equal(document.querySelector('[role=status]').textContent,'載入人員中…');await act(async()=>resolve(response([])));await flush();
 assert.equal(document.querySelector('[role=status]').textContent,'沒有符合的人員');await key('Escape');
 globalThis.fetch=async()=>{throw new Error('offline')};await searchIfClosed();
 async function searchIfClosed(){await click(document.querySelector('button'));await search('missing');await act(async()=>{await new Promise(done=>setTimeout(done,280))});await flush()}
 assert.equal(document.querySelector('[role=alert]').textContent,'無法讀取人員，請重新開啟重試');
});

test('Lark assignment editor searches only its eligible node roster without SOP access',async()=>{
 window.history.replaceState(null,'','#view=project&project=p1&tab=flow');
 globalThis.fetch=async url=>{requests.push(url);return response([{id:'outside',name:'其他組王同仁'}])};
 root=createRoot(document.getElementById('root'));
 const task=assignmentFixture().detail.tasks[0];
 await act(async()=>root.render(React.createElement(ui.AssignmentTaskInspector,{
  assignment:task,people:[{open_id:'eligible',name:'同組王同仁',departments:['控制']}],
  nodeLabel:'控制',nodeKey:'control',busy:false,reason:'',mutate:async value=>{chosen.push(value);return true},onClose:()=>{}
 })));
 await click(document.querySelector(`[aria-label="task: ${task.title}"]`));await flush();
 assert.deepEqual(requests,[]);
 assert.match(document.querySelector('[role=listbox]').textContent,/同組王同仁/);
 await search('王');await act(async()=>{await new Promise(resolve=>setTimeout(resolve,280))});await flush();
 assert.deepEqual(requests,[]);
 assert.match(document.querySelector('[role=listbox]').textContent,/同組王同仁/);
 assert.doesNotMatch(document.querySelector('[role=listbox]').textContent,/其他組/);
 assert.equal(document.querySelector('[role=listbox]').getAttribute('aria-busy'),'false');
 await key('ArrowDown');await key('Enter');
 await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(chosen[0].patch.assignee_open_id,'eligible');
});
