import {useEffect,useState} from 'react';
import {ApiError,fetchPilotShadow,getSessionEpoch} from './api';
import {statusNames,time} from './DataFreshness';
import './lark-pilot.css';

const sources={lark_live:'Lark 即時',lark_live_cached:'快取',mock:'示範',local:'本機',unmapped:'未對映'};
const notices={fresh:'已讀取',stale:'資料待更新',partial:'部分資料，無法讀取的欄位仍待核對',blocked:'無法讀取，權限不足',error:'讀取失敗',unconfigured:'尚未設定'};
const fieldNames={present:'有值',null:'明確空值',omitted:'未回傳',forbidden:'無法讀取',partial:'部分資料',unmapped:'未對映'};
const groups={cases:'工程確認單',work_orders:'外業工作單',people:'人員名單'};
type Source=keyof typeof sources;
type State=keyof typeof notices;
type FieldState=keyof typeof fieldNames;
type Cell={state:'present';value:unknown}|{state:Exclude<FieldState,'present'>};
type Row={record_id:string;fields:Record<string,Cell>};
export type PilotData={status:State;source:Source;fetched_at:string|null;ttl_seconds:number;records:{cases:Row[];work_orders:Row[];people:Row[]};table_states:{cases:string;work_orders:string;people:string}};
const object=(value:unknown):value is Record<string,unknown>=>typeof value==='object'&&value!==null&&!Array.isArray(value);
const has=<T extends object>(map:T,key:unknown):key is keyof T=>typeof key==='string'&&Object.hasOwn(map,key);
export function parsePilot(value:unknown):PilotData{
 if(!object(value)||!has(notices,value.status)||!has(sources,value.source)||!object(value.records)||!object(value.table_states)||typeof value.ttl_seconds!=='number'||!Number.isFinite(value.ttl_seconds)||value.ttl_seconds<=0||!(value.fetched_at===null||typeof value.fetched_at==='string'&&Number.isFinite(Date.parse(value.fetched_at))))throw Error('讀取回應格式不正確');
 const rows=(name:keyof typeof groups):Row[]=>{
  const list=object(value.records)?value.records[name]:null;if(!Array.isArray(list))throw Error('讀取回應格式不正確');
  return list.map((row:unknown)=>{
   if(!object(row)||typeof row.record_id!=='string'||!object(row.fields))throw Error('讀取回應格式不正確');
   const fields:Record<string,Cell>={};for(const [id,cell] of Object.entries(row.fields)){
    if(!object(cell)||!has(fieldNames,cell.state))throw Error('讀取回應格式不正確');
    fields[id]=cell.state==='present'?{state:'present',value:cell.value}:{state:cell.state};
   }return {record_id:row.record_id,fields};
  });
 };
 const table=(name:keyof typeof groups)=>{const s=object(value.table_states)?value.table_states[name]:null;if(typeof s!=='string')throw Error('讀取回應格式不正確');return s};
 return {status:value.status,source:value.source,fetched_at:value.fetched_at,ttl_seconds:value.ttl_seconds,records:{cases:rows('cases'),work_orders:rows('work_orders'),people:rows('people')},table_states:{cases:table('cases'),work_orders:table('work_orders'),people:table('people')}};
}
const show=(value:unknown)=>typeof value==='string'?value===''?'空字串':value:JSON.stringify(value);
export function PilotView({data,now=Date.now()}:{data:PilotData;now?:number}){
 const age=data.fetched_at?Math.max(0,(now-Date.parse(data.fetched_at))/1000):null;
 const state=data.source==='lark_live_cached'?'stale':data.status==='fresh'&&age!==null&&age>data.ttl_seconds?'stale':data.status;
 const chip=state==='partial'?'error':state;
 return <section className="lark-pilot" aria-label="唯讀 Lark 試讀"><h2>唯讀 Lark 試讀</h2>
  <p role="status" aria-live="polite"><span>{sources[data.source]}</span> · <span className={`data-freshness data-freshness-${chip}`}>{statusNames[chip]}</span> · {time(data.fetched_at)} · {age===null?'時間未知':`${Math.floor(age)} 秒前`}</p>
  <p>{notices[state]}</p>
  {(Object.keys(groups) as (keyof typeof groups)[]).map(name=><div key={name}><h3>{groups[name]}</h3>
   {data.table_states[name]!=='present'?<p>{data.table_states[name]==='forbidden'?'無法讀取':'未對映或尚未讀取'}</p>:data.records[name].length===0?<p>{state==='fresh'||state==='stale'?'本次取樣無紀錄':'本次讀取未完成'}</p>:
   <div className="lark-pilot-scroll" tabIndex={0} aria-label={`${groups[name]}試讀欄位，可左右捲動`}><table><thead><tr><th>紀錄識別</th><th>欄位識別</th><th>狀態</th><th>原始值</th></tr></thead><tbody>{data.records[name].flatMap(row=>Object.entries(row.fields).map(([id,cell])=><tr key={`${row.record_id}:${id}`}><td>{row.record_id}</td><td>{id}</td><td>{fieldNames[cell.state]}</td><td>{cell.state==='present'?show(cell.value):'—'}</td></tr>))}</tbody></table></div>}</div>)}
 </section>;
}
export function LarkPilotPanel({demo=false}:{demo?:boolean}){
 const [data,setData]=useState<PilotData>();const [message,setMessage]=useState('讀取中…');const [now,setNow]=useState(Date.now);
 useEffect(()=>{
  setData(undefined);setMessage(demo?'示範資料':'讀取中…');if(demo)return;
  const controller=new AbortController();const epoch=getSessionEpoch();let active=true;
  void fetchPilotShadow(controller.signal).then(parsePilot).then(next=>{if(active&&epoch===getSessionEpoch()){setData(next);setNow(Date.now());setMessage('')}}).catch((error:unknown)=>{if(active&&epoch===getSessionEpoch())setMessage(error instanceof ApiError&&error.status===404?'尚未設定':error instanceof ApiError&&error.status===403?'無法讀取，權限不足':'讀取失敗')});
  return()=>{active=false;controller.abort()};
 },[demo]);
 useEffect(()=>{if(!data?.fetched_at||data.status!=='fresh')return;const delay=Math.max(0,Date.parse(data.fetched_at)+data.ttl_seconds*1000-Date.now()+1);const timer=setTimeout(()=>setNow(Date.now()),Math.min(delay,2147483647));return()=>clearTimeout(timer)},[data]);
 return demo||!data?<section className="lark-pilot" aria-label="唯讀 Lark 試讀"><h2>唯讀 Lark 試讀</h2><p role="status" aria-live="polite">{message}</p></section>:<PilotView data={data} now={now}/>;
}
