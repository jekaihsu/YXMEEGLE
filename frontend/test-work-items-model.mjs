import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
const bundle=await build({stdin:{contents:"export * from './src/workItemsModel'; export {parseProjectProgress} from './src/projectProgressApi';",resolveDir:import.meta.dirname},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
const m=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const data=JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
function field(){const stage=structuredClone(data.production.field);stage.items=[5,10,50].map((q,i)=>({item_id:`immutable-${i}`,code:i?'C115264-1':'C115264-2',name:['C42FW','C44FW','C31FW'][i],planned_qty:String(q),link_basis:'native'}));stage.items_total=3;return stage}
test('C115264 retains three immutable identities, individual plans, unknown actuals and progress',()=>{
 const stage=field(),rows=m.workItemRows(stage);assert.equal(rows.length,3);assert.deepEqual(rows.map(r=>r.id),['immutable-0','immutable-1','immutable-2']);assert.equal(new Set(rows.map(r=>r.id)).size,3);assert.equal(rows[1].code,rows[2].code);assert.deepEqual(rows.map(r=>r.planned),['5','10','50']);assert.ok(rows.every(r=>r.actualDisplay==='未知' && r.progressDisplay==='未知' && !r.verified));assert.deepEqual(m.workItemsAggregate(stage,rows),{percent:null,label:'完成率未知'});assert.equal('plannedTotal' in m.departmentItems({...data,production:{...data.production,field:stage}},'field'),false);
});
test('ambiguous and unlinked items never contribute even with complete source points',()=>{
 const stage=field();for(const item of stage.items)Object.assign(item,{planned_points:'100',remaining_points:'0',status:'done'});stage.items[1].link_basis='ambiguous';stage.items[2].link_basis='unlinked';const rows=m.workItemRows(stage);assert.deepEqual(rows.map(r=>r.verified),[true,false,false]);assert.deepEqual(rows.map(r=>r.progressDisplay),['點數完成率 100%','未知','未知']);assert.equal(m.workItemsAggregate(stage,rows).percent,null);
});
test('points are explicitly named, never actual, with an aggregate only for a complete verified set',()=>{
 const stage=field();for(const item of stage.items)Object.assign(item,{planned_points:'100',remaining_points:'40',status:'partial'});let rows=m.workItemRows(stage);assert.ok(rows.every(r=>r.progressDisplay==='點數完成率 60%' && r.actualDisplay==='未知'));assert.equal(m.workItemsAggregate(stage,rows).label,'點數完成率 60%（3 筆工項）');stage.items_truncated=true;stage.items_total=9;assert.equal(m.workItemsAggregate(stage,rows).percent,null);assert.equal(m.workItemsTruncation(stage),'僅顯示 3／9 筆工項，清單未完整，完成率未知。');assert.ok(m.workItemRows(stage,true).every(r=>!r.verified));
});
test('invalid, missing and contradictory point values remain unknown',()=>{
 for(const patch of [{remaining_points:'-1'},{remaining_points:'101'},{planned_points:'0'},{planned_points:''},{remaining_points:null},{status:'no_signal'},{remaining_points:'Infinity'}]){const stage=field();Object.assign(stage.items[0],{planned_points:'100',remaining_points:'40',status:'partial'},patch);assert.equal(m.workItemRows(stage)[0].progressDisplay,'未知')}
});
test('departments only use their own production rows and counts',()=>{
 const copy=structuredClone(data);for(const [i,key] of ['field','control','mapping','report'].entries()){copy.production[key]=field();copy.production[key].items=[{...field().items[0],item_id:key,name:key,planned_qty:String(i)}];copy.production[key].items_total=1}
 for(const [i,key] of ['field','control','mapping','report'].entries()){const view=m.departmentItems(copy,key);assert.deepEqual(view.rows.map(r=>r.id),[key]);assert.equal(view.rows[0].planned,String(i));assert.equal(view.stage.items_total,1)}
});
test('boundary rejects absent or duplicate immutable IDs and invalid optional progress fields',()=>{
 for(const patch of [d=>d.production.field.items[0].item_id='',d=>d.production.field.items[1].item_id=d.production.field.items[0].item_id,d=>d.production.field.items[0].status='100%',d=>d.production.field.items[0].planned_points=100]){const next=structuredClone(data);patch(next);assert.throws(()=>m.parseProjectProgress(next),/工程進度資料格式不正確/)}
});
