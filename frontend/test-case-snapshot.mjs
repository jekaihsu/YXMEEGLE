import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {projectFixture,assignmentFixture} from './fixtures/node-assignments.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true});
for(const key of ['window','document','location','history','sessionStorage','Event','HTMLElement','navigator'])Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const React=await import('react'),{act}=React,{createRoot}=await import('react-dom/client');
const bundle=await build({stdin:{contents:"export {ProjectDetailGate} from './src/ProjectDetail';export {invalidateSessionEpoch} from './src/api';export {createPageData} from './src/pageData';export {readCase} from './src/detailRefresh';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',jsx:'automatic',packages:'external',loader:{'.css':'empty'},plugins:[{name:'observe-case-owner',setup(b){b.onLoad({filter:/\/ProjectDetail\.tsx$/},async({path})=>({contents:(await fs.readFile(path,'utf8')).replace(' const owner=useCaseData();',' const owner=useCaseData();window.caseOwner=owner;'),loader:'tsx'}))}}]});
const temp=new URL('./.case-snapshot-test.mjs',import.meta.url);await fs.writeFile(temp,bundle.outputFiles[0].text);let ui;try{ui=await import(temp.href)}finally{await fs.unlink(temp)}
const {project,user,workspace}=projectFixture();project.source_kind='lark';
const assignments=assignmentFixture().list;assignments.node_details=Object.fromEntries(assignments.nodes.map(n=>[n.key,{tasks:[],assignable_people:[]} ]));
const examples=JSON.parse(await fs.readFile(new URL('../backend/sop_import/api-examples.json',import.meta.url),'utf8'));
const progress=JSON.parse(await fs.readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));progress.project_id=project.id;
const start={project_id:project.id,code:project.code,eligible:false,can_start:false,already_started:true,seeds_pending:0,seeds_optional:false,blockers:[],warnings:[],nodes:[],chain_note:'',preview_hash:'h1',plan_rule_version:'v1'};
const snapshot={snapshot_id:'snapshot-41',as_of:'2026-10-01T00:00:00Z',fetched_at:'2026-10-02T00:00:00Z',verified_at:'2026-11-02T00:00:00Z',local_revision:41,completeness:'partial',stale:true};
const payload={project:{...workspace,scope:'project',project},snapshot,assignments:{status:200,body:assignments,snapshot},tasks:{status:200,body:examples.sop_tasks,snapshot},start:{status:200,body:start,snapshot}};
let fail=false,revision=0,hold=false,release;
const requests=[];
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
globalThis.fetch=async url=>{
 requests.push(url);
 if(url.endsWith('/first-screen')){if(hold)await new Promise(resolve=>release=resolve);return fail?json({detail:'offline'},503):json(payload)}
 if(url.endsWith('/progress'))return json(progress);
 if(url.endsWith('/sop-assignees'))return json(examples.assignees);
 throw Error('Unexpected resource '+url);
};
const root=createRoot(document.getElementById('root'));
const c={w:{...workspace,scope:'shell'},s:{user,workspace_id:'offline',features:{node_assignment:true}},route:{view:'project',project:'p1',tab:'overview'},go(){},registerDrafts(){},notify(){}};
const render=()=>act(async()=>root.render(React.createElement(React.StrictMode,null,React.createElement(ui.ProjectDetailGate,{c:{...c,reloadVersion:revision}}))));
try{
 await render();assert.equal(requests.length,3);
 assert.equal(document.querySelector('[data-snapshot-id]').dataset.snapshotId,'snapshot-41');
 const label=()=>document.querySelector('[data-snapshot-id]').textContent;
 assert.match(label(),/資料時間 2026\/10\/01/);assert.match(label(),/資料待更新.*部分資料/);assert.doesNotMatch(label(),/2026\/11\/02/,'wire verification time never replaces source as_of');
 const ready=window.caseOwner.state({endpoint:'project:p1:true'});assert.equal(ready.value.fetchedAt,snapshot.fetched_at);assert.equal(ready.value.snapshotId,snapshot.snapshot_id);
 fail=true;revision++;await render();
 const failed=window.caseOwner.state({endpoint:'project:p1:true'});assert.equal(failed.kind,'Error');assert.equal(failed.previous.fetchedAt,snapshot.fetched_at);assert.equal(failed.previous.snapshotId,snapshot.snapshot_id);
 assert.match(document.body.textContent,new RegExp(project.name));assert.match(document.body.textContent,/案件更新失敗/);assert.match(label(),/資料時間 2026\/10\/01.*資料待更新/);
 // Grants change without a user-ID change must discard the old case owner's rows.
 const old=window.caseOwner;c.s={...c.s,user:{...user,capabilities:['different-grant'],authz_version:2}};hold=true;fail=false;await render();
 assert.notEqual(window.caseOwner,old);assert.equal(document.querySelector('.cs-summary'),null,'new grants cannot paint old detail rows while the new read is blocked');assert.equal(document.querySelector('[data-snapshot-id]'),null);
 hold=false;await act(async()=>release());assert.match(document.body.textContent,new RegExp(project.name));
 const beforeEpoch=window.caseOwner,beforeEpochReads=requests.length;revision++;await act(async()=>{ui.invalidateSessionEpoch();root.render(React.createElement(React.StrictMode,null,React.createElement(ui.ProjectDetailGate,{c:{...c,reloadVersion:revision}})))});assert.equal(requests.length-beforeEpochReads,4,'initial scope read and subsequent authorized revision read settle without duplicating seeded readers');assert.notEqual(window.caseOwner,beforeEpoch,'same mounted case observes session epoch through usePageOwner');
 assert.doesNotMatch(document.body.textContent,/正在更新案件資料/,'epoch/revision change does not leave a busy batch behind');
 const isolated=ui.createPageData({workspace:'snapshot-test',identityFingerprint:'actor:grant',openId:'completion'});
 let releaseOld;const blocked=new Promise(resolve=>releaseOld=resolve);
 const oldRead=ui.readCase(isolated,'completion',false,async()=>{await blocked;return 'old'});
 await Promise.resolve();const successor=ui.readCase(isolated,'completion',true,async()=> 'new');
 assert.equal(await oldRead,'new','B read awaiter adopts the successor');assert.equal(await successor,'new');releaseOld();isolated.close();
 console.log('PASS case snapshot: E metadata and source as_of, retained Error timestamp, StrictMode, grant/epoch isolation');
}finally{await act(async()=>root.unmount());dom.window.close()}
