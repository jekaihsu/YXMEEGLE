import {useEffect,useMemo,useRef,useState} from 'react';
import {api,ApiError,getSessionEpoch} from './api';
import {dailyReviewLabel} from './dailyReview';
import type {DailyReport,Project,Route,Workspace} from './types';
import {Button,Skeleton} from './design';
import './DailyRecords.css';

type DailyRow=Partial<DailyReport>&{project_id?:string;project_code?:string;work_order_number?:string;work_order?:string;unmatched?:boolean;project?:{id:string;code:string}|null};
type DailyPage={key:string;epoch:number;items:DailyRow[];total:number;summary:Record<string,number>;coverage?:{scope:'workspace'|'visible_cases';project_only:boolean;unmatched_available:boolean};last_sync?:string};
let dailyEpoch=getSessionEpoch();
const dailyPages=new Map<string,DailyPage>();
export function dailyRecordOrder(a:{date?:string;id?:string},b:{date?:string;id?:string}){return Number(!a.date)-Number(!b.date)||String(b.date||'').localeCompare(String(a.date||''))||String(a.id||'').localeCompare(String(b.id||''),'zh-TW',{numeric:true})}
export function DailyRecords({w,p,go}:{w:Workspace;p:Project;go:(r:Route)=>void}){
 const[scope,setScope]=useState('project');const[query,setQuery]=useState('');const[day,setDay]=useState('');const[pg,setPg]=useState({pid:p.id,n:0});if(pg.pid!==p.id)setPg({pid:p.id,n:0});const page=pg.pid===p.id?pg.n:0;const setPage=(n:number)=>setPg({pid:p.id,n});
 const epoch=getSessionEpoch();if(dailyEpoch!==epoch){dailyPages.clear();dailyEpoch=epoch}
 const[remote,setRemote]=useState<DailyPage|null>(null);const[error,setError]=useState('');const[loading,setLoading]=useState(false);const[fallback,setFallback]=useState(false);
 const requestKey=useMemo(()=>{const params=new URLSearchParams({offset:String(page*30),limit:'30',status:scope==='unmatched'?'unmatched':'all'});if(scope==='project')params.set('project_id',p.id);if(query)params.set('q',query);if(day){params.set('date_from',day);params.set('date_to',day)}return params.toString()},[scope,query,day,page,p.id]);
 const seq=useRef(0);
 useEffect(()=>{const controller=new AbortController();const gen=++seq.current;const live=()=>gen===seq.current&&!controller.signal.aborted&&epoch===getSessionEpoch();setLoading(true);setFallback(false);setError('');
  void api<Omit<DailyPage,'key'|'epoch'>>('/api/daily-reports?'+requestKey,{signal:controller.signal},live).then(result=>{if(!live())return;if(!Array.isArray(result.items)||typeof result.total!=='number')throw new Error('日報回應格式不完整');const loaded={...result,key:requestKey,epoch};dailyPages.set(requestKey,loaded);if(dailyPages.size>50)dailyPages.delete(dailyPages.keys().next().value!);setRemote(loaded);setFallback(false);setError('')}).catch(e=>{if(!live())return;if(e instanceof ApiError&&e.status===404){dailyPages.delete(requestKey);setFallback(true);setRemote(null);setError('')}else {if(e instanceof ApiError&&[401,403].includes(e.status)){dailyPages.delete(requestKey);setRemote(null)}setError(e.message)}}).finally(()=>{if(live())setLoading(false)});return()=>{seq.current++;controller.abort()};
 },[requestKey,w.version,epoch]);
 const current=fallback?null:remote&&remote.key===requestKey&&remote.epoch===epoch?remote:dailyPages.get(requestKey)||null;
 const remotePageCount=current?Math.max(1,Math.ceil(current.total/30)):1;
 const pageOutOfRange=!!current&&page>=remotePageCount;
 // Only the pre-/api/daily-reports fallback lists from the workspace; in shell mode the other cards are summaries without daily_reports.
 const records=useMemo(()=>{
  if(!fallback)return [];
  const matched=w.projects.flatMap(project=>(project.daily_reports||[]).map(row=>({...row,project,unmatched:false})));
  const unmatched=(w.daily_unmatched||[]).map((row:any)=>({...row,project:null,unmatched:true}));
  return [...matched,...unmatched];
 },[w,fallback]);
 const filtered=records.filter(r=>(scope==='all'||scope==='unmatched'&&r.unmatched||scope==='project'&&r.project?.id===p.id)&&(!day||r.date?.slice(0,10)===day)&&`${r.person||''} ${r.department||''} ${r.description||''} ${r.project?.code||r.source_case_code||r.case_code||''}`.toLowerCase().includes(query.toLowerCase())).sort(dailyRecordOrder);
 const total=current?.total??(fallback?filtered.length:0);const settled=!loading&&(!!remote&&remote.key===requestKey&&remote.epoch===epoch||fallback);const currentPage=settled?Math.min(page,Math.max(1,Math.ceil(total/30))-1):page;const pageCount=Math.max(1,Math.ceil(total/30),currentPage+1);const visible:any[]=current&&!pageOutOfRange?current.items.map(r=>({...r,unmatched:!r.project_id,project:r.project_id?{id:r.project_id,code:r.project_code}:null})):fallback?filtered.slice(currentPage*30,(currentPage+1)*30):[];
 const countAvailable=!loading&&!error&&!pageOutOfRange&&(fallback||!!current&&(current.coverage?.scope==='workspace'||current.coverage?.scope==='visible_cases'));
 const knownCoverage=current?.coverage;
 const unmatchedAvailable=knownCoverage?.scope==='workspace'||(!knownCoverage&&(w.environment==='demo'||w.environment==='test'))||(fallback&&(w.daily_unmatched||[]).length>0);
 const unmatchedCount=unmatchedAvailable?(fallback?(w.daily_unmatched||[]).length:Number(current?.summary?.unmatched||0)):0;
 const visibleCasesOnly=knownCoverage?.scope==='visible_cases'||(!knownCoverage&&w.environment==='production');
 const emptyLabel=scope==='project'?'本案範圍尚無可見的已配對日報；不代表確定未作業。':scope==='unmatched'?'此篩選條件下尚無可見的待配對日報。':'此篩選條件下尚無可見日報；不代表確定未作業。';
 useEffect(()=>{if(settled&&page!==currentPage)setPage(currentPage)},[settled,page,currentPage,p.id]);
 useEffect(()=>{if(current?.coverage?.unmatched_available===false&&scope==='unmatched'){setScope('project');setPage(0)}},[current,scope,p.id]);
 const snapshot=scope==='project'&&!error&&!current&&!fallback&&!query&&!day&&page===0?(p.daily_reports||[]).slice().sort(dailyRecordOrder):[];
 const shown=visible.length?visible:snapshot;
 return <section className="daily-records"><header className="dr-head"><h2>日報紀錄</h2><p>原表唯讀。日報檢核在 Lark 處理，日報存在不代表成果交付完成。</p></header><div className="daily-filters"><label>查看範圍<select value={scope} onChange={e=>{setScope(e.target.value);setPage(0)}}><option value="project">本案已配對</option><option value="all">{visibleCasesOnly?'全部可見案件日報':'全部可見日報'}</option>{unmatchedAvailable&&<option value="unmatched">待配對</option>}</select></label><label>搜尋人員、內容或案號<input value={query} onChange={e=>{setQuery(e.target.value);setPage(0)}}/></label><label>作業日期<input type="date" value={day} onChange={e=>{setDay(e.target.value);setPage(0)}}/></label></div>{visibleCasesOnly&&<p className="dr-note ops-notice">此查詢只涵蓋可見案件日報；未配對的來源日報不在此範圍。這裡的筆數不代表來源日報總數。</p>}{countAvailable&&unmatchedAvailable&&unmatchedCount>0&&<div className="dr-note ops-notice">此查詢範圍有 {unmatchedCount} 筆待配對日報，尚未歸屬本案，也不計入本案成果。<Button variant="plain" onClick={()=>{setScope('unmatched');setPage(0)}}>查看待配對</Button><Button variant="plain" onClick={()=>go({view:'admin',tab:'daily'})}>前往配對核對</Button></div>}{error&&<p className="dr-note ops-notice" data-tone="critical" role="alert">{error}</p>}{fallback&&<p className="dr-note ops-notice">目前服務尚未提供全量日報查詢，下方僅列工作區已載入紀錄。</p>}<p className="ds-footer">來源同步時間 {current?.last_sync||w.source_status?.last_sync||'來源未提供'}{error&&current&&' · 上次資料，更新失敗'}{loading&&shown.length>0&&' · 背景更新中'}。</p><p role="status">{countAvailable?`共 ${total} 筆符合條件 · 第 ${currentPage+1}／${pageCount} 頁`:loading||pageOutOfRange?"正在讀取日報… · 範圍尚未確認，筆數暫不可用。":"日報查詢範圍尚未確認，筆數暫不可用。"}</p>{loading&&!shown.length&&<Skeleton lines={3} height="5rem"/>}<div className="daily-cards ds-group glass--flat">{shown.map((r,i)=><article key={`${r.project?.id||'unmatched'}:${r.id||i}`}><header><strong>{r.date||'來源未提供'} · {r.department||'來源未提供'}</strong><span>{r.person||'來源未提供'}</span></header><p>{r.description||'來源未提供'}</p><div>工作單號 {r.work_order_number||r.work_order||'來源未提供'} · 公布點數 {r.points==null?'來源未提供':`${Number(r.points).toLocaleString('zh-TW',{maximumFractionDigits:20})} 點`}</div><details><summary>原始值與來源關係</summary><dl><dt>原始營業額點數</dt><dd>來源未提供</dd><dt>修改後營業額</dt><dd>來源未提供</dd><dt>最終營業額點數</dt><dd>來源未提供</dd><dt>成本單與工項</dt><dd>來源未提供</dd></dl><div>公布點數沿用 API 的來源取值，不冒充原始、修正或最終欄位。日期沿用工作單及成本單的業務日期，不採填報時間。</div></details><footer><span>{r.unmatched?'待配對':r.project?.code}{!r.unmatched&&(r.match_basis==='provisional_case_code'||r.mapping_status==='provisional_case_code')&&' · 暫填工編配對，原表關聯待核對'}{r.source_case_code&&r.unmatched&&` · 來源案號 ${r.source_case_code}`}</span><span>{dailyReviewLabel(r.review)}</span>{/^https?:\/\//i.test(r.source_url||'')&&<a href={r.source_url} target="_blank" rel="noreferrer">開啟 Lark 原日報</a>}</footer></article>)}</div>{countAvailable&&!total&&<p className="dr-empty">{emptyLabel}</p>}<div className="daily-pagination"><Button disabled={!countAvailable||currentPage===0} onClick={()=>setPage(currentPage-1)}>上一頁</Button><Button disabled={!countAvailable||currentPage+1>=pageCount} onClick={()=>setPage(currentPage+1)}>下一頁</Button></div></section>;
}
