import {DataState} from './design/DataState';
import type {SourceHealthView} from './sourceHealthView';
import {taipeiTime} from './taipeiTime';
import './source-health.css';

export interface SourceHealthProps {
 view?:SourceHealthView|null;
 onRetry?:(handle:unknown)=>void;
 busy?:boolean;
 onReload?:()=>void;
}
export function successfulRead(value:string|null,_now=Date.now()):string {
 if(!value || !Number.isFinite(Date.parse(value)))return '尚無成功紀錄';
 return taipeiTime(value);
}
export function SourceHealth({view,onRetry,onReload,busy=false}:SourceHealthProps) {
 const diagnostic=view?.diagnostic,rows=diagnostic?.rows??[];
 const shared=rows.length>0&&rows.every(row=>row.stale&&row.dataState?.states.length===1);
 const state=view?.page?.reported?view.page.statusLabel:rows.length&&rows.every(row=>row.dataState===null)?'已讀取':'狀態未知';
 return <div className="source-health-root">
  <section className="source-health-banner" role="status" aria-label="頁面資料狀態">
   <h1>資料來源</h1>{onReload&&<button className="source-health-btn-retry" disabled={busy} onClick={onReload}>重新讀取</button>}<p>來源健康 · 資料時間見最近成功讀取紀錄</p><span className="source-health-status-badge">{shared?`${rows.length} 個來源都標示「資料待更新」`:state}</span>
   <p>最近成功讀取 · {diagnostic?.summary.last_success.value?successfulRead(diagnostic.summary.last_success.value):rows.some(row=>row.last_success.value)?'部分來源時間未知':'尚無成功紀錄'}</p>
  {shared&&<p>來源回報這份快照仍待更新，可能已超過來源新鮮度期限。成功讀取快照不代表已取得最新 Lark 資料；請以資料時間判讀。</p>}</section>
  <section className="source-health-diagnostic-section" aria-label="來源健康診斷">
   {rows.length?<div className="source-read-list">{rows.map(row=><article className="source-read-row" key={row.key}>
    <div><h2>{row.name??'未命名來源'}</h2>{!shared&&row.dataState!==null&&<span className="source-health-tag">{row.statusLabel}</span>}</div>
    <p>最近成功 · {successfulRead(row.last_success.value)}</p>
    {row.lastErrorSummary&&<p className="source-read-error">{row.lastErrorSummary}</p>}
    {row.retry&&onRetry?<button type="button" className="source-health-btn-retry" disabled={busy} onClick={()=>onRetry(row.retry!.handle)}>{busy?'更新中…':'重試'}</button>:row.needsAttention&&<span>待處理</span>}
   </article>)}</div>:<DataState kind={view?.page.states.includes('loading')?'Loading':view?.page.states.includes('forbidden')?'Denied':view?.page.states.includes('read_failed')?'Error':'Empty'} title={view?.page.states.includes('loading')?'正在讀取來源健康':view?.page.states.includes('forbidden')?'無權讀取來源健康':'尚無可見來源'} body="尚無成功紀錄時，來源狀態與筆數皆未知。"/>}
  </section>
 </div>;
}
