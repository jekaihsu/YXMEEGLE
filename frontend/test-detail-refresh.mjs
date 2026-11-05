import assert from 'node:assert/strict';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {assignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','Event','HTMLElement','HTMLSelectElement'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export * from './src/detailRefresh';export * from './src/useNodeAssignments';export * from './src/useSopTasks';export * from './src/useProjectProgress';export {api,invalidateSessionEpoch} from './src/api';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const temp=new URL('./.detail-refresh-test.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const ui=await import(temp.href);await unlink(temp);
const fixture=assignmentFixture(),progress=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
progress.project_id='p1';
const examples=JSON.parse(await readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8'));
const initial=structuredClone(examples.sop_tasks);initial.tasks[0].lark_sync={state:'同步中'};
let overview=initial,reads=[],assignment, sop, evidence,refresh,revision=0,blocked=false,hold=null,fail=false,mutationHold=null;
const response=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
globalThis.fetch=async(url,init={})=>{
 if(init.method&&init.method!=='GET'){if(mutationHold)await mutationHold;return response({...fixture.detail,record_id:fixture.detail.node.record_id})}
 reads.push(url);const captured=structuredClone(url.endsWith('/sop-tasks')?overview:url.endsWith('/sop-assignees')?examples.assignees:url.endsWith('/progress')?progress:fixture.list);
 if(hold)await hold;
 if(fail)return response({detail:'offline'},503);
 return response(captured);
};
function Probe(){
 assignment=ui.useNodeAssignments('p1',true);sop=ui.useSopTasks('p1','w1');evidence=ui.useProjectProgress('p1');
 const reload=React.useCallback(()=>ui.api('/api/projects/p1'),[]);refresh=ui.useDetailRefresh(reload,true,'',false,true);
 return React.createElement('output',null,JSON.stringify({assignment:assignment.state.kind,sop:sop.state.kind,progress:evidence.state.kind}));
}
function MoreProgress(){ui.useProjectProgress('p1');return null}
function Tree(){return React.createElement(ui.DetailRefreshProvider,{revision,canRefresh:()=>!blocked},React.createElement(React.Fragment,null,React.createElement(Probe),React.createElement(MoreProgress)))}
const originalNow=Date.now,originalInterval=globalThis.setInterval,originalWindowInterval=window.setInterval;
let now=100000,intervals=[];Date.now=()=>now;
globalThis.setInterval=window.setInterval=(fn,ms)=>{intervals.push({fn,ms});return intervals.length};
Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
const visibility=state=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:state});document.dispatchEvent(new Event('visibilitychange'))};
const flush=fn=>act(async()=>{fn?.();await new Promise(resolve=>setTimeout(resolve,0))});
const leave=()=>flush(()=>{window.dispatchEvent(new Event('blur'));visibility('hidden')});
const back=()=>flush(()=>{visibility('visible');window.dispatchEvent(new Event('focus'))});
const root=createRoot(document.getElementById('root'));
try{
 ui.invalidateSessionEpoch();await flush(()=>root.render(React.createElement(Tree)));
 assert.equal(reads.length,4);assert.equal(intervals.length,0);
 const baseline=reads.length;
 await flush(()=>{now+=600000;for(const timer of intervals)for(let elapsed=timer.ms;elapsed<=600000;elapsed+=timer.ms)timer.fn()});
 assert.equal(reads.length-baseline,0);
 await flush(()=>{window.dispatchEvent(new Event('focus'));visibility('visible')});assert.equal(reads.length,4);
 await leave();now+=59999;await back();assert.equal(reads.length,4);
 await leave();now+=60000;await back();assert.equal(reads.length,4,'>=60s return stays at four initial reads');
 await flush(()=>window.dispatchEvent(new Event('focus')));assert.equal(reads.length,4);
 await flush(()=>window.dispatchEvent(new Event('blur')));now+=600000;blocked=true;
 await flush(()=>window.dispatchEvent(new Event('focus')));assert.equal(reads.length,4);
 blocked=false;await flush(()=>root.render(React.createElement(Tree)));assert.equal(reads.length,4,'focus never creates deferred work');
 // Save while the dialog itself blocks the reload guard.
 const dialog=document.createElement('div');dialog.setAttribute('role','dialog');dialog.innerHTML='<input type="date">';document.body.append(dialog);
 blocked=true;let saved=false;const beforeSave=reads.length;
 await flush(()=>{void assignment.mutate({action:'update_task',nodeKey:'control',taskId:'recTask1',expected_revision:'9b0c1d2e3f405162',patch:{assignee_open_id:'ou_anna'}}).then(ok=>{saved=ok;if(ok)dialog.remove()})});
 assert.equal(saved,true,'drawer save settles while reload guard is blocked');assert.equal(dialog.isConnected,false);
 assert.equal(reads.length-beforeSave,1,'assignment response seeds detail/list; only progress is read');
 const beforeSop=reads.length;
 overview=structuredClone(initial);overview.tasks[0].lark_sync={state:'已同步',record_id:'recDone',base_id:'base',table_id:'table'};
 let sopDone=false;await flush(()=>{void sop.reload().then(()=>{sopDone=true})});
 assert.equal(sopDone,true,'SOP writer completes inside cleanup drawer');
 assert.equal(reads.length-beforeSop,2,'SOP write reads tasks and progress only');assert.equal(sop.state.data.tasks[0].larkSync.state,'已同步');
 blocked=false;const beforeExplicit=reads.length;
 await flush(()=>{void refresh(false)});assert.equal(reads.length-beforeExplicit,5);
 const beforeMutation=reads.length;
 let releaseMutation;mutationHold=new Promise(resolve=>releaseMutation=resolve);
 let writing;await flush(()=>{writing=ui.api('/api/projects/p1/test-write',{method:'POST'})});
 await leave();now+=60000;await back();assert.equal(reads.length,beforeMutation);
 mutationHold=null;await flush(()=>releaseMutation());await writing;await flush();
 assert.equal(reads.length,beforeMutation,'return during mutation never creates deferred work');
 fail=true;await flush(()=>{void refresh(false)});await flush();
 assert.equal(assignment.state.kind,'error');assert.equal(sop.state.kind,'error');assert.equal(evidence.state.kind,'ready');
 assert.equal(document.body.textContent.includes('工程進度更新失敗，顯示上次資料'),true);
 console.log('PASS drawer writes: assignment follow-up GETs=1; SOP follow-up GETs=2; guard cannot hold writer completion. Detail refresh: 10 idle minutes = 0 extra fetches; <60s away = 0; >=60s + visibility/focus = 0 fetches; explicit refresh rereads all; targeted own writes; loading retains data; failures label retained progress; ');
}finally{await act(async()=>root.unmount());Date.now=originalNow;globalThis.setInterval=originalInterval;window.setInterval=originalWindowInterval;dom.window.close()}
