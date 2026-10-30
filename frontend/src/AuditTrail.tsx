import {useEffect,useState} from 'react';
import {api,ApiError,getSessionEpoch} from './api';
import type {Project,Workspace} from './types';

let auditEpoch=getSessionEpoch();
const auditPages=new Map<string,{items:any[];total:number;has_more?:boolean}>();
export function auditRecordOrder(a:{created_at?:string;at?:string;id?:string},b:{created_at?:string;at?:string;id?:string}){const x=a.created_at||a.at,y=b.created_at||b.at;return Number(!x)-Number(!y)||String(y||'').localeCompare(String(x||''))||String(b.id||'').localeCompare(String(a.id||''))}
export function AuditTrail({w,p}:{w:Workspace;p:Project}){
 // Every piece of fetched state is tagged with the project (and offset) it was requested for, so a render
 // for another project can never display it, even before an effect has had a chance to clear it.
 const[nav,setNav]=useState({pid:p.id,page:0});const page=nav.pid===p.id?nav.page:0;const setPage=(n:number)=>setNav({pid:p.id,page:n});
 if(nav.pid!==p.id)setNav({pid:p.id,page:0});
 const epoch=getSessionEpoch();if(auditEpoch!==epoch){auditPages.clear();auditEpoch=epoch}const cacheKey=`${p.id}:${page}`;const[retry,setRetry]=useState(0);const[loading,setLoading]=useState(true);
 const requestKey=`${epoch}:${p.id}:${w.version}:${page}`;
 const[loaded,setLoaded]=useState<{key:string;data:{items:any[];total:number;has_more?:boolean}|null;legacy:boolean;error:string}|null>(null);
 useEffect(()=>{const controller=new AbortController();const isCurrent=()=>!controller.signal.aborted&&epoch===getSessionEpoch();setLoading(true);void api<any>(`/api/audit?project_id=${encodeURIComponent(p.id)}&offset=${page*30}&limit=30`,{signal:controller.signal},isCurrent).then(result=>{if(!isCurrent())return;if(!Array.isArray(result.items))throw new Error('操作紀錄格式不完整');auditPages.set(cacheKey,result);if(auditPages.size>50)auditPages.delete(auditPages.keys().next().value!);setLoaded({key:requestKey,data:result,legacy:false,error:''})}).catch(e=>{if(!isCurrent())return;if(e instanceof ApiError&&e.status===404)setLoaded({key:requestKey,data:null,legacy:true,error:''});else {if(e instanceof ApiError&&[401,403].includes(e.status))auditPages.delete(cacheKey);setLoaded({key:requestKey,data:auditPages.get(cacheKey)||null,legacy:false,error:e.message})}}).finally(()=>{if(isCurrent())setLoading(false)});return()=>controller.abort()},[requestKey,p.id,page,epoch,retry]);
 const cur=loaded&&loaded.key===requestKey?loaded:null;const data=cur?.data||auditPages.get(cacheKey)||null;const legacy=!!cur?.legacy;const error=cur?.error||'';
 const old=w.events.filter(e=>e.project_id===p.id).slice().sort(auditRecordOrder);const total=legacy?old.length:data?.total||0;
 const settled=!loading&&!!cur&&(!!data||legacy);const currentPage=settled?Math.min(page,Math.max(1,Math.ceil(total/30))-1):page;const pageOutOfRange=settled&&page!==currentPage;
 const rows=legacy?old.slice(currentPage*30,(currentPage+1)*30):!pageOutOfRange?data?.items||[]:[];
  // Older APIs and the local fallback provide exact totals; bounded API pages mark lower bounds.
 const hasMore=legacy?(currentPage+1)*30<total:data?.has_more??((currentPage+1)*30<total);
 const countLabel=!settled?'筆數尚未確認':data?.has_more?`至少 ${total} 筆`:`共 ${total} 筆`;
 useEffect(()=>{if(pageOutOfRange)setPage(currentPage)},[pageOutOfRange,currentPage,p.id]);
 const days=new Map<string,any[]>();
 for(const row of rows){const day=String(row.created_at||row.at||'').slice(0,10);days.set(day,[...(days.get(day)||[]),row])}
 return <section className="audit-trail audit-screen"><h2>操作紀錄</h2><p>查看誰在何時處理了哪些工作，以及確認、退回和來源更新的記錄。</p>
  {legacy&&<p className="ops-notice">目前服務僅提供舊版活動紀錄；完整變更稽核尚未接通。</p>}
  {error&&<p className="form-error" role="alert">{data&&'上次資料，更新失敗 · '}{error}<button className="text-button" onClick={()=>setRetry(n=>n+1)}>重試</button></p>}<p className="ds-footer">工作台快照時間 {w.as_of||'來源未提供'}。以下為本地操作稽核，Lark 原始修改時間未提供。</p>
  {!cur&&!data&&<section className="ds-section" aria-hidden="true"><div className="ds-group glass--flat audit-skeleton"><div className="skeleton skeleton-row audit-day-placeholder"/>{Array.from({length:3},(_,i)=><div className="audit-entry" key={i}><div className="ds-row"><span className="ds-row-main"><span className="skeleton skeleton-row"/><small className="skeleton skeleton-row"/></span><span className="skeleton skeleton-row audit-time-placeholder"/></div></div>)}</div></section>}
  {[...days].map(([day,items])=><section className="ds-section" key={day}>{day&&<h2>{day}</h2>}<div className="ds-group glass--flat">{items.map((row:any,index)=><article className="audit-entry" key={row.id||index}>
   <div className="ds-row"><span className="ds-row-main"><strong>{row.message||row.action||'來源未提供'}</strong><small>{row.actor_name||w.users.find(u=>u.id===row.actor_id)?.name||(row.actor_id==='system'?'系統':'來源未提供')}</small></span><time className="ds-row-value" dateTime={row.created_at||row.at}>{row.created_at||row.at||'來源未提供'}</time></div>
   {row.reason&&<p>{row.reason}</p>}{row.outcome&&<p>結果：{row.outcome}</p>}
   <details><summary>範圍與來源</summary><p>節點 {row.node_id||'來源未提供'} · 任務 {row.task_id||'來源未提供'}</p><p>來源 {row.source_kind||'本地操作稽核'}</p></details>{row.changes&&<details><summary>查看變更內容</summary><pre>{JSON.stringify(row.changes,null,2)}</pre></details>}
  </article>)}</div></section>)}
  {!error&&settled&&!pageOutOfRange&&!rows.length&&<p className="empty">尚無可見操作紀錄。</p>}
  <div className="daily-pagination"><span>{countLabel}</span><button className="ds-button" type="button" disabled={!settled||!currentPage} onClick={()=>setPage(currentPage-1)}>上一頁</button><button className="ds-button" type="button" disabled={!settled||!hasMore} onClick={()=>setPage(currentPage+1)}>下一頁</button></div>
 </section>;
}
