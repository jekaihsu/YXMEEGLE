import {useState} from 'react';
import {Button} from '../design';
import {Card,Message} from '../homeCards';
import {ReportBars,ReportTrend} from '../homeCharts';
import {REPORT_CARDS,reportHref,type ReportCardId} from '../homeReportCards';
import {attentionTiles,copySummary,reportInsight,reportMoney,reportWeek} from '../homeReportInsights';
import type {HomeReportsRead} from '../useHomeReports';
import type {HomeReport} from '../reports/types';
function Attention({report}:{report:HomeReport}){return <nav className="home-report-attention" aria-label="週報待追蹤">{attentionTiles(report).map(tile=><a href={tile.href} key={tile.label}><strong data-tone={tile.warning?'warning':undefined}>{tile.value}</strong><span>{tile.label}</span>{tile.note&&<small>{tile.note}</small>}</a>)}</nav>}
function Receivables({report}:{report:HomeReport}){return <div className="home-report-receivables">{report.sales?.top_receivable.map(row=><div className="home-report-receivable" key={row.id}><span>{row.code} {row.name}<small>{row.client||'客戶尚未提供'}</small></span><strong>NT$ {reportMoney(row.receivable)}</strong></div>)}</div>}
const visuals:Record<ReportCardId,(report:HomeReport)=>React.ReactNode>={attention:report=><Attention report={report}/>,qualityTrend:report=>report.quality&&<ReportTrend data={report.quality.trend}/>,qualityGroups:report=><ReportBars rows={reportInsight(report,'qualityGroups').bars} label="各組失誤率"/>,funnel:report=><ReportBars rows={reportInsight(report,'funnel').bars} label="合約、請款與入帳"/>,receivables:report=><Receivables report={report}/>,achievement:report=><ReportBars rows={reportInsight(report,'achievement').bars} label="各組預排達成率"/>,instruments:report=><ReportBars rows={reportInsight(report,'instruments').bars} label="儀器狀態"/>,vehicles:report=><ReportBars rows={reportInsight(report,'vehicles').bars} label="車輛狀態"/>};
export function ReportCard({id,read}:{id:ReportCardId;read:HomeReportsRead}){
 const report=read.data,insight=report&&reportInsight(report,id);
 return <Card id={id} subtitle={report?'PM 週報 · '+reportWeek(report.week):'PM 週報'} href={reportHref(REPORT_CARDS[id].tab)} action="開啟 PM 週報">
  {read.error&&<Message>{report?read.error:'週報資料暫時無法提供，請稍後重新讀取。'}</Message>}
  {insight&&report?<><p className="home-report-sentence">{insight.sentence}</p>{insight.available&&visuals[id](report)}{insight.notes.map((note,index)=><p key={index} className="home-source-note">{note}</p>)}</>:!read.error&&<Message>{read.loading?'週報讀取中…':'週報資料暫時無法提供。'}</Message>}
 </Card>;
}
export function CopyReportSummary({report}:{report:HomeReport}){
 const [status,setStatus]=useState(''),[manual,setManual]=useState(false);
 const copy=async()=>{try{if(!navigator.clipboard?.writeText)throw new Error();await navigator.clipboard.writeText(copySummary(report));setStatus('已複製週報摘要');setManual(false)}catch{setStatus('剪貼簿無法使用，請手動複製下方摘要。');setManual(true)}};
 return <div className="home-report-copy"><Button onClick={()=>void copy()}>複製週報摘要</Button>{status&&<p role="status" className="home-source-note">{status}</p>}{manual&&<textarea aria-label="週報摘要" readOnly value={copySummary(report)}/>}</div>;
}
