import {useEffect,useState} from 'react';
import {api,ApiError} from './api';
import type {Project,Workspace} from './types';

export function AuditTrail({w,p}:{w:Workspace;p:Project}){
 // Every piece of fetched state is tagged with the project (and offset) it was requested for, so a render
 // for another project can never display it, even before an effect has had a chance to clear it.
 const[nav,setNav]=useState({pid:p.id,page:0});const page=nav.pid===p.id?nav.page:0;const setPage=(n:number)=>setNav({pid:p.id,page:n});
 if(nav.pid!==p.id)setNav({pid:p.id,page:0});
 const requestKey=`${p.id}:${w.version}:${page}`;
 const[loaded,setLoaded]=useState<{key:string;data:{items:any[];total:number;has_more?:boolean}|null;legacy:boolean;error:string}|null>(null);
 useEffect(()=>{const controller=new AbortController();const isCurrent=()=>!controller.signal.aborted;setLoaded(null);void api<any>(`/api/audit?project_id=${encodeURIComponent(p.id)}&offset=${page*30}&limit=30`,{signal:controller.signal}).then(result=>{if(!isCurrent())return;if(!Array.isArray(result.items))throw new Error('操作紀錄格式不完整');setLoaded({key:requestKey,data:result,legacy:false,error:''})}).catch(e=>{if(!isCurrent())return;if(e instanceof ApiError&&e.status===404)setLoaded({key:requestKey,data:null,legacy:true,error:''});else setLoaded({key:requestKey,data:null,legacy:false,error:e.message})});return()=>controller.abort()},[requestKey,p.id,page]);
 const cur=loaded&&loaded.key===requestKey?loaded:null;const data=cur?.data||null;const legacy=!!cur?.legacy;const error=cur?.error||'';
 const old=w.events.filter(e=>e.project_id===p.id);const total=legacy?old.length:data?.total||0;
 const settled=!!data||legacy;const currentPage=settled?Math.min(page,Math.max(1,Math.ceil(total/30))-1):page;const pageOutOfRange=settled&&page!==currentPage;
 const rows=legacy?old.slice(currentPage*30,(currentPage+1)*30):!pageOutOfRange?data?.items||[]:[];
  // Older APIs and the local fallback provide exact totals; bounded API pages mark lower bounds.
 const hasMore=legacy?(currentPage+1)*30<total:data?.has_more??((currentPage+1)*30<total);
 const countLabel=data?.has_more?`至少 ${total} 筆`:`共 ${total} 筆`;
 useEffect(()=>{if(pageOutOfRange)setPage(currentPage)},[pageOutOfRange,currentPage,p.id]);
 const days=new Map<string,any[]>();
 for(const row of rows){const day=String(row.created_at||row.at||'').slice(0,10);days.set(day,[...(days.get(day)||[]),row])}
 return <section className="audit-trail audit-screen"><h2>操作紀錄</h2><p>查看誰在何時處理了哪些工作，以及確認、退回和來源更新的記錄。</p>
  {legacy&&<p className="ops-notice">目前服務僅提供舊版活動紀錄；完整變更稽核尚未接通。</p>}
  {error&&<p className="form-error" role="alert">{error}</p>}
  {!cur&&<section className="ds-section" aria-hidden="true"><div className="ds-group glass--flat audit-skeleton"><div className="skeleton skeleton-row audit-day-placeholder"/>{Array.from({length:3},(_,i)=><div className="audit-entry" key={i}><div className="ds-row"><span className="ds-row-main"><span className="skeleton skeleton-row"/><small className="skeleton skeleton-row"/></span><span className="skeleton skeleton-row audit-time-placeholder"/></div></div>)}</div></section>}
  {[...days].map(([day,items])=><section className="ds-section" key={day}>{day&&<h2>{day}</h2>}<div className="ds-group glass--flat">{items.map((row:any,index)=><article className="audit-entry" key={row.id||index}>
   <div className="ds-row"><span className="ds-row-main"><strong>{row.message||row.action}</strong><small>{row.actor_name||w.users.find(u=>u.id===row.actor_id)?.name||(row.actor_id==='system'?'系統':'原操作人員')}</small></span><time className="ds-row-value" dateTime={row.created_at||row.at}>{row.created_at||row.at}</time></div>
   {row.reason&&<p>{row.reason}</p>}{row.outcome&&<p>結果：{row.outcome}</p>}
   {row.changes&&<details><summary>查看變更內容</summary><pre>{JSON.stringify(row.changes,null,2)}</pre></details>}
  </article>)}</div></section>)}
  {!error&&settled&&!pageOutOfRange&&!rows.length&&<p className="empty">尚無可見操作紀錄。</p>}
  <div className="daily-pagination"><span>{countLabel}</span><button className="ds-button" type="button" disabled={!currentPage} onClick={()=>setPage(currentPage-1)}>上一頁</button><button className="ds-button" type="button" disabled={!hasMore} onClick={()=>setPage(currentPage+1)}>下一頁</button></div>
 </section>;
}
