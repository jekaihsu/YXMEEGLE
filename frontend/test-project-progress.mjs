import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile,writeFile,unlink} from 'node:fs/promises';
import {build} from 'esbuild';
import {assignmentFixture} from './fixtures/node-assignments.mjs';
const bundle = await build({stdin:{contents:"export {prefetchProjectProgress} from './src/useProjectProgress'; export {invalidateSessionEpoch} from './src/api'; export * from './src/projectProgressApi'; export * from './src/projectProgressView'; export {parseRoute} from './src/api'; export {sopActionLabel,canConfirmSop} from './src/startSop';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external'});
const temp=new URL('./.project-progress-test.mjs',import.meta.url);await writeFile(temp,bundle.outputFiles[0].text);const m=await import(temp.href);await unlink(temp);
const fixture = JSON.parse(await readFile(new URL('./fixtures/project-progress.json',import.meta.url),'utf8'));
test('parser accepts real backend synthetic fixture and preserves exact decimal quantities',()=>{const d=m.parseProjectProgress(fixture);assert.equal(d.production.field.planned.qty,'65');assert.equal(d.identity.is_c_prefix,true);assert.equal(d.production.field.actual.known,false)});
test('parser rejects malformed nested values and missing stages with friendly error',()=>{for(const patch of [d=>d.stages.pop(),d=>d.stages[0].state='completed',d=>d.production.field.items[0].planned_qty=0,d=>d.production.control.actual.known=true,d=>d.finance.quotes[0].received_total=0,d=>d.sources.reports_status='ready',d=>d.gaps[0].severity='critical']){const d=structuredClone(fixture);patch(d);assert.throws(()=>m.parseProjectProgress(d),/工程進度資料格式不正確/)};assert.throws(()=>m.parseProjectProgress(null),/請稍後重試/)});
test('stage join keeps source state and evidence independent of SOP completion',()=>{const nodes=assignmentFixture().list.nodes;nodes.find(n=>n.key==='field').derived_status='已完成';const joined=m.joinProgressStages(fixture.stages,nodes);assert.equal(joined.find(s=>s.key==='field').state,'unknown');assert.equal(joined.find(s=>s.key==='field').sop.derived_status,'已完成');assert.deepEqual(joined[0].evidence,fixture.stages[0].evidence)});
test('billing joins pricing node and missing SOP remains absent',()=>{assert.equal(m.joinProgressStages(fixture.stages,assignmentFixture().list.nodes).find(s=>s.key==='billing').sop.key,'pricing');assert.ok(m.joinProgressStages(fixture.stages).every(s=>s.sop===undefined))});
test('null numbers never become zero and decimal text stays exact',()=>{assert.equal(m.progressValue(null),'來源未提供');assert.equal(m.progressValue(undefined),'來源未提供');assert.equal(m.progressValue(''),'來源未提供');assert.equal(m.progressValue(0),'0');assert.equal(m.progressValue('12.5000'),'12.5000')});
test('gap hints give practical repair instructions for every known id',()=>{const ids=['no_confirmation','confirmation_status_conflict','fill_items_unknown','plan_unavailable','plan_truncated','items_unlinked','items_ambiguous','quotes_duplicated','no_daily_linked','v3_ambiguous','v3_none','v3_no_activity','reports_cold','reports_unavailable','reports_restricted','reports_disabled','reports_stale','finance_restricted','finance_empty'];for(const id of ids)assert.notEqual(m.gapHint(id),m.gapHint('unknown'));assert.match(m.gapHint('no_daily_linked'),/所屬案件.*合約工項.*下次來源同步/)});
test('progress deep link survives serialization and preserves existing route normalization',()=>{const route=m.parseRoute('#view=project&project=p2&tab=progress');assert.equal(route.tab,'items');assert.equal(m.parseRoute('#'+new URLSearchParams(Object.entries(route).filter(([,v])=>v))).tab,'items');assert.equal(m.parseRoute('#view=project&tab=files').tab,'files')});
test('SOP label offers the start only before the node rows exist; a started case has none',()=>{assert.equal(m.sopActionLabel({already_started:false}),'啟動 SOP');assert.equal(m.sopActionLabel({already_started:true}),null)});
test('starting needs eligibility; seeds are a separate opt-in and a started case confirms neither',()=>{const p={can_start:true,blockers:[],already_started:false,seeds_pending:4,eligible:true};assert.equal(m.canConfirmSop(p),true);assert.equal(m.canConfirmSop(p,true),true);assert.equal(m.canConfirmSop({...p,eligible:false}),false);assert.equal(m.canConfirmSop({...p,seeds_pending:0},true),false);assert.equal(m.canConfirmSop({...p,already_started:true}),false);assert.equal(m.canConfirmSop({...p,already_started:true},true),false);assert.equal(m.canConfirmSop({...p,can_start:false}),false);assert.equal(m.canConfirmSop({...p,blockers:[{}]}),false)});

test('ambiguous report links list every candidate without choosing one',()=>{const cases=[{case_key:'a',case_code:'C115264'},{case_key:'b',case_code:'115588'}];assert.deepEqual(m.caseReportTargets(cases,[], 'office'),[{case_code:'C115264',dept:'office',week:undefined},{case_code:'115588',dept:'office',week:undefined}])});

test('the parser keeps the item progress and statuses and an older payload without them still parses',()=>{
  const d=m.parseProjectProgress(fixture);assert.equal(d.production.field.progress,undefined);
  const next=structuredClone(fixture);
  next.production.field.progress={percent:'30',earned_points:'60',planned_points:'200',items_done:0,items_total:2};
  Object.assign(next.production.field.items[0],{planned_points:'100',remaining_points:'40',status:'partial'});
  const parsed=m.parseProjectProgress(next);
  assert.deepEqual(parsed.production.field.progress,next.production.field.progress);
  assert.equal(parsed.production.field.items[0].status,'partial');
});


test('forced progress reads bypass pending requests and older completions cannot replace fresh data',async()=>{
 m.invalidateSessionEpoch();
 let release,calls=0;
 const old=structuredClone(fixture),fresh=structuredClone(fixture);fresh.as_of='2026-10-26T08:00:00Z';
 const wait=new Promise(resolve=>release=resolve);
 globalThis.fetch=async()=>{calls++;const index=calls;if(index===1)await wait;return new Response(JSON.stringify(index===1?old:fresh),{headers:{'Content-Type':'application/json'}})};
 const first=m.prefetchProjectProgress(fixture.project_id);
 const retry=m.prefetchProjectProgress(fixture.project_id,true);
 const independent=calls===2;release();assert.equal(independent,true,'retry starts an independent HTTP read');
 assert.equal((await retry).as_of,fresh.as_of);
 release();await first;
 assert.equal((await m.prefetchProjectProgress(fixture.project_id)).as_of,fresh.as_of);
});
