// Mount two real same-title DraftForms for different records; drafts must stay isolated per record/action/revision.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#project=P1&node=N1'});
for(const k of ['window','document','sessionStorage','location','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','Event','FormData'])Object.defineProperty(globalThis,k,{value:dom.window[k],configurable:true,writable:true});
// react-dom must load after the DOM globals exist or it disables DOM event handling.
const React=(await import('react')).default,{act}=await import('react');
const {createRoot}=await import('react-dom/client');
const bundle=await build({entryPoints:['src/FormDraft.tsx'],bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.form-draft-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let DraftForm,DraftNamespace;try{({DraftForm,DraftNamespace}=await import(bundlePath.href))}finally{await fs.unlink(bundlePath)}
globalThis.IS_REACT_ACT_ENVIRONMENT=true;

const TITLE='記錄本次執行';
const submitted=[];let result=true;
const form=(record,id=`recurring:${record}:1`)=>React.createElement('div',{'data-record':record,key:record},
 React.createElement(DraftForm,{title:TITLE,draftId:id,busy:false,onSubmit:d=>{submitted.push({record,evidence:d.evidence});return Promise.resolve(result)}},
  React.createElement('textarea',{name:'evidence'})));
const root=createRoot(document.getElementById('root'));
const show=async(...ids)=>act(async()=>root.render(React.createElement(DraftNamespace.Provider,{value:'u1:w1'},...ids.map(r=>typeof r==='string'?form(r):form(r.record,r.id)))));
const hide=async()=>act(async()=>root.render(null));
const at=r=>document.querySelector(`[data-record="${r}"]`);
const text=r=>at(r).querySelector('textarea');
const button=(r,label)=>[...at(r).querySelectorAll('button')].find(b=>b.textContent===label);
const type=async(r,v)=>act(async()=>{Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype,'value').set.call(text(r),v);text(r).dispatchEvent(new dom.window.Event('input',{bubbles:true}))});
const click=async(r,label)=>act(async()=>button(r,label).click());
const submit=async r=>act(async()=>{at(r).querySelector('form').requestSubmit()});
const keys=()=>Object.keys(sessionStorage).filter(k=>k.startsWith('yx:draft:v2:')).sort();

await show('RECORD_A','RECORD_B');
await type('RECORD_A','A_PRIVATE_DRAFT');
await type('RECORD_B','B_DIFFERENT_DRAFT');
assert.equal(keys().length,2,'same-title forms for different records use distinct storage keys');
assert.ok(keys().every(k=>k.includes(encodeURIComponent(TITLE))),'title stays in the key');
assert.ok(keys().some(k=>k.includes('RECORD_A'))&&keys().some(k=>k.includes('RECORD_B')));

// Reload: each form offers and restores only its own text.
await hide();await show('RECORD_A','RECORD_B');
assert.ok(button('RECORD_A','恢復暫存文字')&&button('RECORD_B','恢復暫存文字'));
await click('RECORD_A','恢復暫存文字');
assert.equal(text('RECORD_A').value,'A_PRIVATE_DRAFT');
assert.equal(text('RECORD_B').value,'','restoring A must not touch B');
await click('RECORD_B','恢復暫存文字');
assert.equal(text('RECORD_B').value,'B_DIFFERENT_DRAFT');

// Submitting A never carries B's text.
result=false;await submit('RECORD_A');
assert.deepEqual(submitted.at(-1),{record:'RECORD_A',evidence:'A_PRIVATE_DRAFT'});
assert.equal(keys().length,2,'an unsuccessful save keeps the draft');

// Discarding A leaves B intact.
await click('RECORD_A','捨棄暫存');
assert.equal(keys().length,1);
assert.ok(keys()[0].includes('RECORD_B'));
assert.equal(button('RECORD_A','恢復暫存文字'),undefined);
assert.ok(button('RECORD_B','恢復暫存文字'));

// Editing A again must not overwrite B's draft.
await type('RECORD_A','A_SECOND_DRAFT');
assert.equal(keys().length,2);
await hide();await show('RECORD_B');
await click('RECORD_B','恢復暫存文字');
assert.equal(text('RECORD_B').value,'B_DIFFERENT_DRAFT');
await hide();await show('RECORD_A','RECORD_B');

// Successful save of A clears only A.
result=true;await click('RECORD_A','恢復暫存文字');await submit('RECORD_A');
assert.deepEqual(submitted.at(-1),{record:'RECORD_A',evidence:'A_SECOND_DRAFT'});
assert.equal(keys().length,1);
assert.ok(keys()[0].includes('RECORD_B'));
assert.equal(button('RECORD_A','恢復暫存文字'),undefined,'A recovery banner is gone');
assert.ok(button('RECORD_B','恢復暫存文字'),'B recovery remains');
await hide();await show('RECORD_A','RECORD_B');
assert.equal(button('RECORD_A','恢復暫存文字'),undefined);
await click('RECORD_B','恢復暫存文字');
await submit('RECORD_B');
assert.deepEqual(submitted.at(-1),{record:'RECORD_B',evidence:'B_DIFFERENT_DRAFT'});
assert.equal(keys().length,0);

// Version-sensitive: a new revision of the same record has its own draft.
await show({record:'REC',id:'recurring:R1:1'});
await type('REC','REVISION_ONE');
await show({record:'REC',id:'recurring:R1:2'});
assert.equal(button('REC','恢復暫存文字'),undefined,'revision 2 does not offer revision 1 text');
assert.equal(keys().length,1);
// A save started on revision 1 that resolves after the form moved to revision 2 clears only revision 1.
await show({record:'REC',id:'recurring:R1:1'});
let finish;result=new Promise(r=>{finish=r});
await click('REC','恢復暫存文字');await submit('REC');
await type('REC','REVISION_ONE_EDIT');
await show({record:'REC',id:'recurring:R1:2'});
await type('REC','REVISION_TWO');
await act(async()=>{finish(true)});
assert.equal(keys().length,1);
assert.ok(keys()[0].endsWith(encodeURIComponent('recurring:R1:2')),'only the saved revision draft was cleared');
sessionStorage.clear();

// Key separators in title/id cannot make two different forms collide.
await show({record:'X',id:'a:b'},{record:'Y',id:'a%3Ab'});
await type('X','X_TEXT');await type('Y','Y_TEXT');
assert.equal(keys().length,2);

// A form without an identity does not persist at all.
sessionStorage.clear();
await show({record:'NOID',id:''});
await type('NOID','NEVER_STORED');
assert.equal(keys().length,0);
console.log('form draft identity: ok');
