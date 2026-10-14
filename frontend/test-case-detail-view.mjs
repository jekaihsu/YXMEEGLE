import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
const moduleUrl = process.env.CASE_DETAIL_MODULE_URL ?? new URL('./src/caseDetailView.ts', import.meta.url).href;
const {buildCaseDetailView: build} = await import(moduleUrl);
const clone = x => structuredClone(x);
const edge = (type,p,c) => ({edge_type:type,parent_key:p,child_key:c,cardinality:'one',contested:false,verification:'receipt_missing'});
const parent = (p,type='case_confirmation') => ({edge_type:type,parent_key:p,contested:false,verification:'receipt_missing'});
const row = (key,kind,label,p) => ({key,kind,label,parents:p?[parent(p)]:[]});
const section = (rows=[],states=[],details={}) => ({states,freshness:null,reason:null,source_time:{value:'2026-10-14T01:00:00Z',basis:'source_sync_completed',fetched_at:'2026-10-14T02:00:00Z'},rows,details});
function fixture(){
 const c=row('confirmation:v1','confirmation','版 A','case:case-a'); Object.assign(c,{code:'版 A',selected:true,revision:'r1',source_url:'https://example.invalid/source'});
 const ct=row('contract:ct1','contract','合約 A',c.key); Object.assign(ct,{item_number:'1',amount:{state:'withheld',reason:'G-AMT'},work_item_links:'unresolved'});
 const i=row('work_item:w1','work_item','工項 A',ct.key);
 const t=row('task:case-a/n1/t1','task','任務 A',i.key); Object.assign(t,{status:'pending',task_id:'t1'});
 const n=row('node:case-a/n1','node','節點 A','case:case-a'); Object.assign(n,{status:'in_progress',node_id:'n1',tasks:[t]});
 return {project_id:'case-a',page_state:[],header:{project_name:'測試案件',case_number:'同號',selected_confirmation:{key:c.key,code:c.code},other_versions:[],admission:{execution_system:'yx',execution_system_label:'YX',execution_readonly_reason:null,case_visibility:null,explanation:'admitted'},pm:{name:'角色 A'},responsible_person:{name:'角色 B'},current_stage:{state:'verified',node_id:'n1',label:'節點 A'},dates:{effective_approved:{state:'unknown',reason:'VCC-123 deadline provenance unresolved'},pending_requested:[{approval_id:'p1',task_key:t.key,requested_due_date:'2026-11-01',status:'pending'}],estimated:{state:'unknown',reason:'no verified source field'}},blockers:{items:[],states:['unknown']},source_link:{url:'https://example.invalid/source',basis:'authorized_source_reference'},contract_amounts:{state:'withheld',reason:'G-AMT'},details:{case_identity:'case-a',confirmation_identity:'v1',relationship_counts:{basis:'authorized_view_only; not a population total',confirmations:1,contracts:1,work_items:1,tasks:1},complete_ids:{contracts:['ct1'],work_items:['w1']},edges:[edge('case_confirmation','case:case-a',c.key),edge('confirmation_contract',c.key,ct.key),edge('contract_work_item',ct.key,i.key),edge('case_node','case:case-a',n.key),edge('work_item_task',i.key,t.key)],edge_verification:'receipt_missing'}},sections:{overview:section([],['partial'],{case_identity:'case-a'}),versions:section([c]),contract_lines:section([ct],['partial']),work_items:section([i]),workflow_nodes:section([n]),reports_documents:section([],['unknown'],{entry_point:{view:'project',project:'case-a',tab:'data',section:'files'},unresolved_edges:[{edge_type:'task_evidence',parent_key:t.key,child_key:null,verification:'receipt_missing',reason:'edge_not_located'}]}),history:section([{confirmation_key:c.key,revision:'r0',replaced_at:'2026-10-01'},{event_id:'e1',action:'read',created_at:'2026-10-02'}])}};
}
const tests=[]; const test=(name,fn)=>tests.push([name,fn]);
const sec=(v,k)=>v.sections.find(s=>s.key===k);
const header=(v,k)=>v.header.find(f=>f.label===k);
test('header and seven independently timed sections preserve body facts',()=>{
 const v=build(fixture()); assert.equal(v.page.label,'已讀取'); assert.equal(header(v,'專案').text,'測試案件');
 assert.deepEqual(v.sections.map(s=>s.title),['總覽','確認單版本','合約明細','工項','流程節點／SOP','報告與文件','歷程']);
 assert.equal(sec(v,'overview').label,'部分資料'); assert.equal(sec(v,'versions').sourceTime.text,'2026-10-14T01:00:00Z');
 assert.equal(v.sourceLink.url,'https://example.invalid/source'); assert.equal(v.side.operations,'唯讀'); assert.equal(v.drawer,null);
});
test('unknown is em dash with reason and never a zero count',()=>{
 const v=build(fixture(),{selected:'case'}); assert.deepEqual(header(v,'生效核准日期'),{label:'生效核准日期',text:'—',reason:'VCC-123 deadline provenance unresolved'});
 assert.equal(v.side.relationshipCompleteness.text,'—'); assert.equal(v.side.relationshipCompleteness.reason,'receipt_missing'); assert.equal(v.drawer.relationshipCounts,null);
 const b=fixture(); b.sections.reports_documents=section([],['complete_empty']); b.header.details.relationship_counts.tasks=0;
 assert.equal(build(b,{selected:'case'}).drawer.relationshipCounts.tasks,0);
});
test('amount withheld ignores value, derived value and caller approval strings',()=>{
 const b=fixture(); b.header.contract_amounts.value=9001; b.header.contract_amounts.approved=true;
 Object.assign(b.sections.contract_lines.rows[0].amount,{value:9001,sum:18002,derived:4500.5});
 const v=build(b); assert.deepEqual(header(v,'合約金額'),{label:'合約金額',text:'未核准顯示',reason:'G-AMT'});
 assert.deepEqual(sec(v,'contract_lines').rows[0].amount,{label:'合約金額',text:'未核准顯示',reason:'G-AMT'});
 assert.equal(/9001|18002|4500/.test(JSON.stringify(v)),false);
});
test('forbidden rows, nested tasks, IDs, labels, times and count hints disappear',()=>{
 const b=fixture(); const visible=build(b); assert.equal(sec(visible,'contract_lines').rows[0].title.text,'合約 A');
 b.sections.contract_lines.states=['forbidden']; b.sections.contract_lines.rows[0].label='SECRET_CHILD'; b.sections.contract_lines.rows[0].key='contract:SECRET_ID';
 b.header.details.edges.push(edge('confirmation_contract','confirmation:v1','contract:SECRET_ID'));
 const v=build(b,{selected:sec(visible,'contract_lines').rows[0].key});
 assert.equal(sec(v,'contract_lines').label,'沒有權限'); assert.deepEqual(sec(v,'contract_lines').rows,[]);
 assert.equal(v.drawer,null); assert.equal(sec(v,'contract_lines').sourceTime.text,'—'); assert.equal(/SECRET_CHILD|SECRET_ID/.test(JSON.stringify(v)),false);
 const persons=fixture(); persons.header.pm={name:'SECRET_PM',states:['forbidden']}; persons.header.blockers={items:['SECRET_BLOCKER'],states:['forbidden']}; persons.header.source_link={url:'https://secret.invalid',states:['forbidden']}; assert.equal(/SECRET_PM|SECRET_BLOCKER|secret.invalid/.test(JSON.stringify(build(persons))),false);
 const versions=fixture(); versions.sections.versions.states=['forbidden']; assert.equal(header(build(versions),'確認單版本').text,'—');
});
test('malformed body fails closed without retaining otherwise valid header facts',()=>{
 for(const mutate of [b=>b.sections.work_items.rows.push(null),b=>b.sections.history.rows[0].revision={},b=>b.header.pm.name=42,b=>b.sections.versions.source_time=[],b=>b.sections.contract_lines.states=['partial','unknown'],b=>b.header.details.edges[0].contested='yes',b=>b.sections.versions.rows[0].kind='contract',b=>delete b.sections.overview,b=>b.sections.work_items.rows[0].parents=[null]]){
  const b=fixture(); mutate(b); const v=build(b); assert.deepEqual(v.page,{states:['unknown'],label:'狀態未知',reason:'malformed_case_detail_body'}); assert.deepEqual(v.header,[]); assert.equal(v.drawer,null);
 }
 assert.equal(build(fixture()).header[0].text,'測試案件');
});
test('all C-STATE labels remain independent and stale freshness survives unknown',()=>{
 const expected={loading:'讀取中',complete_empty:'尚無資料',filtered_empty:'沒有符合篩選條件的資料',unlocated:'找不到資料來源',forbidden:'沒有權限',read_failed:'讀取失敗',partial:'部分資料',stale:'資料待更新',unknown:'狀態未知'};
 for(const [s,label] of Object.entries(expected)){const b=fixture(); b.sections.history=section([],[s]); assert.equal(sec(build(b),'history').label,label);}
 const b=fixture(); b.sections.history.states=['unknown']; b.sections.history.freshness='stale'; b.sections.history.source_time.value=null;
 assert.equal(sec(build(b),'history').freshness,'資料待更新'); assert.equal(sec(build(b),'history').sourceTime.text,'—');
 b.sections.contract_lines.states=['partial','stale']; assert.equal(sec(build(b),'contract_lines').label,'部分資料・資料待更新');
});
test('pending requested date never substitutes for effective or estimated date',()=>{
 const v=build(fixture()); assert.equal(header(v,'待核准申請日期').text,'2026-11-01'); assert.equal(header(v,'生效核准日期').text,'—'); assert.equal(header(v,'預估日期').text,'—');
 const b=fixture(); b.header.dates.effective_approved={state:'verified',value:'2026-11-01',reason:'caller receipt'};
 assert.equal(build(b).page.reason,'malformed_case_detail_body');
});
test('tree starts one level deep and expands only selected native identity',()=>{
 const b=fixture(),v=build(b); assert.deepEqual(v.tree.children.map(r=>r.title.text),['版 A','節點 A']); assert.equal(v.tree.expanded,null); assert.deepEqual(v.tree.children[1].children,[]);
 const c=v.tree.children[0],next=build(b,{selected:c.key}); assert.deepEqual(next.tree.expanded.children.map(r=>r.title.text),['合約 A']);
 assert.equal(next.drawer.identifiers.record_key,'confirmation:v1'); assert.deepEqual(next.drawer.navigation,{route:'confirmation',nativeKey:'confirmation:v1'}); assert.deepEqual(next.drawer.reportsDocuments,{view:'project',project:'case-a',tab:'data',section:'files'}); assert.deepEqual(next.drawer.parents,[{label:'測試案件',verification:'對應未驗證'}]);
 const defaultSurface=clone(next); delete defaultSurface.drawer; assert.equal(/confirmation:v1|contract:ct1|case-a\/n1/.test(JSON.stringify(defaultSurface)),false);
});
test('unresolved edges and missing parents render explicit rows without guessed identity',()=>{
 const b=fixture(); b.sections.work_items.rows[0].unresolved={reason:'no_authorized_parent_edge',verification:'verified'};
 const v=build(b); assert.equal(sec(v,'work_items').rows[0].relationship,'對應未驗證'); assert.equal(sec(v,'work_items').rows[0].reason,'no_authorized_parent_edge');
 assert.equal(sec(v,'reports_documents').rows[0].kind,'unresolved_edge'); assert.equal(sec(v,'reports_documents').rows[0].title.text,'—'); assert.equal(v.side.warnings.length,3);
 b.header.details.edges.push(edge('confirmation_contract','confirmation:v1','contract:missing-secret'));
 const out=build(b,{selected:v.tree.children[0].key}); assert.equal(out.tree.expanded.children[1].reason,'no_authorized_edge_target'); assert.equal(JSON.stringify(out).includes('missing-secret'),false);
});
test('caller mapping/receipt claims never grant verification or write actions',()=>{
 const b=fixture(); b.header.details.edge_verification='verified'; b.header.details.edges.forEach(e=>{e.verification='verified'; e.receipt='accepted';}); b.actions=['Complete','Approve','SOP'];
 const v=build(b,{selected:build(b).tree.children[0].key}); assert.equal(v.drawer.parents[0].verification,'對應未驗證'); assert.equal(v.side.relationshipCompleteness.reason,'receipt_missing');
 assert.equal(/"Complete"|"Approve"|"accepted"|"verification":"verified"|receipt"/.exec(JSON.stringify(v)),null);
});
test('duplicate numbers remain distinct versions; duplicate native keys fail closed',()=>{
 const b=fixture(); const c=clone(b.sections.versions.rows[0]); c.key='confirmation:v2'; c.selected=false; b.sections.versions.rows.push(c); b.header.other_versions.push({key:c.key,code:c.code});
 assert.equal(sec(build(b),'versions').rows.length,2); assert.notEqual(sec(build(b),'versions').rows[0].key,sec(build(b),'versions').rows[1].key);
 b.sections.versions.rows[1].key='confirmation:v1'; assert.equal(build(b).page.reason,'duplicate_identity');
});
test('UI filter and sort preserve selection and do not search technical IDs',()=>{
 const b=fixture(),v=build(b),selected=v.tree.children[0].key;
 const out=build(b,{selected,filters:{search:'no match'},sort:{key:'title',dir:'desc'}});
 assert.deepEqual(sec(out,'versions').rows,[]); assert.equal(out.drawer.row.title.text,'版 A'); assert.equal(sec(out,'reports_documents').rows[0].kind,'unresolved_edge');
 assert.deepEqual(sec(build(b,{filters:{search:'v1'}}),'versions').rows.map(r=>r.title.text),[]);
 const second=clone(b.sections.versions.rows[0]); second.key='confirmation:v2'; second.label='版 B'; b.sections.versions.rows.push(second);
 assert.deepEqual(sec(build(b,{sort:{key:'title',dir:'desc'}}),'versions').rows.map(r=>r.title.text),['版 B','版 A']);
});
test('history variant allowlists ignore injected generic row fields',()=>{
 const b=fixture(); Object.assign(b.sections.history.rows[0],{key:'contract:HIDDEN',kind:'contract',label:'SECRET_HISTORY',action:'INJECTED_ACTION',source_url:'https://secret.invalid',tasks:[],amount:{state:'withheld',reason:'G-AMT',value:9001}});
 const v=build(b); assert.equal(sec(v,'history').rows[0].title.text,'r0'); assert.equal(/HIDDEN|SECRET_HISTORY|INJECTED_ACTION|secret.invalid|9001/.test(JSON.stringify(v)),false);
});
test('source fetch time is never substituted; unsafe URLs remain unlocated',()=>{
 const b=fixture(); b.sections.overview.source_time.value=null; b.header.source_link.url='javascript:alert(1)';
 const v=build(b); assert.equal(sec(v,'overview').sourceTime.text,'—'); assert.equal(v.sourceLink.url,null); assert.equal(v.sourceLink.reason,'source_link_unlocated');
 const hidden={project_id:'secret',page_state:['unlocated'],reason:'not_in_authorized_view',header:null,sections:{}};
 assert.equal(build(hidden).page.label,'找不到資料來源'); assert.equal(JSON.stringify(build(hidden)).includes('secret'),false);
});
let failed=0;
for(const [name,fn] of tests){try{fn(); console.log(`ok - ${name}`);}catch(e){failed++;console.error(`not ok - ${name}\n${e.stack}`);}}
if(failed) process.exit(1);
console.log(`case-detail view: ${tests.length} named tests passed`);
if(process.argv.includes('--mutations')){
 const path=fileURLToPath(new URL('./src/caseDetailView.ts',import.meta.url));
 const original=readFileSync(path,'utf8'); const dir=mkdtempSync(join(tmpdir(),'case-detail-mutations-'));
 const guards=[['unknown-not-zero',"text: str(value) ? value : '—'","text: str(value) ? value : '0'"],['amount-withheld',"text: '未核准顯示'","text: '9001'"],['forbidden-absent',"['forbidden','loading','read_failed','unlocated'].includes(x)","['loading','read_failed','unlocated'].includes(x)"],['malformed-fail-closed',"if (!validBody(input)) return blank('malformed_case_detail_body');","if (false) return blank('malformed_case_detail_body');"]];
 try{for(const [name,from,to] of guards){assert.ok(original.includes(from),`mutation target ${name}`); const p=join(dir,`${name}.ts`);
  const source=original.replace(from,to).replaceAll("'./dataState.ts'",JSON.stringify(fileURLToPath(new URL('./src/dataState.ts',import.meta.url)))); writeFileSync(p,source);
  const run=spawnSync(process.execPath,[fileURLToPath(import.meta.url)],{env:{...process.env,CASE_DETAIL_MODULE_URL:pathToFileURL(p).href},encoding:'utf8'});
  assert.notEqual(run.status,0,`${name} mutation survived`); const failing=(run.stderr??'').split('\n').find(s=>s.startsWith('not ok -')) ?? (run.stderr??'').split('\n')[0];
  console.log(`killed mutation - ${name}: exit ${run.status}; ${failing}`);
 }}finally{rmSync(dir,{recursive:true,force:true});}
}
