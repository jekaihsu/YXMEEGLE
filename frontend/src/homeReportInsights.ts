import type {Gap,HomeReport} from './reports/types';
import {REPORT_CARDS,reportHref,type ReportCardId} from './homeReportCards';
export type ReportBar={label:string;value:number|null;display:string;muted?:boolean};
export type ReportInsight={sentence:string;notes:string[];bars:ReportBar[];available:boolean};
export const percent=(n:number|null,digits=0)=>n===null?'—':(n*100).toFixed(digits)+'%';
export function reportMoney(n:number|null){return n===null?'—':n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'K':n.toLocaleString('zh-TW')}
export function reportWeek(week:string){const end=new Date(week+'T00:00:00Z');if(!Number.isFinite(end.getTime()))return week;end.setUTCDate(end.getUTCDate()+6);return week.replaceAll('-','/')+'～'+end.toISOString().slice(0,10).replaceAll('-','/')}
function cappedNotes(coverage:string[],gaps:Gap[]){
 const messages=gaps.map(g=>g.message);
 if(coverage.length+messages.length<=2)return [...coverage,...messages];
 const fixed=coverage.length>1?[coverage.join('；')]:coverage;
 const shown=messages.slice(0,1-fixed.length);
 return [...fixed,...shown,`另有 ${messages.length-shown.length} 項資料缺口，詳見 PM 週報`];
}
const unavailable=():ReportInsight=>({sentence:'週報資料暫時無法提供。',notes:['來源尚未提供，未以 0 代替。'],bars:[],available:false});
const bar=(label:string,value:number|null,display=percent(value)):ReportBar=>({label,value,display});
export function attentionTiles(r:HomeReport){return [
 {label:'外業已退回 · 待複查',value:r.quality?String(r.quality.kpi.returned):'—',note:r.quality?'':'外業檢核資料尚未提供',href:reportHref('review'),warning:false},
 {label:'可請款未請',value:r.sales?.kpi.unbilled_billable==null?'—':'NT$ '+reportMoney(r.sales.kpi.unbilled_billable),note:r.sales?.kpi.unbilled_billable==null?'請款金額尚未提供':'',href:reportHref('sales'),warning:false},
 {label:'應收未收',value:r.sales?.kpi.receivable==null?'—':'NT$ '+reportMoney(r.sales.kpi.receivable),note:r.sales?.kpi.receivable==null?'應收金額尚未提供':'',href:reportHref('sales'),warning:false},
 {label:'儀器送修',value:r.assets?String(r.assets.instrument.kpi.repair):'—',note:r.assets?'':'儀器資料尚未提供',href:reportHref('assets'),warning:(r.assets?.instrument.kpi.repair??0)>0},
]}
function qualityTrend(r:HomeReport):ReportInsight{
 const q=r.quality;if(!q)return unavailable();
 const now=q.kpi.error_rate,prev=q.kpi_prev.error_rate;
 let sentence=now===null?'本週尚無已檢核資料':`本週 ${percent(now,1)}，`+(prev===null?'上週無可比數據':`較上週 ${now>=prev?'+':''}${((now-prev)*100).toFixed(1)}pt`);
 const most=[...q.by_group].sort((a,b)=>b.returned-a.returned)[0];
 if(q.kpi.returned>0&&most&&most.returned>0)sentence+=`。${q.kpi.returned} 筆已退回中，${most.group} 佔 ${percent(most.returned/q.kpi.returned)}`;
 const notes=[`檢核覆蓋率 ${percent(q.kpi.coverage)} (${q.kpi.passed+q.kpi.returned} / ${q.kpi.total})；${q.kpi.pending} 筆待檢核未計入`];
 const office=r.quality_office?.kpi.coverage;
 if(office!=null&&office<.5)notes.push(`內業失誤率目前無法由檢核狀態計算 (覆蓋 ${percent(office)})`);
 return {available:true,sentence,notes:cappedNotes(notes,[...q.gaps,...(r.quality_office?.gaps??[])].filter((gap,index,all)=>all.findIndex(g=>g.id===gap.id)===index)),bars:[]};
}
function qualityGroups(r:HomeReport):ReportInsight{
 if(!r.quality)return unavailable();
 const ranked=[...r.quality.by_group].filter(g=>g.passed+g.returned>=20).sort((a,b)=>(b.error_rate??-1)-(a.error_rate??-1)).slice(0,5);
 const small=r.quality.by_group.filter(g=>g.passed+g.returned<20);
 const highest=ranked.find(g=>g.error_rate!==null);
 return {available:true,sentence:highest?`${highest.group}最高 (${percent(highest.error_rate)})`:'尚無足夠已檢核樣本可比較各組',notes:cappedNotes(['n 為已通過 + 已退回筆數；n < 20 的組別只供參考。'],r.quality.gaps),bars:[...ranked.map(g=>bar(`${g.group} · n=${g.passed+g.returned}`,g.error_rate)),...small.map(g=>({...bar(`${g.group} · 樣本少 · n=${g.passed+g.returned}`,g.error_rate),muted:true}))]};
}
function funnel(r:HomeReport):ReportInsight{
 if(!r.sales)return unavailable();
 const k=r.sales.kpi,ratios:string[]=[],amounts:string[]=[];
 if(k.contract_total!==null&&k.contract_total>0){if(k.billed_total!==null)ratios.push(`已請款 ${percent(k.billed_total/k.contract_total)}`);if(k.received_total!==null)ratios.push(`已入帳 ${percent(k.received_total/k.contract_total)}`)}
 if(k.unbilled_billable!==null)amounts.push(`可請款未請 NT$ ${reportMoney(k.unbilled_billable)}`);
 if(k.receivable!==null)amounts.push(`應收未收 NT$ ${reportMoney(k.receivable)}`);
 const notes:string[]=[];
 if(r.sales.by_status.some(s=>!s.status.trim()||/未知|不明|unknown/i.test(s.status))&&!r.sales.gaps.some(g=>g.id==='sales-status'))notes.push('部分案件狀態空白或未知，統計範圍尚待核對。');
 if([k.contract_total,k.billed_total,k.received_total].some(n=>n===null))notes.push('部分金額來源尚未提供，未以 0 代替。');
 return {available:true,sentence:[ratios.join('，'),amounts.join('，')].filter(Boolean).join('。')||'金額來源尚未提供',notes:cappedNotes(notes.length||r.sales.gaps.length?notes:['僅涵蓋週報已納入的案件與金額。'],r.sales.gaps),bars:[bar('合約',k.contract_total,reportMoney(k.contract_total)),bar('已請款',k.billed_total,reportMoney(k.billed_total)),bar('已入帳',k.received_total,reportMoney(k.received_total))]};
}
function receivables(r:HomeReport):ReportInsight{
 if(!r.sales)return unavailable();
 const complete=r.sales.kpi.receivable!==null&&!r.sales.gaps.length;
 return {available:true,sentence:r.sales.top_receivable.length?`應收未收 NT$ ${reportMoney(r.sales.kpi.receivable)}，依金額列出前 ${r.sales.top_receivable.length} 案`:complete&&r.sales.kpi.receivable===0?'目前沒有應收未收案件':'應收案件明細暫時無法提供',notes:cappedNotes(['僅列應收未收金額大於 0 的案件。'],r.sales.gaps),bars:[]};
}
function achievement(r:HomeReport):ReportInsight{
 const p=r.progress;if(!p)return unavailable();
 const lowest=[...p.by_group].filter(g=>g.achievement!==null).sort((a,b)=>(a.achievement??0)-(b.achievement??0))[0];
 const sentence=(p.kpi.achievement===null?'整體達成率尚無可計算資料':`整體 ${percent(p.kpi.achievement)}`)+(lowest?`，${lowest.group_label||lowest.group} ${percent(lowest.achievement)} 最低`:'');
 return {available:true,sentence,notes:cappedNotes([(p.basis==='days'?'依預排天數':'依點數')+(p.kpi.unplanned_days===undefined?'':`；未預排工作 ${p.kpi.unplanned_days} 天`)],p.gaps),bars:p.by_group.map(g=>bar(g.group_label||g.group,g.achievement))};
}
function assets(r:HomeReport,kind:'instrument'|'vehicle'):ReportInsight{
 if(!r.assets)return unavailable();
 const k=r.assets[kind].kpi,unit=kind==='instrument'?'項':'台';
 const rows=[bar('總數',k.total,`${k.total} ${unit}`),bar('使用中',k.in_use,`${k.in_use} ${unit}`),bar('閒置',k.idle,`${k.idle} ${unit}`),...(kind==='instrument'?[bar('送修',k.repair,`${k.repair} ${unit}`)]:[])];
 return {available:true,sentence:`共 ${k.total} ${unit}，使用中 ${k.in_use} ${unit}，閒置 ${k.idle} ${unit}`+(kind==='instrument'?`，送修 ${k.repair} ${unit}`:''),notes:cappedNotes(['依週報資源狀態統計。',...r.assets[kind].gaps.filter(g=>g.id==='asset-inspections').map(g=>g.message)],r.assets[kind].gaps.filter(g=>g.id!=='asset-inspections')),bars:rows};
}
const insights:Record<ReportCardId,(r:HomeReport)=>ReportInsight>={attention:r=>({available:true,sentence:'追蹤本週檢核、請款與資源事項',notes:['各項依週報來源；缺少資料以 — 顯示。'],bars:attentionTiles(r).map(t=>bar(t.label,null,t.value))}),qualityTrend,qualityGroups,funnel,receivables,achievement,instruments:r=>assets(r,'instrument'),vehicles:r=>assets(r,'vehicle')};
export const reportInsight=(r:HomeReport,id:ReportCardId)=>insights[id](r);
export function copySummary(r:HomeReport){return [`PM 週報 · ${reportWeek(r.week)}`,...Object.entries(REPORT_CARDS).map(([id,card])=>{const insight=reportInsight(r,id as ReportCardId);return `${card.title}：${insight.sentence}${id==='attention'?'。'+attentionTiles(r).map(t=>`${t.label} ${t.value}`).join('；'):''}\n${insight.notes.join('；')}`}),...(r.meta.stale||r.meta.refresh_error?['週報資料為舊快照']:[])].join('\n')}
