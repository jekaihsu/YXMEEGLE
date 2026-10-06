// Exercise real App Comments draft keys and submission wiring.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const k of ['window','document','sessionStorage','HTMLElement','Event'])globalThis[k]=dom.window[k];
globalThis.requestAnimationFrame=fn=>setTimeout(fn,0);
globalThis.cancelAnimationFrame=clearTimeout;
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=(await import('react')).default,{act}=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['src/App.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'},plugins:[{name:'expose-comments',setup(b){b.onLoad({filter:/\/App\.tsx$/},async({path})=>({contents:await fs.readFile(path,'utf8')+'\nexport {Comments};',loader:'tsx'}))}}]});
const path=new URL('./.comment-draft-bundle.mjs',import.meta.url);
await fs.writeFile(path,bundle.outputFiles[0].text);
let Comments;try{({Comments}=await import(path.href))}finally{await fs.unlink(path)}
const submissions=[];
const root=createRoot(document.getElementById('root'));
const user={id:'u1',name:'User One',can_mention:true};
const show=async(project='A',node,task,uid='u1',wid='w1')=>act(async()=>root.render(React.createElement(Comments,{
 c:{s:{user:{...user,id:uid},mode:'lark'},w:{workspace_id:wid,users:[user]},route:{},busy:false,run:async(action,payload,scope)=>{submissions.push({action,payload,scope});return true}},
 p:{id:project,comments:[]},n:node?{id:node}:undefined,t:task?{id:task,comments:[]}:undefined
})));
const text=()=>document.querySelector('textarea');
const fill=async value=>act(async()=>{
 Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype,'value').set.call(text(),value);
 text().dispatchEvent(new Event('input',{bubbles:true}));
});
const click=async label=>act(async()=>[...document.querySelectorAll('button')].find(b=>b.textContent.includes(label)).click());
await show();await fill('PRIVATE_A_COMMENT');
await click('標註同事');await click('User One');
await show('B');assert.equal(text().value,'');assert.equal(document.querySelector('.mention-chip'),null);
await fill('B_COMMENT');await click('送出');
assert.deepEqual(submissions.pop(),{action:'comment_add',payload:{body:'B_COMMENT',mentions:[]},scope:{project_id:'B',node_id:undefined,task_id:undefined}});
await show();assert.equal(text().value,'PRIVATE_A_COMMENT');assert.ok(document.querySelector('.mention-chip'));
await click('標註同事');
await show('A','n1');assert.equal(text().value,'');assert.equal(document.querySelector('.mention-picker'),null);
await fill('NODE_1');await show('A','n2');assert.equal(text().value,'');
await fill('NODE_2');await show('A','n1');assert.equal(text().value,'NODE_1');
await show('A','n1','t1');assert.equal(text().value,'');await fill('TASK_1');
await show('A','n1','t2');assert.equal(text().value,'');await fill('TASK_2');
await show('A','n1','t1');assert.equal(text().value,'TASK_1');await click('送出');
assert.deepEqual(submissions.pop().scope,{project_id:'A',node_id:'n1',task_id:'t1'});
await show('A',undefined,undefined,'u2');assert.equal(text().value,'');await fill('USER_2');
await show('A',undefined,undefined,'u1','w2');assert.equal(text().value,'');await fill('WORKSPACE_2');
await show();assert.equal(text().value,'PRIVATE_A_COMMENT');await click('送出');
assert.deepEqual(submissions.pop(),{action:'comment_add',payload:{body:'PRIVATE_A_COMMENT',mentions:['u1']},scope:{project_id:'A',node_id:undefined,task_id:undefined}});
await act(async()=>root.unmount());dom.window.close();
console.log('comment draft scope: project/node/task/user/workspace isolation and submissions passed');
