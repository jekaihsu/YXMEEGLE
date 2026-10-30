import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {JSDOM} from 'jsdom';
import {example,response} from './qa/dispatch-api-examples.mjs';
const bundle=await build({stdin:{contents:"export {DispatchPublishDialog} from './src/DispatchPublishDialog';export {DispatchWork,WorkDetail} from './src/DispatchWork';export {canReadDispatch,canWriteDispatch} from './src/dispatchAccess';export {parseWork,parseTaskForm} from './src/dispatchPublishModel';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm',packages:'external',loader:{'.css':'empty'}});
const temp=new URL('./.dispatch-publish-ui-test.mjs',import.meta.url);await fs.writeFile(temp,bundle.outputFiles[0].text);let m;try{m=await import(temp.href)}finally{await fs.unlink(temp)}
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#view=dispatch',pretendToBeVisual:true});
for(const k of ['window','document','Event','HTMLElement','Element','Node'])globalThis[k]=dom.window[k];
globalThis.getComputedStyle=dom.window.getComputedStyle;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const root=createRoot(document.getElementById('root'));
const session={workspace_id:'company',mode:'lark',features:{dispatch_board:true,dispatch_write:true},user:{id:'ou_pm',role:'pm'}};
assert.equal(m.canWriteDispatch(session),true);
assert.equal(m.canWriteDispatch({...session,features:{dispatch_board:true}}),false);
assert.equal(m.canWriteDispatch({...session,user:{role:'member'}}),false);
assert.equal(m.canReadDispatch({...session,user:{id:'ou_lead',role:'member'}}),true);
assert.equal(m.canWriteDispatch({...session,workspace_id:'test-company'}),false);
const row=m.parseWork(response('work queue: PM')).rows.find(r=>r.task_id==='recTask0001'),proposal=m.parseTaskForm(response('assign form for an existing task')).proposal;
let saved=[],calls=[],commitExample='commit: timeout after remote success is outcome_unknown (202)',workStatus=200,commitStatus=202,commandStatus=200,saveConflict=false,decisionConflict=false;
let testActor=session;
let previewBody=response('decision: PM final accepts');
globalThis.fetch=async(url,init={})=>{
 const call={url,method:init.method??'GET',body:init.body?JSON.parse(init.body):null};calls.push(call);
 let status=200,body={};
 if(url.includes('/options'))body=response('picker options');
 else if(url.includes('/tasks/'))body=response('assign form for an existing task');
 else if(decisionConflict&&url.endsWith('/decisions')){status=409;body=response('decision refused: wrong order')}
 else if(url.includes('/previews'))body={...structuredClone(previewBody),...(testActor.user.id==='ou_lead'?{my_seats:response('decision: group leader accepts').my_seats}:{}),...(init.method==='POST'&&!url.endsWith('/decisions')?{proposal:{...previewBody.proposal,task_id:call.body.task_id}}:{}),expires_at:'2099-01-01T00:00:00Z'};
 else if(url.endsWith('/commits')){body=response(commitExample);status=commitStatus;if(body.command)body.command.command_id=call.body.command_id}
 else if(url.includes('/commands/')){status=commandStatus;body=response(url.endsWith('/reconcile')?'reconcile: row found by 命令編號, committed':'command status for a manager: reconcile offered');body.command.command_id=url.split('/')[4]}
 else if(url.includes('/drafts/')){status=saveConflict?409:200;body=response(saveConflict?'draft: save with a stale version':'draft: save')}
 else if(url.includes('/dispatch/work')){status=workStatus;body=status===200?response('work queue: PM'):{detail:'來源暫時失敗',code:'sources_unavailable'}}
 return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
};
const settle=()=>new Promise(r=>setTimeout(r,0));
const mount=async(key='one',override={},actor=session)=>act(async()=>{testActor=actor;root.render(React.createElement(m.DispatchPublishDialog,{key,flow:{proposal,row,action:'reassign',...override},session:actor,onClose(){},onSaved:d=>saved.push(d),onPublished(){}}));await settle()});
const click=async(text)=>{const b=[...document.querySelectorAll('button')].find(b=>b.textContent===text);assert.ok(b,`button ${text}`);assert.equal(b.disabled,false,`${text} enabled`);await act(async()=>{b.click();await settle()})};
const inactive=response('picker options').people.find(p=>p.active===false);
await mount('inactive',{row:undefined,action:'new',proposal:{...proposal,crew:[...proposal.crew,inactive.person_ref]}});
const inactiveCheck=[...document.querySelectorAll('.dp-picker label')].find(label=>label.textContent.includes(inactive.name)).querySelector('input');
assert.equal(inactiveCheck.checked,true);assert.equal(inactiveCheck.disabled,false);await act(async()=>{inactiveCheck.click();await settle()});assert.equal(inactiveCheck.checked,false);
await mount();assert.ok(calls.some(c=>c.url.endsWith('/options')));assert.ok(calls.some(c=>c.url.endsWith('/tasks/recTask0001')));
assert.equal(document.querySelector('input[readonly]').value,proposal.parent_task_ref);
assert.ok(document.body.textContent.includes('無 Lark 帳號'));assert.ok(document.body.textContent.includes('SYN-001'));
await click('儲存草稿');assert.equal(calls.at(-1).method,'PUT');assert.equal('manual_verifications' in calls.at(-1).body.proposal,false);assert.equal(saved.at(-1).version,1);
saveConflict=true;await click('儲存草稿');assert.equal(calls.at(-1).body.version,1);assert.ok(document.body.textContent.includes('草稿已在其他地方更新'));saveConflict=false;
await click('檢核並預覽');assert.equal(calls.at(-1).body.task_id,'recTask0001');assert.equal(calls.at(-1).body.phase,'formal');assert.ok(document.body.textContent.includes('8 人時'));
await click('查看核准席位');await click('發布排班');assert.ok(document.body.textContent.includes('結果不明'));
const commandId=calls.findLast(c=>c.url.endsWith('/commits')).body.command_id;
assert.match(commandId,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);assert.equal(saved.at(-1).command_id,commandId);
await click('查詢命令進度');assert.ok(document.body.textContent.includes('尚不確定遠端任務是否寫入'));
await mount('restored',{action:'reconcile',draft:saved.at(-1)},{...session,user:{id:'ou_mgr',role:'manager'}});
await click('重新對帳');assert.ok(document.body.textContent.includes('任務寫入後已讀回核對成功'));
commitExample='commit refused: concurrent overlapping commit lost the reservation race';commitStatus=409;
await mount('conflict');await click('檢核並預覽');await click('查看核准席位');await click('發布排班');assert.ok(document.body.textContent.includes('草稿已保留'));assert.equal(saved.at(-1).command_id,'');assert.equal(saved.at(-1).proposal.task_id,'recTask0001');await click('返回編輯');
commitExample='commit: committed after read-back';commitStatus=503;
await mount('retry');await click('檢核並預覽');await click('查看核准席位');await click('發布排班');const retryId=calls.findLast(c=>c.url.endsWith('/commits')).body.command_id;
commandStatus=404;await mount('retry-restored',{draft:saved.at(-1)});commitStatus=200;commandStatus=200;await click('重試同一命令');assert.equal(calls.findLast(c=>c.url.endsWith('/commits')).body.command_id,retryId);assert.ok(document.body.textContent.includes('任務寫入後已讀回核對成功'));
commitExample='commit refused: another command for a live preview';commitStatus=409;
await mount('duplicate');await click('檢核並預覽');await click('查看核准席位');await click('發布排班');assert.ok(calls.at(-1).url.endsWith(response(commitExample).command_id));assert.equal(saved.at(-1).command_id,response(commitExample).command_id);
previewBody=response('preview: verified crew, waiting for approval seats');
await mount('member-seat',{action:'approve',row:{...row,preview_id:previewBody.preview_id}},{...session,user:{id:'ou_lead',role:'member'}});
decisionConflict=true;await click('核准此席');assert.ok(document.body.textContent.includes('前一席尚未核准'));decisionConflict=false;
await click('核准此席');assert.equal(calls.at(-1).body.seat,'group_leader_confirmed');assert.equal(calls.at(-1).body.decision,'accepted');
await act(async()=>{root.render(React.createElement(m.DispatchWork,{from:'2026-10-19',write:false,onProposal(){},onAction(){}}));await settle()});
assert.ok(document.querySelector('.dp-progress').textContent.includes('9 件'));assert.ok(document.body.textContent.includes('預覽提案'));assert.equal(document.querySelectorAll('.dp-needs .dp-work-row').length,3);
const scopeSelect=document.querySelector('.dp-filters select');await act(async()=>{scopeSelect.value='all';scopeSelect.dispatchEvent(new Event('change',{bubbles:true}));await settle()});
await act(async()=>{root.render(React.createElement(m.DispatchWork,{from:'2026-10-19',write:false,refreshVersion:1,onProposal(){},onAction(){}}));await settle()});assert.equal(document.querySelector('.dp-filters select').value,'all');assert.ok(calls.at(-1).url.includes('scope=all'));
workStatus=503;await click('更新工作進度');assert.ok(document.querySelector('.dp-source').textContent.includes('保留上次成功快照'));assert.ok(document.querySelector('.dp-progress').textContent.includes('9 件'));
workStatus=403;await click('更新工作進度');assert.equal(document.querySelectorAll('.dp-work-row').length,0);assert.equal(document.querySelector('.dp-progress').textContent,'進度 · —');
await act(async()=>root.render(React.createElement(m.WorkDetail,{row,write:true,onClose(){},onAction(){}})));assert.equal(document.querySelectorAll('.dp-fields dt').length,26);assert.ok(document.body.textContent.includes('讀回時間（系統唯讀）'));
await act(async()=>root.unmount());
console.log('dispatch publish UI passed with captured options, task prefill, drafts, member seats, UUID retry, 409/503, reconciliation and all 21 fields');
