import assert from 'node:assert/strict';
import {build} from 'esbuild';
import fs from 'node:fs/promises';
import {homeReportFixture} from './home-reports-fixture.mjs';
const bundle=await build({stdin:{contents:"export * from './src/homeReportInsights';export * from './src/homeReports';",resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm'});
const file=new URL('./.home-reports-test.mjs',import.meta.url);await fs.writeFile(file,bundle.outputFiles[0].text);
let m;try{m=await import(file.href)}finally{await fs.unlink(file)}
let checks=0;const equal=(actual,expected)=>{assert.deepEqual(actual,expected);checks++};
const r=m.parseHomeReport(homeReportFixture());
equal(m.reportInsight(r,'qualityTrend').sentence,'本週 11.5%，較上週 +2.1pt。47 筆已退回中，測量二組 佔 38%');
equal(m.reportInsight(r,'qualityTrend').notes,['檢核覆蓋率 50% (408 / 813)；405 筆待檢核未計入','內業失誤率目前無法由檢核狀態計算 (覆蓋 3%)','內業檢核狀態：來源尚未建立']);
equal(m.reportInsight({...r,quality:{...r.quality,kpi:{...r.quality.kpi,error_rate:null,returned:0}}},'qualityTrend').sentence,'本週尚無已檢核資料');
equal(m.reportInsight({...r,quality:{...r.quality,kpi_prev:{...r.quality.kpi_prev,error_rate:null}}},'qualityTrend').sentence,'本週 11.5%，上週無可比數據。47 筆已退回中，測量二組 佔 38%');
equal(m.reportInsight(r,'qualityGroups').sentence,'測量二組最高 (18%)');
equal(m.reportInsight(r,'qualityGroups').bars.at(-1),{label:'內業組 · 樣本少 · n=12',value:.04,display:'4%',muted:true});
equal(m.reportInsight({...r,quality:{...r.quality,by_group:[r.quality.by_group.at(-1)]}},'qualityGroups').sentence,'尚無足夠已檢核樣本可比較各組');
equal(m.reportInsight(r,'funnel').sentence,'已請款 68%，已入帳 51%。可請款未請 NT$ 3.2M，應收未收 NT$ 8.1M');
equal(m.reportInsight(r,'funnel').notes,['417 件案件狀態空白，未納入。']);
const nullTotals={...r,sales:{...r.sales,kpi:{cases:0,contract_total:null,billed_total:null,received_total:null,unbilled_billable:null,receivable:null}}};
equal(m.reportInsight(nullTotals,'funnel').sentence,'金額來源尚未提供');
equal(m.reportInsight(nullTotals,'funnel').bars.map(b=>[b.value,b.display]),[[null,'—'],[null,'—'],[null,'—']]);
equal(m.attentionTiles(nullTotals).map(t=>t.value),['47','—','—','7']);
equal(m.attentionTiles(r).map(t=>t.warning),[false,false,false,true]);
equal(m.reportInsight(r,'achievement').sentence,'整體 86%，測量二組 61% 最低');
equal(m.reportInsight(r,'achievement').notes,['依預排天數；未預排工作 6 天']);
equal(m.reportInsight(r,'instruments').sentence,'共 148 項，使用中 100 項，閒置 41 項，送修 7 項');
equal(m.reportInsight(r,'vehicles').sentence,'共 21 台，使用中 17 台，閒置 4 台');
equal(m.reportInsight(r,'receivables').sentence,'應收未收 NT$ 8.1M，依金額列出前 5 案');
equal(m.reportInsight({...r,meta:{...r.meta,gaps:[]},sales:{...r.sales,kpi:{...r.sales.kpi,receivable:0},top_receivable:[]}},'receivables').sentence,'目前沒有應收未收案件');
equal(m.reportInsight({...r,sales:null},'receivables').sentence,'週報資料暫時無法提供。');
const empty={...r,quality:null,quality_office:null,sales:null,progress:null,assets:null};
equal(m.parseHomeReport(empty),empty);
equal(m.attentionTiles(empty).map(t=>t.value),['—','—','—','—']);
for(const mutate of [r=>delete r.quality.kpi.total,r=>r.sales.kpi.billed_total='0',r=>r.meta.gaps[0].severity='bad',r=>r.assets.instrument.kpi.repair=NaN,r=>delete r.progress,r=>r.quality.trend[0].error_rate=undefined,r=>r.progress.basis='hours',r=>r.sales.top_receivable[0].client=7]){const bad=homeReportFixture();mutate(bad);assert.throws(()=>m.parseHomeReport(bad),/資料格式不正確/);checks++}
equal(m.reportWeek(r.week),'2026/10/12～2026/10/18');
const summary=m.copySummary(empty);
equal(summary,`PM 週報 · 2026/10/12～2026/10/18
週報待追蹤：追蹤本週檢核、請款與資源事項。外業已退回 · 待複查 —；可請款未請 —；應收未收 —；儀器送修 —
各項依週報來源；缺少資料以 — 顯示。
外業失誤率 · 12 週：週報資料暫時無法提供。
來源尚未提供，未以 0 代替。
各組失誤率：週報資料暫時無法提供。
來源尚未提供，未以 0 代替。
合約 → 請款 → 入帳：週報資料暫時無法提供。
來源尚未提供，未以 0 代替。
應收未收前 5 案：週報資料暫時無法提供。
來源尚未提供，未以 0 代替。
預排達成率：週報資料暫時無法提供。
來源尚未提供，未以 0 代替。
儀器：週報資料暫時無法提供。
來源尚未提供，未以 0 代替。
車輛：週報資料暫時無法提供。
來源尚未提供，未以 0 代替。`);
equal(m.copySummary({...empty,meta:{...r.meta,stale:true}}).endsWith('週報資料為舊快照'),true);
console.log(`Home reports: ${checks} literal parser, insight and summary checks passed.`);
