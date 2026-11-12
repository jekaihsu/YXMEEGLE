import assert from 'node:assert/strict';
import {build} from 'esbuild';
const result=await build({entryPoints:['src/tokenDashboardModel.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const m=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'));
const filters={from:'2026-10-01',to:'2026-10-31',actor:'王 & a',provider:'gpt',rating:'down',scope:'project',q:'進度 & <script>'};
assert.deepEqual(m.readFilters(m.filterQuery(filters)),filters);
for(const path of ['/token_dashboard','/token_dashboard/','/token_dashboard///'])assert.equal(m.isTokenDashboardPath(path),true);
for(const path of ['/token_dashboard_x','/x/token_dashboard','/','/TOKEN_DASHBOARD'])assert.equal(m.isTokenDashboardPath(path),false);
assert.equal(m.canViewUsage('manager'),true);
for(const role of ['member','admin','',undefined])assert.equal(m.canViewUsage(role),false);
assert.equal(m.formatNumber(1234567),'1,234,567');
assert.equal(m.formatNumber(12.2),'12');
assert.equal(m.formatNumber(undefined),'待確認');assert.equal(m.formatNumber(null),'待確認');assert.equal(m.formatCost(undefined),'待確認');assert.equal(m.formatCost(NaN),'待確認');
assert.equal(m.formatReadTime('2026-10-30T17:30:00Z').replace(/\s/g,' '),'2026/10/31 01:30:00');
assert.match(m.formatCost(.12345),/0\.1235/);
assert.match(m.formatCost(12.345),/12\.35/);
assert.equal(m.formatCost(null),'未計價');
assert.equal(m.formatTime('2026-10-30T17:30:00Z').replace(/\s/g,' '),'10/31 01:30');
assert.deepEqual(m.presetRange('week',new Date('2026-10-30T17:00:00Z')),{from:'2026-10-25',to:'2026-10-31'});
assert.deepEqual(m.presetRange('thisMonth',new Date('2026-10-30T17:00:00Z')),{from:'2026-10-01',to:'2026-10-31'});
assert.equal(m.readFilters('?from=2026-02-30&provider=other',new Date('2026-10-31T00:00:00Z')).from,'2026-10-02');
assert.deepEqual(m.chartSeries([],{from:'2026-10-30',to:'2026-10-31'}).map(row=>[row.day,row.questions]),[['2026-10-30',0],['2026-10-31',0]]);
const rows=[{actor_id:'a',cost_usd:.1,name:'A'},{actor_id:'b',cost_usd:2,name:'B'}];
assert.deepEqual(m.sortPeople(rows).map(row=>row.actor_id),['b','a']);assert.equal(rows[0].actor_id,'a');
assert.equal(m.rangeError({from:'2026-01-01',to:'2027-01-02'}),'日期範圍最多 366 天。');
assert.equal(m.rangeError({from:'2026-01-01',to:'2027-01-01'}),null,'366 day limit is inclusive');
assert.equal(m.rangeError({from:'2024-01-01',to:'2024-12-31'}),null,'leap year allows exactly 366 days');
assert.equal(m.rangeError({from:'2026-10-31',to:'2026-10-01'}),'開始日期不能晚於結束日期。');
assert.equal(m.chartSeries([],{from:'2026-01-01',to:'2026-03-03'}).length,62,'full ledger range includes inactive days');
const weekly=m.chartSeries([{day:'2026-01-01',questions:2,input_tokens:10,output_tokens:20,cost_usd:.1},{day:'2026-01-07',questions:3,input_tokens:30,output_tokens:40,cost_usd:.2},{day:'2026-03-04',questions:4,input_tokens:1,output_tokens:2,cost_usd:.5}],{from:'2026-01-01',to:'2026-03-04'});
assert.equal(weekly.length,9,'all calendar weeks appear');
assert.deepEqual(weekly[0],{day:'2026-01-01',questions:5,input_tokens:40,output_tokens:60,cost_usd:.1+.2,up:undefined,down:undefined});assert.equal(weekly.at(-1).questions,4);
assert.equal(m.chartSeries([],{from:'2024-01-01',to:'2024-12-31'}).length,53,'empty ledger year includes zero weeks');

for(const rating of ['', 'down', 'up', 'none']) {
 const value={...filters,rating};
 assert.deepEqual(m.readFilters(m.filterQuery(value)),value);
 assert.equal(new URLSearchParams(m.filterQuery(value)).has('rating'),!!rating);
}
assert.equal(m.readFilters('?rating=invalid').rating,'');
assert.equal(m.formatPercent(2/3),'66.7%');
assert.equal(m.formatPercent(0),'0.0%');
assert.equal(m.formatPercent(null),'尚無評分');
assert.equal(m.satisfaction({down:3}),'待確認');
assert.equal(m.satisfaction({}),'待確認');
assert.deepEqual(m.reasonSeries({slow:2,wrong:3}),[
 {key:'wrong',label:'答錯',value:3},{key:'incomplete',label:'不完整',value:undefined},
 {key:'slow',label:'太慢',value:2},{key:'other',label:'其他',value:undefined},{key:'unspecified',label:'未填寫',value:undefined}
]);
assert.deepEqual(m.reasonSeries(undefined).map(row=>row.value),[undefined,undefined,undefined,undefined,undefined]);
assert.equal(m.reasonSeries({slow:2,wrong:3},7).at(-1).value,undefined,'a missing reason count remains unknown');
assert.equal(m.reasonSeries({slow:2,unspecified:0},7).at(-1).value,0,'an explicit zero is kept');
assert.deepEqual(m.sortPeople([{actor_id:'a',down:2},{actor_id:'b'},{actor_id:'c',down:10}],'down').map(row=>row.actor_id),['c','a','b']);
assert.deepEqual(m.sortProviders([{provider:'claude',up:10},{provider:'gpt'}],'up','asc').map(row=>row.provider),['gpt','claude']);
assert.equal(m.chartSeries([],{from:'2026-10-01',to:'2026-10-01'}).length,1);
const feedbackWeeks=m.chartSeries([{day:'2026-01-01',questions:5,input_tokens:0,output_tokens:0,cost_usd:0,up:1,down:2},{day:'2026-01-02',questions:3,input_tokens:0,output_tokens:0,cost_usd:0,down:3}],{from:'2026-01-01',to:'2026-03-04'});
assert.equal(feedbackWeeks[0].down,5);assert.equal(feedbackWeeks[0].up,undefined);
console.log('Token dashboard model, feedback query, percentages, reasons, sorting and weekly feedback passed');

assert.deepEqual(m.reasonSeries({unspecified:3}).at(-1),{key:'unspecified',label:'未填寫',value:3});

for(const scope of ['global','project',''])assert.equal(m.readFilters(m.filterQuery({...filters,scope})).scope,scope);
assert.equal(m.readFilters('?scope=invalid').scope,'');assert.equal(m.scopeLabel(undefined),'—');assert.equal(m.scopeLabel('global'),'全域');assert.equal(m.scopeLabel('project'),'案件');

assert.equal(m.contentText(undefined),'—');assert.equal(m.contentText(null),'（未保存內容）');assert.equal(m.contentText('<script> **問題**'),'<script> **問題**');assert.equal(m.toolLabel('case_progress'),'案件進度');assert.equal(m.toolLabel('new_tool'),'new_tool');assert.equal(m.exportUrl(filters),'/api/ai/usage/export?'+m.filterQuery(filters));

const active=[1,4,10,18,30].map(day=>({day:`2026-10-${String(day).padStart(2,'0')}`,questions:2,input_tokens:3,output_tokens:4,cost_usd:.01}));
const calendar=m.chartSeries(active,{from:'2026-10-01',to:'2026-10-30'});
assert.equal(calendar.length,30);assert.equal(calendar.filter(r=>r.questions===0).length,25);assert.equal(calendar[9].questions,2);assert.equal(calendar[29].questions,2);assert.equal(calendar[1].input_tokens,0);assert.equal(calendar[1].up,undefined,'absent feedback remains unknown');
const week=m.chartSeries([active[0]],{from:'2026-10-01',to:'2026-10-07'});assert.equal(week.length,7);assert.equal(week.filter(r=>r.questions===0).length,6);
