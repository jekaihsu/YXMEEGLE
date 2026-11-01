import assert from 'node:assert/strict';
import {test} from 'node:test';
import {build} from 'esbuild';
import {writeFile,unlink} from 'node:fs/promises';
import {projectFixture} from './fixtures/node-assignments.mjs';
const bundled=await build({stdin:{contents:"export {caseDataSections} from './src/caseDataSections'; export {projectFlowRoute} from './src/projectRoutes'; export {participantRows} from './src/ProjectDestinations';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external',loader:{'.css':'empty'},jsx:'automatic'});
const temp=new URL('./.case-data-sections.mjs',import.meta.url);await writeFile(temp,bundled.outputFiles[0].text);const m=await import(temp.href);await unlink(temp);
const labels=sections=>sections.map(([,label])=>label);
const world=(patch={},status='ready')=>{const base=projectFixture();Object.assign(base.project,{source_kind:'v4'},patch);return {w:{...base.workspace,source_status:{...base.workspace.source_status,status},projects:[base.project],source_confirmations:[],contract_items:[]},p:base.project}};

test('案件資料 drops 參與人員 and 附件索引 and hides verified-empty subsections',()=>{
 const {w,p}=world();
 assert.deepEqual(labels(m.caseDataSections(w,p,'basic')),['基本資料','審批與變更','討論與紀錄','資料來源與同步']);
 assert.ok(!labels(m.caseDataSections(w,p,'basic')).some(l=>/參與人員|附件索引/.test(l)));
});
test('an unverified source read keeps the empty subsections so unknown is not shown as none',()=>{
 const {w,p}=world({},'error');
 assert.deepEqual(labels(m.caseDataSections(w,p,'basic')),['基本資料','報價（0）','確認單與合約工項','母子案','審批與變更','討論與紀錄','資料來源與同步']);
});
test('subsections with content stay, and the open one never disappears',()=>{
 const {w,p}=world();
 w.source_confirmations=[{id:'cf1',project_id:p.id}];
 assert.ok(labels(m.caseDataSections(w,p,'basic')).includes('確認單與合約工項'));
 w.source_confirmations=[];
 assert.ok(labels(m.caseDataSections(w,p,'contracts')).includes('確認單與合約工項'),'the section being viewed is kept');
 const child={...p,id:'c1',code:'C-1',parent_code:p.code};w.projects=[p,child];
 assert.ok(labels(m.caseDataSections(w,p,'basic')).includes('母子案'));
});
test('demo cases count as verified',()=>{
 const {w,p}=world({source_kind:'demo'},'error');
 assert.ok(!labels(m.caseDataSections(w,p,'basic')).includes('報價（0）'));
});
test('old 參與人員 and 附件索引 deep links land on their canonical tabs',()=>{
 assert.equal(m.projectFlowRoute({tab:'data',section:'participants'}).tab,'people');
 assert.equal(m.projectFlowRoute({tab:'data',section:'files'}).tab,'files');
 assert.equal(m.projectFlowRoute({tab:'data',section:'basic'}).tab,'data');
});
const idle={state:{kind:'disabled'}};
test('local mode: one row per node, source 本地流程, node deadline kept',()=>{
 const {w,p}=world();p.nodes[0].collaborator_ids=['ou_anna'];
 const rows=m.participantRows({w},p,idle,[{key:p.nodes[0].key,finalDeadline:'2026-10-04T00:00:00Z'}]);
 assert.equal(rows.length,p.nodes.length);
 assert.ok(rows.every(r=>r.source==='本地流程'));
 assert.equal(rows[0].deadline,'2026-10-04');assert.match(rows[0].others,/林安娜/);assert.equal(rows[1].deadline,'未排定');
});
test('Lark assignment and 本地流程 stay separate identities in the same table',()=>{
 const {w,p}=world();
 for(const n of p.nodes){n.owner_id='';n.collaborator_ids=[];n.tasks=[]}
 p.nodes[0].owner_id='ou_anna';
 const data={nodes:[{key:'sales',label:'業務',owners:[{open_id:'ou_wei',name:'陳威廷'}],assignment_method:'手動指派',assigned_by:{name:'林安娜'}}],node_details:{sales:{tasks:[{assignee:{name:'陳威廷'}},{assignee:null}]}}};
 const rows=m.participantRows({w},p,{state:{kind:'ready',data}},[{key:'sales',finalDeadline:'2026-10-09'}]);
 assert.deepEqual(rows.map(r=>r.source),['Lark 指派 · 手動指派 · 林安娜指派','本地流程'],'empty local nodes are not repeated next to Lark rows');
 assert.equal(rows[0].others,'陳威廷、尚未指派');assert.equal(rows[0].deadline,'2026-10-09');assert.equal(rows[1].owners[0].name,'林安娜');assert.equal(rows[1].deadline,'未排定');
});
