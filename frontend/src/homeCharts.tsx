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
