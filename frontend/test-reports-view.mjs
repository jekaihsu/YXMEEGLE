import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
const result=await build({entryPoints:['src/reports/reportsView.ts'],bundle:true,write:false,platform:'node',format:'esm'});
const {rate,number,clamp,query,shiftWeek,lastWeek,change,safeLink,compactMoney,sample}=await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
assert.equal(rate(null),'無法計算');assert.equal(rate(47/408),'11.5%');assert.equal(rate(0),'0%');assert.equal(number(null),'—');assert.equal(clamp(1.4),1);assert.equal(clamp(-1),0);assert.equal(clamp(NaN),0);
assert.equal(query({group:'外業一組',offset:0,limit:50,q:'',status:undefined}),'group=%E5%A4%96%E6%A5%AD%E4%B8%80%E7%B5%84&offset=0&limit=50');
assert.equal(shiftWeek('2026-01-05',-1),'2025-12-29');assert.equal(lastWeek(new Date('2026-10-11T16:01:00Z')),'2026-10-05');assert.equal(lastWeek(new Date('2026-10-11T15:59:00Z')),'2026-09-28');
assert.equal(change(null,.1),'前週無可比較資料');assert.equal(change(.1,.12),'較前週 -2 個百分點');assert.equal(safeLink('javascript:alert(1)'),undefined);assert.equal(safeLink('https://example.com'),'https://example.com');
assert.equal(compactMoney(385000000),'NT$ 3.9 億');
console.log('Reports view-model assertions passed.');

assert.equal(compactMoney(null),'來源無資料');assert.equal(sample(10),'10 筆已檢核 · 樣本少');assert.equal(sample(20),'20 筆已檢核');
const chartBundle=await build({stdin:{contents:"import {renderToStaticMarkup} from 'react-dom/server';import TrendChart from './src/reports/charts/TrendChart';export const review=renderToStaticMarkup(<TrendChart label='檢核趨勢' data={[{week:'2026-10-05',total:42,passed:0,returned:10,error_rate:1}]}/>);export const assets=renderToStaticMarkup(<TrendChart label='使用趨勢' barLabel='使用次數' data={[{week:'2026-10-05',total:773}]}/>);",resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic'});
const chartModule={exports:{}};new Function('require','module','exports',chartBundle.outputFiles[0].text)(createRequire(import.meta.url),chartModule,chartModule.exports);const chart=chartModule.exports;
assert.match(chart.review,/10 筆已檢核 · 樣本少/);assert.match(chart.assets,/使用次數（左軸）/);assert.doesNotMatch(chart.assets,/386\.5|失誤率/);assert.doesNotMatch(chart.assets,/tabindex="0"/);

const fixes=await build({loader:{'.css':'empty'},stdin:{contents:`import {renderToStaticMarkup as render} from 'react-dom/server';import TrendChart from './src/reports/charts/TrendChart';import BarList from './src/reports/charts/BarList';import {MetaNotice,ReportState,Select} from './src/reports/shared';export const chart=render(<TrendChart label="週報" data={[{week:'2026-10-05',total:2}]} onSelect={()=>{}}/>);export const bars=render(<BarList label="排行" data={[{label:'A',value:1}]}/>);export const error=render(<ReportState loading={false} error="failed" retry={()=>{}}/>);export const meta=render(<MetaNotice meta={{fetched_at:'',stale:true,refresh_error:true,snapshot:'',gaps:[]}}/>);export const select=render(<Select label="人員" value="" onChange={()=>{}} options={['A','A']}/>);`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic'});
const fm={exports:{}};new Function('require','module','exports',fixes.outputFiles[0].text)(createRequire(import.meta.url),fm,fm.exports);
assert.match(fm.exports.chart,/<button/);assert.doesNotMatch(fm.exports.chart,/role="button"/);assert.match(fm.exports.chart,/role="group"/);
assert.match(fm.exports.error,/role="alert"/);assert.doesNotMatch(fm.exports.meta,/Invalid Date/);assert.match(fm.exports.meta,/更新失敗，顯示舊資料/);
assert.equal((fm.exports.select.match(/value="A"/g)||[]).length,1);

const sortModel=await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);for(const key of ['group','pm','status','category','case_code'])assert.equal(sortModel.nextSortOrder('points','desc',key),'asc');for(const key of ['points','diff','contract','uses'])assert.equal(sortModel.nextSortOrder('group','asc',key),'desc');assert.equal(sortModel.nextSortOrder('diff','desc','diff'),'asc');assert.equal(sortModel.nextSortOrder('group','asc','group'),'desc');
