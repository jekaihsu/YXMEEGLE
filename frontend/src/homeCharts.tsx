export type HomeBar={label:string;completed:number;open:number;overdue:number};
export function WorkloadChart({rows,label}:{rows:HomeBar[];label:string}){
 const max=Math.max(1,...rows.map(row=>row.completed+row.open+row.overdue));
 return <figure className="home-chart" aria-label={label}>
  {rows.map(row=><div className="home-chart-row" key={row.label}>
   <span>{row.label}</span><div className="home-bar" aria-hidden="true">
    <i className="home-bar-completed" style={{width:`${row.completed/max*100}%`}}/>
    <i className="home-bar-open" style={{width:`${row.open/max*100}%`}}/>
    <i className="home-bar-overdue" style={{width:`${row.overdue/max*100}%`}}/>
   </div><small>已完成 {row.completed} · 未逾期 {row.open} · 逾期 {row.overdue}</small>
  </div>)}
  {!rows.length&&<figcaption>目前沒有可顯示的工作量。</figcaption>}
 </figure>;
}
export function DeadlineStrip({days}:{days:{day:string;count:number}[]}){
 const max=Math.max(1,...days.map(day=>day.count));
 return <figure className="home-deadline-chart" aria-label="未來七天每日到期工作數">
  {days.map(({day,count})=><div key={day}><span>{count} 項</span><div aria-hidden="true"><i style={{height:`${count/max*100}%`}}/></div><small>{day.slice(5).replace('-','/')}</small></div>)}
 </figure>;
}
export function StatusChart({counts}:{counts:Record<string,number>}){
 const labels:Record<string,string>={pending:'未開始',in_progress:'進行中',paused:'暫停',blocked:'受阻',completed:'已完成',engineering_complete:'工程已交付',superseded:'已取代'};
 const total=Object.values(counts).reduce((sum,n)=>sum+n,0);
 return <figure className="home-chart" aria-label="案件執行狀態分布">
  <div className="home-status-bar" aria-hidden="true">{Object.entries(counts).filter(([,count])=>count>0).map(([key,count],i)=><i key={key} style={{flex:count,opacity:1-i%3*.2}}/>)}</div>
  <figcaption>{Object.entries(counts).map(([key,count])=><span key={key}>{labels[key]||key} {count} 件　</span>)}{!total&&'目前沒有案件狀態資料。'}</figcaption>
 </figure>;
}

export function ReportBars({rows,label}:{rows:import('./homeReportInsights').ReportBar[];label:string}){
 const max=Math.max(0,...rows.flatMap(row=>row.value===null?[]:[row.value]))||1;
 return <figure className="home-chart home-report-bars" aria-label={label}>{rows.map((row,index)=><div className={`home-chart-row${row.muted?' is-muted':''}`} key={index}><span>{row.label}</span><strong>{row.display}</strong><div className="home-bar" aria-hidden="true">{row.value!==null&&<i style={{width:`${Math.max(0,row.value/max*100)}%`}}/>}</div></div>)}{!rows.length&&<figcaption>目前沒有可比較的資料。</figcaption>}</figure>;
}
export function ReportTrend({data}:{data:import('./reports/types').Review['trend']}){
 const rows=data.slice(-12),max=Math.max(.01,...rows.map(r=>r.error_rate??0))*1.35;
 const x=(i:number)=>36+i*488/Math.max(1,rows.length-1),y=(n:number)=>140-n/max*112;
 const last=rows.at(-1);
 return <figure className="home-chart home-report-trend"><svg viewBox="0 0 560 180" role="img" aria-label={'外業失誤率 12 週趨勢。'+rows.map(r=>r.week+' '+(r.error_rate===null?'無資料':(r.error_rate*100).toFixed(1)+'%')).join('；')}>
  {[0,.5,1].map(v=><g key={v}><line x1="36" x2="524" y1={y(max*v)} y2={y(max*v)}/><text x="32" y={y(max*v)+4} textAnchor="end">{(max*v*100).toFixed(0)}%</text></g>)}
  {rows.slice(1).map((row,i)=>{const prev=rows[i];return row.error_rate!==null&&prev.error_rate!==null?<line className="home-report-line" key={row.week} x1={x(i)} x2={x(i+1)} y1={y(prev.error_rate)} y2={y(row.error_rate)}/>:null})}
  {last&&last.error_rate!==null&&<g><circle cx={x(rows.length-1)} cy={y(last.error_rate)} r="4"/><text x={x(rows.length-1)} y={y(last.error_rate)-12} textAnchor="end">本週 {(last.error_rate*100).toFixed(1)}%</text></g>}
  {rows.length>0&&<><text x="36" y="168">{rows[0].week.slice(5)}</text><text x="524" y="168" textAnchor="end">{last?.week.slice(5)}</text></>}
 </svg>{!rows.length&&<figcaption>趨勢來源尚未提供。</figcaption>}</figure>;
}
