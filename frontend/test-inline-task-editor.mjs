import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>');
for(const key of ['window','document','Event','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {InlineTaskEditor} from './src/InlineTaskEditor';export {editorFields} from './src/nodeWorkbenchModel'",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'}});
const path=new URL('./.inline-editor-test.mjs',import.meta.url);await writeFile(path,bundle.outputFiles[0].text);const ui=await import(path.href);await unlink(path);
const draft={title:'核對成果',assignee:'u1',due:'2026-10-25',notes:'原備註',status:'pending',reason:''};
const change=async(label,value)=>{const el=document.querySelector(`[aria-label="${label}"]`);await act(async()=>{Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'value').set.call(el,value);el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}))})};
for(const source of ['lark','local-sop','legacy'])test(`${source} uses the same visible editor and saves changed fields`,async()=>{
 const root=createRoot(document.getElementById('root'));let saved;
 const model={draft,fields:ui.editorFields({title:true,assignee:true,due:true,notes:true,status:true}),people:[{id:'u1',name:'甲'},{id:'u2',name:'乙'}],statuses:[{id:'pending',label:'待處理'},{id:'in_progress',label:'進行中'}],maxTitle:200,maxNotes:2000,dueReason:source==='local-sop'};
 await act(async()=>root.render(React.createElement(ui.InlineTaskEditor,{model,onSave:async value=>{saved=value;return true}})));
 assert.equal(document.querySelector('details'),null);
 await change('任務名稱','更新標題');await change('任務負責人','u2');await change('任務期限','2026-10-30');await change('任務備註','更新備註');await change('任務狀態','in_progress');
 if(model.dueReason)await change('期限變更原因','配合時程');
 await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 assert.deepEqual(saved,{title:'更新標題',assignee:'u2',due:'2026-10-30',notes:'更新備註',status:'in_progress',reason:model.dueReason?'配合時程':''});
 await act(async()=>root.unmount());
});
test('denied fields have a visible reason and cannot save an unchanged task',async()=>{
 const root=createRoot(document.getElementById('root'));let writes=0;
 await act(async()=>root.render(React.createElement(ui.InlineTaskEditor,{model:{draft,fields:ui.editorFields({title:false,assignee:false,due:false,notes:false,status:false},'需管理權限'),people:[],statuses:[{id:'pending',label:'待處理'}],maxTitle:200,maxNotes:2000,dueReason:false},onSave:async()=>{writes++;return true}})));
 assert.equal(document.querySelector('input').disabled,true);assert.match(document.body.textContent,/需管理權限/);
 await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));assert.equal(writes,0);await act(async()=>root.unmount());
});
test('legacy start date and points are editable and reach the save callback',async()=>{
 const root=createRoot(document.getElementById('root'));let saved;
 const model={draft:{...draft,start_date:'',points:''},legacy:{start_date:true,points:true},fields:ui.editorFields({title:true,assignee:true,due:true,notes:true,status:false}),people:[],statuses:[{id:'pending',label:'待處理'}],maxTitle:500,maxNotes:20000,dueReason:false};
 await act(async()=>root.render(React.createElement(ui.InlineTaskEditor,{model,onSave:async d=>{saved=d;return true}})));
 await change('任務開始日期','2026-10-26');await change('任務營業額點數','12.5');
 await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(saved.start_date,'2026-10-26');assert.equal(saved.points,'12.5');await act(async()=>root.unmount());
});
test('archived tasks show one short reason and keep every field disabled',async()=>{
 const root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(ui.InlineTaskEditor,{model:{draft,fields:ui.editorFields({title:false,assignee:false,due:false,notes:false,status:false},'已封存'),readOnlyReason:'已封存',people:[],statuses:[{id:'pending',label:'待處理'}],maxTitle:500,maxNotes:20000,dueReason:false},onSave:async()=>false})));
 assert.equal(document.querySelectorAll('#task-editor-readonly').length,1);assert.equal(document.querySelectorAll('small').length,0);assert.ok([...document.querySelectorAll('input,select,textarea')].every(el=>el.disabled));await act(async()=>root.unmount());
});
