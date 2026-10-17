import assert from 'node:assert/strict';
import {build} from 'esbuild';
const result=await build({entryPoints:['src/reports/mock.ts'],bundle:true,write:false,platform:'node',format:'esm'});
const {mockReport}=await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);globalThis.location={search:'?mock=1'};
const field=mockReport('review',new URLSearchParams('dept=field'));assert.equal(field.kpi.total,813);assert.equal(field.kpi.passed,361);assert.equal(field.kpi.returned,47);assert.equal(field.kpi.pending,405);assert.equal(field.kpi.error_rate,47/408);
const office=mockReport('review',new URLSearchParams('dept=office'));assert.equal(office.kpi.error_rate,null);assert.equal(office.kpi.coverage,0);assert.equal(office.kpi.pending,31);assert.equal(office.kpi.unset,1202);assert.equal(office.flags[0].count,356);
const flags=mockReport('review/rows',new URLSearchParams('dept=office&flag=⚠案件不符&offset=50&limit=50'));assert.equal(flags.total,356);assert.equal(flags.items.length,50);assert.ok(flags.items.every(r=>r.flags.includes('⚠案件不符')));
const assets=mockReport('assets',new URLSearchParams('kind=instrument&status=送修-損壞'));assert.equal(assets.total,6);assert.ok(assets.items.every(r=>r.status==='送修-損壞'));
location.search='?mock=1&mockState=stale';assert.equal(mockReport('sources',new URLSearchParams()).meta.stale,true);
location.search='?mock=1&mockState=error';assert.throws(()=>mockReport('sources',new URLSearchParams()),/示範讀取失敗/);
console.log('Reports realistic totals, missing office reviews, flag filtering, paging, repairs and state fixtures passed.');

location.search='?mock=1';const unset=mockReport('sales',new URLSearchParams('status=未填'));assert.equal(unset.total,417);assert.ok(unset.items.every(r=>r.status==='未填'));
