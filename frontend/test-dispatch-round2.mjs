import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {Simulate} from 'react-dom/test-utils';
import {JSDOM} from 'jsdom';
import {response} from './qa/dispatch-api-examples.mjs';
const bundle=await build({stdin:{contents:"export * from './src/dispatchPublishModel';export {DispatchPublishDialog} from './src/DispatchPublishDialog';export {DispatchWork} from './src/DispatchWork';export {invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.dispatch-round2-test.mjs',import.meta.url);await fs.writeFile(temp,bundle.outputFiles[0].text);let m;try{m=await import(temp.href)}finally{await fs.unlink(temp)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/',pretendToBeVisual:true});
for(const k of ['window','document','Event','HTMLElement','Element','Node'])globalThis[k]=dom.window[k];
globalThis.getComputedStyle=dom.window.getComputedStyle;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const root=createRoot(document.getElementById('root')),settle=()=>new Promise(r=>setTimeout(r,0));
const session={workspace_id:'company',mode:'lark',user:{id:'ou_pm',role:'pm'}};
const original=response('decision: PM final accepts');original.expires_at='2099-01-01T00:00:00Z';
const task=response('assign form for an existing task');task.proposal.parent_task_ref='recObligation001';const proposal=m.normalizeProposal(original.proposal);
let calls=[],saved=[],workStatus=200;
globalThis.fetch=async(url,init={})=>{
 const body=init.body?JSON.parse(init.body):null;calls.push({url,body});let status=200,result={};
 if(url.includes('/options'))result=response('picker options');
 else if(url.includes('/tasks/'))result=task;
 else if(url.includes('/previews'))result=original;
 else if(url.includes('/commands/'))result={command:{command_id:'cmd-recovery',state:url.endsWith('/reconcile')?'failed':'outcome_unknown',task_id:'recTask0001',proposal:task.proposal},next_action:'reconcile'};
 else if(url.includes('/drafts/'))result={draft_id:'draft-r2',version:2,proposal:body?.proposal??proposal};
 else if(url.includes('/dispatch/work')){status=workStatus;result=status===200?response('work queue: PM'):{code:'forbidden'}}
 return new Response(JSON.stringify(result),{status,headers:{'Content-Type':'application/json'}});
};
const mount=async(key,flow,actor=session)=>act(async()=>{root.render(React.createElement(m.DispatchPublishDialog,{key,flow,session:actor,onClose(){},onSaved:d=>saved.push(d),onPublished(){}}));await settle()});
const click=async(text)=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent===text);assert.ok(b,`button ${text}`);assert.equal(b.disabled,false,`${text} enabled`);await act(async()=>{b.click();await settle()})};
let failures=0;
async function test(name,fn){try{await fn();console.log(`PASS ${name}`)}catch(error){failures++;console.error(`FAIL ${name}: ${error.message}`)}}
await test('R1 saved proposal wins over approved preview and approvals are void',async()=>{
 await mount('r1-edit',{proposal,action:'review_preview',row:{preview_id:original.preview_id}});
 const input=document.querySelector('.dp-verification textarea');
 await act(async()=>{input.value='修改後的核實原因';Simulate.change(input);await settle()});
 await click('儲存草稿');const changedDraft=saved.at(-1);
 assert.equal(changedDraft.proposal.manual_verifications['person:recP3'],'修改後的核實原因',JSON.stringify(changedDraft.proposal.manual_verifications));
 await mount('r1-reopen',{proposal,action:'new',draft:changedDraft});
 assert.equal(document.querySelector('.dp-verification textarea').value,'修改後的核實原因');
 assert.equal([...document.querySelectorAll('button')].find(b=>b.textContent==='發布排班').disabled,true);
 assert.equal(document.querySelectorAll('.dp-seat').length,3);
 assert.equal(document.querySelectorAll('.dp-seat p')[0].textContent.includes('先前核准已失效'),true);
 await click('儲存草稿');assert.equal(calls.at(-1).body.proposal.verifications['person:recP3'],'修改後的核實原因');
});
await test('R2 failed reconciliation restores options task and parent obligation',async()=>{
 calls=[];await mount('r2',{proposal:m.normalizeProposal({}),row:{task_id:'recTask0001',command:{command_id:'cmd-recovery'}},action:'reconcile'},{...session,user:{id:'ou_mgr',role:'manager'}});
 await click('重新對帳');await click('修改後重新預覽');
 assert.equal(document.querySelector('select option[value="recP2"]').textContent,'乙');
 assert.equal(document.querySelector('input[readonly]')?.value??[...document.querySelectorAll('label')].find(l=>l.textContent==='父義務').querySelector('input').value,'recObligation001');
 await click('檢核並預覽');assert.equal(calls.at(-1).body.task_id,'recTask0001');assert.equal(calls.at(-1).body.parent_task_ref,'recObligation001');
});
await test('R3 seat holder sees every hashed proposal field and exclusive interval',async()=>{
 await mount('r3',{proposal,action:'approve',row:{preview_id:original.preview_id,case:{ref:'recCase1',code:'SYN-001',name:'合成示範案'}}},{...session,user:{id:'ou_lead',role:'member'}});
 const fields=Object.fromEntries([...document.querySelectorAll('.dp-proposal-summary dl>div')].map(d=>[d.querySelector('dt').textContent,d.querySelector('dd').textContent]));
 assert.equal(fields['工作內容'],'B 區水深測量');assert.equal(fields['預定開始'],'2026-10-20T08:00+08:00');assert.equal(fields['預定結束'],'2026-10-20T12:00+08:00');
 assert.equal(fields['負責人'],'丙');assert.equal(fields['工程確認單'],'SYN-001 · 合成示範案');
 assert.equal(document.querySelector('.dp-proposal-summary').textContent.includes('結束時間不含在本工作時段內'),true);
 assert.equal(Object.keys(fields).length,20);
});
await test('R4 absent hours stay null omitted and show estimation hint',async()=>{
 const p=m.normalizeProposal({...proposal,est_person_hours:null});assert.equal(p.est_person_hours,null);assert.equal(Object.hasOwn(m.proposalBody(p),'est_person_hours'),false);assert.equal(m.proposalBody(m.normalizeProposal({...proposal,est_person_hours:0})).est_person_hours,0);assert.deepEqual(m.validateProposal(p),[]);
 await mount('r4',{proposal:p,action:'new'});assert.equal(document.querySelector('input[type=number]').value,'');assert.equal(document.body.textContent.includes('系統依組員與時段估算'),true);
});
await test('R5 unresolved display names never expose record IDs',async()=>{
 assert.equal(m.parseOptions({people:[],instruments:[{ref:'recSecret'}],vehicles:[],cases:[]}).instruments[0].label,'名稱未能解析');
 assert.equal(m.parsePreview({...original,crew:[{person_ref:'recSecret'}],resources:[]}).feasibility[0].label,'名稱未能解析');
 await mount('r5',{proposal,action:'approve',row:{preview_id:original.preview_id}});assert.equal(document.querySelector('.dp-proposal-summary')?.textContent.includes('rec'),false);
});
const renderWork=async(refreshVersion)=>act(async()=>{root.render(React.createElement(m.DispatchWork,{from:'2026-10-19',write:true,refreshVersion,onProposal(){},onAction(){}}));await settle()});
await test('R6 forbidden read clears open detail and actions',async()=>{
 await renderWork(0);await act(async()=>{document.querySelector('.dp-work-open').click();await settle()});assert.equal(document.querySelectorAll('[role=dialog]').length,1);
 workStatus=403;await click('更新工作進度');assert.equal(document.querySelector('.dp-source').textContent,'沒有工作進度的檢視權限。');assert.equal(document.querySelectorAll('[role=dialog]').length,0);
 workStatus=200;await click('更新工作進度');assert.equal(document.querySelector('.dp-progress').textContent.includes('9 件'),true);assert.equal(document.querySelectorAll('[role=dialog]').length,0);
});
await test('R6 identity epoch clears open detail before new read',async()=>{
 workStatus=200;await renderWork(1);await act(async()=>{document.querySelector('.dp-work-open').click();await settle()});assert.equal(document.querySelectorAll('[role=dialog]').length,1);
 m.invalidateSessionEpoch();await renderWork(1);assert.equal(document.querySelectorAll('[role=dialog]').length,0);
});
await test('wire errors use plain Chinese and receipt reasons survive parsing',async()=>{
 assert.equal(m.blockerLabel('decision_holder_changed:manager_review'),'核准席位持有人已變更，請由現任持有人重新核准 · 經理審核');
 assert.equal(m.blockerLabel('department_not_node_group'),'所選部門不屬於此任務節點的組別，請重新選擇');
 assert.equal(m.blockerLabel('own_preview'),'提案人不能核准自己的組長或經理席位，請由其他持有人核准');
 assert.equal(m.blockerLabel('recheck_unavailable'),'發布前無法重新讀取資料，請稍後重試');
 assert.equal(m.blockerLabel('unknown_department'),'部門不在現有人員名冊中，請重新選擇');
 assert.equal(m.blockerLabel('search_lag'),'命令搜尋尚未同步，請稍後以原命令重新對帳');
 assert.equal(m.blockerLabel(m.parseCommand({command:{command_id:'reason',state:'reconciliation_required'},receipt:{reason:'no_base_snapshot'}}).issue),'缺少發布前的任務快照，無法安全重送，請人工核對');
 globalThis.fetch=async()=>new Response(JSON.stringify({code:'invalid',field:'department',detail:'Unknown department'}),{status:422});
 await assert.rejects(m.dispatchRequest(m.dispatchPaths.previews,new AbortController().signal,{}),error=>error.status===422&&error.message.startsWith('部門不在現有人員名冊中，請重新選擇'));
});
await act(async()=>root.unmount());
if(failures)process.exitCode=1;
