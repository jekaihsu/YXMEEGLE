import {useEffect,useRef,useState} from 'react';
import {getSessionEpoch,liveRefresh,liveStatus} from './api';
import {ageFreshness} from './freshness';
import type {Freshness,LiveDataset} from './types';

export interface DataFreshnessProps {
  freshness?:Freshness;
  demo?:boolean;
  mutationActive?:boolean;
  dirtyDraft?:boolean;
  refresh:()=>void;
}
const names:Record<LiveDataset,string>={sources:'來源',roster:'名冊',attendance:'班表'};
const priority=['blocked','error','refreshing','never','stale','fresh','unconfigured'] as const;
const time=(value:string|null)=>value?new Date(value).toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei',hour12:false}):'—';

export function DataFreshness({freshness,demo=false,mutationActive=false,dirtyDraft=false,refresh}:DataFreshnessProps){
  const [current,setCurrent]=useState(freshness);
  const receivedAt=useRef(Date.now());
  const [now,setNow]=useState(Date.now);
  const [busy,setBusy]=useState(false);
  const [requestError,setRequestError]=useState('');
  const changed=useRef<Partial<Record<LiveDataset,number>>|null>(null);
  const mounted=useRef(true);
  const epoch=useRef(getSessionEpoch());
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
  useEffect(()=>{receivedAt.current=Date.now();setNow(Date.now());setCurrent(freshness);setRequestError('')},[freshness]);
  useEffect(()=>{if(demo||!current?.enabled)return;let timer:ReturnType<typeof setTimeout>;const tick=()=>{setNow(Date.now());timer=setTimeout(tick,30000)};timer=setTimeout(tick,30000);return()=>clearTimeout(timer)},[demo,current?.enabled]);
  const aged=current?ageFreshness(current,receivedAt.current,now):undefined;
  const active=!!current?.enabled&&!demo;
  const entries=aged?Object.entries(aged.datasets) as [LiveDataset,Freshness['datasets'][LiveDataset]][]:[];
  const polling=active&&entries.some(([,d])=>d.status==='refreshing');

  useEffect(()=>{
    if(!active||!polling||epoch.current!==getSessionEpoch())return;
    let stopped=false;
    let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      if(epoch.current!==getSessionEpoch())return;
      try{
        const result=await liveStatus();
        if(!stopped&&epoch.current===getSessionEpoch()){receivedAt.current=Date.now();setNow(Date.now());setCurrent(result.freshness);setRequestError('')}
      }catch{
        if(!stopped&&epoch.current===getSessionEpoch())setRequestError('資料狀態暫時無法讀取');
      }
      if(!stopped&&epoch.current===getSessionEpoch())timer=setTimeout(poll,15000);
    };
    timer=setTimeout(poll,15000);
    return()=>{stopped=true;clearTimeout(timer)};
  },[active,polling,freshness]);

  useEffect(()=>{
    if(!current||!active)return;
    const latest=Object.fromEntries(Object.entries(current.datasets).map(([key,d])=>[key,d.changed_at?Date.parse(d.changed_at):0])) as Record<LiveDataset,number>;
    if(changed.current===null){changed.current=latest;return}
    if(mutationActive||dirtyDraft||epoch.current!==getSessionEpoch())return;
    const advanced=(Object.keys(latest) as LiveDataset[]).some(key=>latest[key]>(changed.current?.[key]||0));
    if(advanced){
      for(const key of Object.keys(latest) as LiveDataset[])changed.current[key]=Math.max(changed.current[key]||0,latest[key]||0);
      refresh();
    }
  },[current,active,mutationActive,dirtyDraft,refresh]);

  const reread=async()=>{
    if(!active||busy||epoch.current!==getSessionEpoch())return;
    setBusy(true);setRequestError('');
    try{
      const result=await liveRefresh(['sources','attendance']);
      if(mounted.current&&epoch.current===getSessionEpoch()){receivedAt.current=Date.now();setNow(Date.now());setCurrent(result.freshness)};
    }catch{
      if(mounted.current&&epoch.current===getSessionEpoch())setRequestError('Lark 暫時無法讀取，請稍後重試');
    }finally{if(mounted.current)setBusy(false)}
  };
  const state=active?(priority.find(s=>entries.some(([,d])=>d.status===s))||'unconfigured'):'unconfigured';
  const source=aged?.datasets.sources;
  const age=source?.age_seconds;
  const ageText=age==null?'未知時間':`${Math.max(0,Math.floor(age/60))} 分鐘前`;
  let label=`Lark 資料 ${time(source?.as_of||null)}（${age==null?'—':Math.max(0,Math.floor(age))} 秒前）`;
  if(state==='unconfigured')label=demo?'示範資料':'尚未設定';
  if(state==='stale')label+=' · 資料待更新';
  if(state==='refreshing')label='更新中…';
  if(state==='never')label='正在讀取 Lark 來源…';
  if(state==='error')label=`Lark 暫時無法讀取，顯示 ${ageText}資料`;
  if(state==='blocked')label='Lark 權限不足（1254302），請聯絡管理員';
  const color=state==='error'||state==='blocked'?'#b91c1c':state==='stale'?'#92400e':'inherit';
  const details=entries.map(([key,d])=>`${names[key]}：${time(d.as_of)} · ${d.age_seconds??'—'} 秒前 · TTL ${d.ttl_seconds} 秒`).join('\n');
  return <div className={`data-freshness data-freshness-${state}`} data-state={state}>
    <span role="status" aria-live="polite" title={details} style={{color}}>
      {state==='refreshing'?<span className="spinner" aria-hidden="true">◌ </span>:null}<span aria-hidden="true">{label}</span><span className="sr-only">{state==='fresh'?'Lark 資料已讀取':state==='stale'?'Lark 資料待更新':label}</span>
      {requestError?<span> · {requestError}</span>:null}
    </span>
    {active?<button type="button" className="button" onClick={reread} disabled={busy} aria-label="立即重新讀取 Lark">{busy?'讀取中…':state==='error'?'重試':'重新讀取'}</button>:null}
  </div>;
}
