import assert from 'node:assert/strict';
import {build} from 'esbuild';
const result=await build({entryPoints:['src/tokenDashboardModel.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const m=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'));
const filters={from:'2026-10-01',to:'2026-10-31',actor:'王 & a',provider:'gpt',rating:'down'};
assert.deepEqual(m.readFilters(m.filterQuery(filters)),filters);
for(const path of ['/token_dashboard','/token_dashboard/','/token_dashboard///'])assert.equal(m.isTokenDashboardPath(path),true);
for(const path of ['/token_dashboard_x','/x/token_dashboard','/','/TOKEN_DASHBOARD'])assert.equal(m.isTokenDashboardPath(path),false);
assert.equal(m.canViewUsage('manager'),true);
for(const role of ['member','admin','',undefined])assert.equal(m.canViewUsage(role),false);
assert.equal(m.formatNumber(1234567),'1,234,567');
assert.equal(m.formatNumber(12.2),'12');
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
assert.equal(m.chartSeries([],{from:'2026-01-01',to:'2026-03-03'}).length,62,'62 days stay daily');
const weekly=m.chartSeries([{day:'2026-01-01',questions:2,input_tokens:10,output_tokens:20,cost_usd:.1},{day:'2026-01-07',questions:3,input_tokens:30,output_tokens:40,cost_usd:.2},{day:'2026-03-04',questions:4,input_tokens:1,output_tokens:2,cost_usd:.5}],{from:'2026-01-01',to:'2026-03-04'});
assert.equal(weekly.length,9,'63 days aggregate into nine weeks');
assert.deepEqual(weekly[0],{day:'2026-01-01',questions:5,input_tokens:40,output_tokens:60,cost_usd:.1+.2,up:0,down:0});assert.equal(weekly.at(-1).questions,4);
assert.equal(m.chartSeries([],{from:'2024-01-01',to:'2024-12-31'}).length,53,'year renders at most 53 bars');

for(const rating of ['', 'down', 'up', 'none']) {
 const value={...filters,rating};
 assert.deepEqual(m.readFilters(m.filterQuery(value)),value);
 assert.equal(new URLSearchParams(m.filterQuery(value)).has('rating'),!!rating);
}
assert.equal(m.readFilters('?rating=invalid').rating,'');
assert.equal(m.formatPercent(2/3),'66.7%');
assert.equal(m.formatPercent(0),'0.0%');
assert.equal(m.formatPercent(null),'尚無評分');
assert.equal(m.satisfaction({down:3}),'0.0%');
assert.equal(m.satisfaction({}),'尚無評分');
assert.deepEqual(m.reasonSeries({slow:2,wrong:3}),[
 {key:'wrong',label:'答錯',value:3},{key:'incomplete',label:'不完整',value:0},
 {key:'slow',label:'太慢',value:2},{key:'other',label:'其他',value:0}
]);
assert.deepEqual(m.reasonSeries(undefined).map(row=>row.value),[0,0,0,0]);
assert.deepEqual(m.sortPeople([{actor_id:'a',down:2},{actor_id:'b'},{actor_id:'c',down:10}],'down').map(row=>row.actor_id),['c','a','b']);
assert.deepEqual(m.sortProviders([{provider:'claude',up:10},{provider:'gpt'}],'up','asc').map(row=>row.provider),['gpt','claude']);
assert.equal(m.chartSeries([],{from:'2026-10-01',to:'2026-10-01'})[0].down,0);
const feedbackWeeks=m.chartSeries([{day:'2026-01-01',questions:5,input_tokens:0,output_tokens:0,cost_usd:0,up:1,down:2},{day:'2026-01-02',questions:3,input_tokens:0,output_tokens:0,cost_usd:0,down:3}],{from:'2026-01-01',to:'2026-03-04'});
assert.equal(feedbackWeeks[0].down,5);assert.equal(feedbackWeeks[0].up,1);
console.log('Token dashboard model, feedback query, percentages, reasons, sorting and weekly feedback passed');
