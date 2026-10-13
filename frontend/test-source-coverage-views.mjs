// Render the production HTTP contract in the real Daily and Documents views.
// The isolated backend fixture contains only synthetic source records.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';

const python=`
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from backend import storage
from backend.app import WorkspaceRow,BusinessRow
from backend.test_public_case_http_boundaries import isolated_http

with TemporaryDirectory() as tmp:
    app,client,_,_=isolated_http.__wrapped__(Path(tmp))
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary')
        state=storage.load(db,BusinessRow,row)
        visible=state['projects'][1]
        visible['daily_reports']=[]
        visible['files']=[]
        visible['source_attachments']=[]
        state['daily_unmatched']=[{'id':'orphan','date':'2026-10-01','description':'GLOBAL_ORPHAN_SENTINEL'}]
        state['source_attachment_index']=[{'id':f'GLOBAL_META_{i}','status':'indexed'} for i in range(42)]
        row.data=storage.save(db,BusinessRow,row.id,state)
    daily_case=client.get('/api/daily-reports',params={'project_id':'p2'}).json()
    daily_all=client.get('/api/daily-reports').json()
    full_zero=client.get('/api/workspace').json()
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary')
        state=storage.load(db,BusinessRow,row)
        visible=state['projects'][1]
        visible['source_attachments']=[
            {'id':'meta-indexed','name':'CASE_METADATA_ONE','status':'indexed','source_field':'來源附件'},
            {'id':'meta-missing','name':'CASE_METADATA_TWO','status':'source_missing','source_field':'來源附件'},
            {'id':'meta-unavailable','name':'CASE_METADATA_THREE','status':'metadata_unavailable','source_field':'來源附件'},
        ]
        visible['files']=[{'id':'file-v1','name':'WORKBENCH_VERSION','node_id':'','direction':'input',
            'category_id':'photo','file_key':'file-key','version':1,'uploaded_by':'u-manager',
            'created_at':'2026-10-01','size':10,'url':'','storage':'link'}]
        row.data=storage.save(db,BusinessRow,row.id,state)
    full_metadata=client.get('/api/workspace').json()
    print(json.dumps({'daily_case':daily_case,'daily_all':daily_all,
        'full_zero':full_zero,'full_metadata':full_metadata},ensure_ascii=False))
`;
const generated=spawnSync('/Users/vc/Local/run/yxs3-demo/venv/bin/python',['-c',python],{cwd:new URL('..',import.meta.url).pathname,encoding:'utf8'});
assert.equal(generated.status,0,generated.stderr);
const fixture=JSON.parse(generated.stdout);
const zero=fixture.full_zero.projects[0], metadata=fixture.full_metadata.projects[0];
assert.equal(fixture.daily_case.total,0);
assert.equal(fixture.daily_all.total,0);
assert.deepEqual(fixture.daily_all.coverage,{scope:'visible_cases',project_only:false,unmatched_available:false});
assert.equal(zero.source_attachment_coverage.metadata_records,0);
assert.equal(metadata.source_attachment_coverage.metadata_records,3);
assert.equal(metadata.source_attachment_coverage.workspace_versions,1);
assert.ok(!JSON.stringify(fixture.full_metadata).includes('GLOBAL_META_'));

const bundle=await build({stdin:{contents:"export {DailyRecords} from './DailyRecords'; export {FilePanel} from './FileWorkspace';",resolveDir:new URL('./src/',import.meta.url).pathname,sourcefile:'coverage-entry.ts'},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'}});
const bundlePath=new URL('./.source-coverage-bundle.mjs',import.meta.url);
await fs.writeFile(bundlePath,bundle.outputFiles[0].text);
let DailyRecords,FilePanel;
try{({DailyRecords,FilePanel}=await import(bundlePath.href))}finally{await fs.unlink(bundlePath)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','location','history','sessionStorage','localStorage','Event','HTMLElement','HTMLSelectElement','File','FormData'])Object.defineProperty(globalThis,key,{configurable:true,value:dom.window[key]});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const root=createRoot(document.getElementById('root'));
const tick=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,20))});
globalThis.fetch=async url=>{
 const query=new URL(String(url),'http://localhost').searchParams;
 const response=query.has('project_id')?fixture.daily_case:fixture.daily_all;
 return new Response(JSON.stringify(response),{status:200,headers:{'content-type':'application/json'}});
};
await act(async()=>{root.render(React.createElement(DailyRecords,{w:fixture.full_zero,p:zero,go:()=>{}}));await new Promise(resolve=>setTimeout(resolve,20))});
await tick();
assert.match(document.querySelector('.daily-records').textContent,/本案範圍尚無可見的已配對日報/);
assert.match(document.querySelector('.daily-records').textContent,/未配對的來源日報不在此範圍/);
assert.ok(!document.querySelector('option[value="unmatched"]'));
assert.ok(!document.querySelector('.daily-records').textContent.includes('535'));
assert.ok(!document.querySelector('.daily-records').textContent.includes('GLOBAL_ORPHAN_SENTINEL'));
const range=document.querySelector('.daily-records select');
await act(async()=>{range.value='all';range.dispatchEvent(new dom.window.Event('change',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,20))});
await tick();
assert.match(document.querySelector('.daily-records').textContent,/全部可見案件日報/);
assert.ok(!document.querySelector('option[value="unmatched"]'));

const demoCase={...fixture.daily_case,coverage:{scope:'workspace',project_only:true,unmatched_available:false}};
const demoUnmatched={...fixture.daily_case,items:[{id:'demo-orphan',date:'2026-10-01',description:'DEMO_UNMATCHED',project_id:null}],total:1,summary:{matched:0,unmatched:1,source_missing:0},coverage:{scope:'workspace',project_only:false,unmatched_available:true}};
globalThis.fetch=async url=>{
 const query=new URL(String(url),'http://localhost').searchParams;
 return new Response(JSON.stringify(query.get('status')==='unmatched'?demoUnmatched:demoCase),{status:200,headers:{'content-type':'application/json'}});
};
await act(async()=>{root.render(React.createElement(DailyRecords,{key:'demo',w:{...fixture.full_zero,environment:'demo'},p:zero,go:()=>{}}));await new Promise(resolve=>setTimeout(resolve,20))});
await tick();
const demoRange=document.querySelector('.daily-records select');
assert.ok(document.querySelector('option[value="unmatched"]'),'demo workspace offers unmatched without first visiting All');
await act(async()=>{demoRange.value='unmatched';demoRange.dispatchEvent(new dom.window.Event('change',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,20))});
await tick();
assert.match(document.querySelector('.daily-cards').textContent,/DEMO_UNMATCHED/);

const context={w:fixture.full_zero,s:{},busy:false,error:'',refresh:async()=>{},run:async()=>undefined,upload:async()=>false};
await act(async()=>root.render(React.createElement(FilePanel,{c:context,p:zero})));
let content=document.querySelector('.file-workspace').textContent;
assert.match(content,/本案已配對的 Lark 來源附件索引 0 筆/);
assert.match(content,/本案尚無可列出的來源附件索引/);
assert.match(content,/來源附件欄位覆蓋未回報/);
assert.match(content,/附件內容存取權限未核實/);
assert.ok(!content.includes('42'));
assert.ok(!document.querySelector('.source-attachment-index'));
await act(async()=>root.render(React.createElement(FilePanel,{c:{...context,w:fixture.full_metadata},p:metadata})));
content=document.querySelector('.file-workspace').textContent;
assert.match(content,/本案工作台 1 筆版本/);
assert.match(content,/本案已配對的 Lark 來源附件索引 3 筆/);
assert.match(content,/CASE_METADATA_ONE/);
assert.match(content,/來源已移除，保留索引/);
assert.match(content,/來源中繼資料待核對/);
assert.ok(!content.includes('42'));
const category=document.querySelector('.file-workspace select');
await act(async()=>{category.value='report';category.dispatchEvent(new dom.window.Event('change',{bubbles:true}))});
content=document.querySelector('.file-workspace').textContent;
assert.match(content,/目前篩選顯示 0 筆版本/);
assert.match(content,/本案已配對的來源附件索引另列如下/);
assert.match(content,/CASE_METADATA_ONE/);
await act(async()=>root.unmount());
dom.window.close();
console.log('Source coverage views: production Daily scope and case-only Documents metadata render correctly');
