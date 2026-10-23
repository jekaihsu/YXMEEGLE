import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {test} from 'node:test';
const bundle=await build({stdin:{contents:"export * from './src/reportLinksModel';export {fieldworkSnapshot} from './src/projectOverviewModel';export {overviewKpis} from './src/overviewDashboardModel';",resolveDir:import.meta.dirname},bundle:true,write:false,platform:'node',format:'esm'});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const row=(id,reason,code='C1',project_id=null)=>({id,case_mapping_status:reason,source_case_code:code,project_id});
test('queue groups unresolved reasons and excludes already linked reports',()=>{
 const groups=m.groupedQueue([row('a','missing_reference'),row('b','unresolved_reference'),row('c','ambiguous_reference'),row('d','matched','C1','p'),row('e','unresolved_reference')]);
 assert.deepEqual(groups.map(g=>[g.reason,g.rows.map(r=>r.id)]),[['missing_reference',['a']],['unresolved_reference',['b','e']],['ambiguous_reference',['c']]]);
});
test('backend and frontend share the basis vocabulary including manual_review',()=>{
 assert.deepEqual(Object.values(m.linkVocabulary).map(v=>[v.value,m.basisLabel(v.value)]),[['source_case_or_link','原生'],['provisional_case_code','完整案號'],['manual_review','人工核對'],['unlinked','待配對']]);
 assert.equal(m.basisLabel('manual_reviewed'),'人工核對');assert.equal(m.basisLabel(undefined),'待配對');
});
test('summary is exact and does not change an unknown quantity to zero',()=>{
 assert.equal(m.summaryLine({linked:2,total:7,unlinked:5}),'日報已連結 2 / 7 筆，待配對 5 筆');
});
test('bulk selection preserves suffixes and excludes linked, missing-source, and blank rows',()=>{
 const rows=[row('a','unresolved_reference','C1-01'),row('b','unresolved_reference',' C1-01 '),row('c','unresolved_reference','C1'),row('d','matched','C1-01','p'),{...row('e','unresolved_reference','C1-01'),source_missing:true}];
 assert.deepEqual(m.sameCodeRows(rows,rows[0]).map(r=>r.id),['a','b']);assert.deepEqual(m.sameCodeRows(rows,row('z','missing_reference','')),[]);
});
test('latest report is linked activity and does not require delivery acceptance',()=>{
 const report={date:'2026-10-22',department:'外業組',review:{status:'pending'},match_basis:'manual_review'};
 assert.equal(m.fieldworkSnapshot(undefined,[report]).latestDate,'2026-10-22');
 assert.equal(m.fieldworkSnapshot(undefined,[{...report,match_basis:undefined}]).latestDate,null);
 assert.equal(m.fieldworkSnapshot({work_orders:{latest_date:'2026-10-23'},items_total:0,actual:{known:false}},[report]).latestDate,'2026-10-23');
});

test('Overview field box and latest-valid-report KPI use the linked date',()=>{
 const field={work_orders:{latest_date:'2026-10-22'},items_total:0,actual:{known:false},items:[]};
 const cells=m.overviewKpis({field,nodes:[],issues:[],available:true});
 assert.equal(cells.find(c=>c.id==='latest_report').value,'2026-10-22');
 assert.match(cells.find(c=>c.id==='field').detail,/最近已連結回報 2026-10-22/);
});
