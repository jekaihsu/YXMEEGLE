import {useEffect,useMemo,useRef,useState} from 'react';
import {getSessionEpoch,liveRefresh} from './api';
import {ageFreshness,datasetNames,retainedAge,failedFreshness} from './freshness';
import type {Freshness,LiveDataset} from './types';

export interface DataFreshnessProps {
  freshness?:Freshness;
  onFreshness?:(freshness:Freshness,snapshot?:Freshness)=>void;
  demo?:boolean;
  mutationActive?:boolean;
  dirtyDraft?:boolean;
  refresh:()=>boolean|void|Promise<boolean|void>;
}
const names=datasetNames;
const statusNames={fresh:'已讀取',stale:'資料待更新',refreshing:'更新中',never:'尚未讀取',error:'讀取失敗',blocked:'權限不足',unconfigured:'尚未設定'};
const priority=['blocked','error','refreshing','never','stale','fresh','unconfigured'] as const;
const time=(value:string|null)=>value?new Date(value).toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei',hour12:false}):'—';

export function DataFreshness({freshness,demo=false,mutationActive=false,dirtyDraft=false,refresh,onFreshness}:DataFreshnessProps){
  const [current,setCurrent]=useState(freshness);
  const receivedAt=useRef(Date.now());
  const latestSnapshot=useRef(freshness);
  const manualController=useRef<AbortController>();
  const [now,setNow]=useState(Date.now);
  const [busy,setBusy]=useState(false);
  const [requestError,setRequestError]=useState('');
  const [errorDatasets,setErrorDatasets]=useState<LiveDataset[]>(['sources','roster','attendance']);
  const mounted=useRef(true);
  const epoch=useRef(getSessionEpoch());
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;manualController.current?.abort()}},[]);
  const accept=(next:Freshness|undefined)=>{
    const previous=latestSnapshot.current;
    if(previous&&next&&Date.parse(next.server_time)<Date.parse(previous.server_time))return;
    if(previous?.server_time!==next?.server_time)receivedAt.current=Date.now();
    latestSnapshot.current=next;setNow(Date.now());setCurrent(next);setRequestError('');
  };
  useEffect(()=>{accept(freshness)},[freshness]);
  const aged=useMemo(()=>{if(!current)return;const value=ageFreshness(current,receivedAt.current,now);return requestError?failedFreshness(value,errorDatasets):value},[current,now,requestError,errorDatasets]);
  useEffect(()=>{if(aged&&epoch.current===getSessionEpoch())onFreshness?.(aged,current)},[aged,onFreshness]);
  const active=!!current?.enabled&&!demo;
  const entries=aged?Object.entries(aged.datasets) as [LiveDataset,Freshness['datasets'][LiveDataset]][]:[];
  const reread=async()=>{
    if(!active||busy||mutationActive||dirtyDraft||epoch.current!==getSessionEpoch())return;
    setNow(Date.now());
    const failed=entries.filter(([,d])=>d.status==='error'||d.status==='blocked').map(([key])=>key);
    const datasets:LiveDataset[]=failed.length?failed:['sources','attendance'];
    setBusy(true);setRequestError('');manualController.current?.abort();manualController.current=new AbortController();
    try{
      const result=await liveRefresh(datasets,false,manualController.current.signal);
      if(mounted.current&&epoch.current===getSessionEpoch()){accept(result.freshness);await refresh()}
    }catch{
      if(mounted.current&&epoch.current===getSessionEpoch()){setErrorDatasets(datasets);setRequestError('Lark 暫時無法讀取，請稍後重試')}
    }finally{if(mounted.current)setBusy(false)}
  };
  const state=active?(priority.find(s=>entries.some(([,d])=>d.status===s))||'unconfigured'):'unconfigured';
  const deciding=entries.filter(([,d])=>d.status===state).sort((a,b)=>(b[1].age_seconds??-1)-(a[1].age_seconds??-1));
  const source=deciding[0]?.[1];
  const age=source?.age_seconds;
  const ageText=retainedAge(age??null);
  let label=`Lark 資料 ${time(source?.as_of||null)}`;
  if(state==='unconfigured')label=demo?'示範資料':'尚未設定';
  if(state==='stale')label+=' · 資料待更新';
  if(state==='refreshing')label='更新中…';
  if(state==='never')label=`正在讀取 Lark ${names[deciding[0]?.[0]||'sources']}…`;
  if(state==='error')label=`${deciding.map(([key])=>names[key]).join('、')}：Lark 暫時無法讀取，${ageText}`;
  if(state==='blocked')label=`${deciding.map(([key])=>names[key]).join('、')}：Lark 權限不足（1254302），請聯絡管理員`;
  const color=state==='error'||state==='blocked'?'#b91c1c':state==='stale'?'#92400e':'inherit';
  const details=entries.map(([key,d])=>`${names[key]}：${time(d.as_of)} · ${d.age_seconds??'—'} 秒前 · TTL ${d.ttl_seconds} 秒`).join('\n');
  return <div className={`data-freshness data-freshness-${state}`} data-state={state}>
    <span role="status" aria-live="polite" title={details} style={{color}}>
      {state==='refreshing'?<span className="spin" aria-hidden="true">◌ </span>:null}{state==='fresh'||state==='stale'||state==='error'?<><span aria-hidden="true">{label}</span><span className="sr-only">{state==='fresh'?'Lark 資料已讀取':state==='stale'?'Lark 資料待更新':`${deciding.map(([key])=>names[key]).join('、')}：Lark 暫時無法讀取，顯示先前資料`}</span></>:label}
      {requestError?<span> · {requestError}</span>:null}
    </span>
    {!demo&&active?<details className="freshness-details"><summary>資料讀取詳情</summary><ul>{entries.map(([key,d])=><li key={key}>{names[key]}：{time(d.as_of)} · {d.age_seconds==null?'時間未知':`${Math.floor(d.age_seconds)} 秒前`} · 有效時間 {d.ttl_seconds} 秒 · {statusNames[d.status]}</li>)}</ul></details>:null}
    {active?<button type="button" className="button" onClick={reread} disabled={busy} aria-busy={busy}>{busy?'讀取中…':state==='error'?'重試':'重新整理'}</button>:null}
  </div>;
}
