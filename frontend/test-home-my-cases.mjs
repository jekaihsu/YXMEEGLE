import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {JSDOM} from 'jsdom';
const bundle=await build({stdin:{contents:"export {MineCard,caseCoverage} from './src/homeViews/MineCards';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const file=new URL('./.home-my-cases-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);
let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=dashboard',pretendToBeVisual:true});
for(const key of ['window','document','location','history','Event','HTMLElement','localStorage'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const c={go(){},reloadVersion:1,s:{mode:'lark',workspace_id:'w',user:{id:'u1',name:'測試',role:'member'},features:{}},w:{version:1,workspace_id:'w',projects:[],users:[],as_of:'2026-10-27T01:00:00Z'}};
const item=(n)=>({id:`sop_task/${n}`,kind:'sop_task',origin:'sop_local',title:`任務${n}`,status:'todo',source_status:null,case:{id:`case${n}`,code:`LOCAL-${n}`,name:`案件${n}`,relation_state:'verified'},assignees:[],assigned_by:null,assignment_state:'assigned',deadline:null,next_due:null,original_deadline:null,deadline_basis:'sop_task',can_execute:true,blocked_reasons:[],target:{view:'project',project:`case${n}`,tab:'flow',task:`t${n}`,task_source:'sop_local',section:'assigned-sop'},detail:null,overdue:false,due_today:false});
const body=(items,over={})=>({panel:'assigned',scope:'mine',readState:'ready',snapshot_version:'1',as_of:null,freshness:{status:'fresh',last_success_at:null,refreshing:false},counts:{node_assignments:0,tasks:0,local_workflow:0,sop_tasks:items.length,complete:true},items,next_cursor:null,has_more:false,complete:true,total_count:items.length,manager_view_available:null,...over});
async function render(read){
 const host=document.getElementById('root');const root=createRoot(host);
 await act(async()=>root.render(React.createElement(m.MineCard,{id:'mycases',c,today:'2026-10-27',assigned:read,confirmation:{body:null,pending:false,error:null}})));
 const text=host.textContent;await act(async()=>root.unmount());return text;
}
const EMPTY='目前沒有你負責、釘選或有你任務的案件';
let text=await render({body:body([item(1)]),pending:false,error:null});
assert.match(text,/案件1/);assert.doesNotMatch(text,/僅涵蓋|失敗|讀取中/);
text=await render({body:body([]),pending:false,error:null});
assert.match(text,new RegExp(EMPTY),'a complete empty read may say there are no cases');
text=await render({body:body([item(1)],{has_more:true,next_cursor:'c2',total_count:150}),pending:false,error:null});
assert.match(text,/案件1/);assert.match(text,/僅涵蓋已載入的工作/,'cases beyond the first page are flagged as possibly missing');
text=await render({body:body([],{has_more:true,next_cursor:'c2',complete:false}),pending:false,error:null});
assert.doesNotMatch(text,new RegExp(EMPTY),'an incomplete empty page is never shown as no cases');assert.match(text,/僅涵蓋已載入的工作/);
text=await render({body:null,pending:false,error:'更新失敗'});
assert.doesNotMatch(text,new RegExp(EMPTY),'an error is never shown as no cases');assert.match(text,/讀取失敗/);
text=await render({body:body([item(1)]),pending:false,error:'更新失敗'});
assert.match(text,/案件1/,'the last good page stays visible');assert.match(text,/讀取失敗/);
text=await render({body:null,pending:true,error:null});
assert.doesNotMatch(text,new RegExp(EMPTY));assert.match(text,/讀取中/);
text=await render({body:body([],{readState:'disabled'}),pending:false,error:null});
assert.doesNotMatch(text,new RegExp(EMPTY),'a disabled source is not an empty one');
console.log('home my-cases coverage checks passed');
