import type {SourceHealthView} from './sourceHealthView';
import {taipeiTime} from './taipeiTime';
import './source-health.css';

export interface SourceHealthProps {
 view?:SourceHealthView|null;
 onRetry?:(handle:unknown)=>void;
 busy?:boolean;
}
export function successfulRead(value:string|null,now=Date.now()):string {
 if(!value || !Number.isFinite(Date.parse(value)))return '尚無成功紀錄';
 const seconds=Math.max(0,Math.floor((now-Date.parse(value))/1000));
 const relative=seconds<60?`${seconds} 秒前`:seconds<3600?`${Math.floor(seconds/60)} 分鐘前`:seconds<86400?`${Math.floor(seconds/3600)} 小時前`:`${Math.floor(seconds/86400)} 天前`;
 return `${taipeiTime(value)} · ${relative}`;
}
export function SourceHealth({view,onRetry,busy=false}:SourceHealthProps) {
 const diagnostic=view?.diagnostic,rows=diagnostic?.rows??[];
 const state=view?.page?.reported?view.page.statusLabel:rows.length&&rows.every(row=>row.dataState===null)?'已讀取':'狀態未知';
 return <div className="source-health-root">
  <section className="source-health-banner" role="status" aria-label="頁面資料狀態">
   <h1>來源與資料健康</h1><span className="source-health-status-badge">{state}</span>
   <p>最近成功讀取 · {diagnostic?.summary.last_success.value?successfulRead(diagnostic.summary.last_success.value):rows.some(row=>row.last_success.value)?'部分來源時間未知':'尚無成功紀錄'}</p>
  </section>
  <section className="source-health-diagnostic-section" aria-label="來源健康診斷">
   {rows.length?<div className="source-read-list">{rows.map(row=><article className="source-read-row" key={row.key}>
    <div><h2>{row.name??'未命名來源'}</h2><span className="source-health-tag">{row.dataState===null?'已讀取':row.statusLabel}</span></div>
    <p>最近成功 · {successfulRead(row.last_success.value)}</p>
    {row.lastErrorSummary&&<p className="source-read-error">{row.lastErrorSummary}</p>}
    {row.retry&&onRetry?<button type="button" className="source-health-btn-retry" disabled={busy} onClick={()=>onRetry(row.retry!.handle)}>{busy?'更新中…':'重試'}</button>:row.needsAttention&&<span>待處理</span>}
   </article>)}</div>:<p>{view?.page.states.includes('loading')?'讀取中…':'尚無可見來源'}</p>}
  </section>
 </div>;
}
