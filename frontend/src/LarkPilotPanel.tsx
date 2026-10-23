import {useEffect,useRef,useState} from 'react';
import {api,ApiError,fetchPilotShadow,getSessionEpoch,liveRefresh} from './api';
import {statusNames,time} from './DataFreshness';
import {ageFreshness} from './freshness';
import './lark-pilot.css';
import type {Context} from './Operations';

const sources={lark_live:'Lark 即時',lark_live_cached:'快取',mock:'示範',local:'本機',unmapped:'未對映'};
const notices={fresh:'已讀取',stale:'資料待更新',partial:'部分資料，無法讀取的欄位仍待核對',blocked:'無法讀取，權限不足',error:'讀取失敗',unconfigured:'尚未設定'};
const fieldNames={present:'有值',null:'明確空值',omitted:'未回傳',forbidden:'無法讀取',partial:'部分資料',unmapped:'未對映'};
const groups={cases:'工程確認單',work_orders:'外業工作單',people:'人員名單'};
type Source=keyof typeof sources;
type State=keyof typeof notices;
type FieldState=keyof typeof fieldNames;
type Cell={state:'present';value:unknown}|{state:Exclude<FieldState,'present'>};
type Count={requested:number;returned:number;omitted:number;has_more:boolean};
const tableNames={present:'已讀取取樣',not_read:'尚未讀取',unmapped:'未對映',forbidden:'無法讀取',partial:'部分資料'};
const noLinked:Record<keyof typeof groups,string>={cases:'不適用',work_orders:'案件目前沒有關聯的工單，未讀取',people:'工單目前沒有關聯的人員，未讀取'};
const reasonNames={no_linked_records:'',traversal_unavailable:'目前唯讀範圍無法依關聯讀取',access_denied:'應用尚無此資料表讀取權限（Lark 1254302）',read_failed:'此資料表讀取失敗',not_applicable:'不適用'};
type Row={record_id:string;fields:Record<string,Cell>};
export type PilotData={status:State;source:Source;fetched_at:string|null;ttl_seconds:number;records:{cases:Row[];work_orders:Row[];people:Row[]};table_states:{cases:string;work_orders:string;people:string};table_reasons:Partial<Record<keyof typeof groups,keyof typeof reasonNames>>;table_fetched_at:Record<keyof typeof groups,string|null>;counts:Record<keyof typeof groups,Count|null>;code?:string};
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
 const table=(name:keyof typeof groups)=>{const s=object(value.table_states)?value.table_states[name]:null;if(!has(tableNames,s))throw Error('讀取回應格式不正確');return s};
 const stamps={} as PilotData['table_fetched_at'];const counts={} as PilotData['counts'];
 for(const name of Object.keys(groups) as (keyof typeof groups)[]){
  const stamp=object(value.table_fetched_at)?value.table_fetched_at[name]:null;
  if(!(stamp===null||typeof stamp==='string'&&Number.isFinite(Date.parse(stamp))))throw Error('讀取回應格式不正確');
  stamps[name]=stamp;
  const count=object(value.counts)?value.counts[name]:null;
  if(count!==null&&(!object(count)||!['requested','returned','omitted'].every(k=>typeof count[k]==='number'&&Number.isInteger(count[k])&&(count[k] as number)>=0)||typeof count.has_more!=='boolean'))throw Error('讀取回應格式不正確');
  counts[name]=count as Count|null;
 }
 const reasons:PilotData['table_reasons']={};for(const name of Object.keys(groups) as (keyof typeof groups)[]){const r=object(value.table_reasons)?value.table_reasons[name]:undefined;if(has(reasonNames,r))reasons[name]=r}
 return {status:value.status,source:value.source,fetched_at:value.fetched_at,ttl_seconds:value.ttl_seconds,records:{cases:rows('cases'),work_orders:rows('work_orders'),people:rows('people')},table_states:{cases:table('cases'),work_orders:table('work_orders'),people:table('people')},table_reasons:reasons,table_fetched_at:stamps,counts,code:typeof value.code==='string'?value.code:undefined};
}
const show=(value:unknown)=>typeof value==='string'?value===''?'空字串':value:JSON.stringify(value);
export function PilotView({data,now=Date.now()}:{data:PilotData;now?:number}){
 const age=data.fetched_at?Math.max(0,(now-Date.parse(data.fetched_at))/1000):null;
 const names=Object.keys(groups) as (keyof typeof groups)[];
 const expired=age===null||age>data.ttl_seconds||names.some(name=>data.table_states[name]==='present'&&(!data.table_fetched_at[name]||(now-Date.parse(data.table_fetched_at[name]!))/1000>data.ttl_seconds));
 const incomplete=names.some(name=>data.table_states[name]!=='present'||!data.counts[name]||data.counts[name]!.has_more||data.counts[name]!.omitted>0);
 const state=data.source==='lark_live_cached'||['fresh','partial'].includes(data.status)&&expired?'stale':data.status==='fresh'&&incomplete?'partial':data.status;
 const chip=state==='partial'?'error':state;
 return <section className="lark-pilot" aria-label="唯讀 Lark 試讀"><h2>唯讀 Lark 試讀</h2>
  <p role="status" aria-live="polite"><span>{data.source==='lark_live'&&state!=='fresh'?'Lark 已讀取取樣':sources[data.source]}</span> · <span className={`data-freshness data-freshness-${chip}`}>{state==='partial'?'部分資料':statusNames[chip]}</span> · {time(data.fetched_at)} · {age===null?'時間未知':`${Math.floor(age)} 秒前`}</p>
  <p>{data.code&&errorMessages[data.code]||notices[state]}</p>
  {(Object.keys(groups) as (keyof typeof groups)[]).map(name=><div key={name}><h3>{groups[name]}</h3><p>{tableNames[data.table_states[name] as keyof typeof tableNames]} · {time(data.table_fetched_at[name])}</p>
   {!['blocked','error','unconfigured'].includes(data.status)&&data.table_states[name]==='present'&&data.counts[name]&&<p>本次取樣 {data.counts[name]!.returned} 筆{(data.counts[name]!.has_more||data.counts[name]!.omitted>0)&&` · 至少 ${Math.max(data.counts[name]!.omitted,data.counts[name]!.has_more?1:0)} 筆未納入取樣`}</p>}
   {data.table_states[name]!=='present'?<p>{data.table_reasons[name]&&(data.table_reasons[name]==='no_linked_records'?noLinked[name]:reasonNames[data.table_reasons[name]!])||tableNames[data.table_states[name] as keyof typeof tableNames]}</p>:data.records[name].length===0?<p>{state==='fresh'||state==='stale'?'本次取樣無紀錄':'本次讀取未完成'}</p>:
   <div className="lark-pilot-scroll" tabIndex={0} aria-label={`${groups[name]}試讀欄位，可左右捲動`}><table><thead><tr><th>紀錄識別</th><th>欄位識別</th><th>狀態</th><th>原始值</th></tr></thead><tbody>{data.records[name].flatMap(row=>Object.entries(row.fields).map(([id,cell])=><tr key={`${row.record_id}:${id}`}><td>{row.record_id}</td><td>{id}</td><td>{fieldNames[cell.state]}</td><td>{cell.state==='present'?show(cell.value):'—'}</td></tr>))}</tbody></table></div>}</div>)}
 </section>;
}
const errorMessages:Record<string,string>={pilot_disabled:'唯讀 Lark 試讀尚未啟用',pilot_not_company_workspace:'此工作區不是公司工作區',pilot_method_not_allowed:'唯讀 Lark 試讀不支援此請求方式',pilot_read_failed:'唯讀 Lark 試讀暫時無法完成',pilot_roster_missing:'尚無名冊核實紀錄',pilot_config_invalid:'系統設定異常',access_roster_expired:'公司名冊已逾 15 分鐘',access_not_admitted:'帳號尚未核實或已停用',source_authorization_denied:'你沒有讀取 Lark 來源的權限',lark_permission_denied:'Lark 拒絕此應用讀取',lark_read_failed:'Lark 資料暫時無法讀取',client_timeout:'讀取逾時，請重試。'};
const errorMessage=(error:unknown)=>error instanceof ApiError?(error.code==='pilot_roster_stale'?`名冊核實已逾 ${error.ceiling_seconds??60} 秒，請重新核對名冊`:errorMessages[error.code||'']||'讀取失敗（原因不明）'):'讀取失敗（原因不明）';
export function LarkPilotPanel({demo=false,c}:{demo?:boolean;c?:Context}){
 const [data,setData]=useState<PilotData>();const [message,setMessage]=useState('讀取中…');const [now,setNow]=useState(Date.now);
 const [reason,setReason]=useState<string>();const [retry,setRetry]=useState(0);const [busy,setBusy]=useState(false);
 const syncing=useRef(false);const recovery=useRef<AbortController>();
 useEffect(()=>()=>recovery.current?.abort(),[]);
 useEffect(()=>{
  setData(undefined);setReason(undefined);setMessage(demo?'示範資料':'讀取中…');if(demo)return;
  const controller=new AbortController();const epoch=getSessionEpoch();let active=true;
  void fetchPilotShadow(controller.signal).then(parsePilot).then(next=>{if(active&&epoch===getSessionEpoch()){setData(next);setNow(Date.now());setMessage('')}}).catch((error:unknown)=>{if(active&&epoch===getSessionEpoch()){setMessage(errorMessage(error));setReason(error instanceof ApiError?error.code:undefined)}});
  return()=>{active=false;controller.abort()};
 },[demo,retry]);
 const retryRoster=async()=>{
  if(!c||syncing.current)return;
  syncing.current=true;setBusy(true);const epoch=getSessionEpoch();const controller=new AbortController();recovery.current=controller;
  const current=()=>!controller.signal.aborted&&epoch===getSessionEpoch();
  try{
   const result=c.w.freshness?.enabled?await liveRefresh(['roster'],true,controller.signal):await api<{freshness?:import('./types').Freshness}>('/api/people/sync',{method:'POST',signal:controller.signal,timeoutMs:120000});
   if(!current())return;
   if(result.freshness)c.onFreshness?.(result.freshness);
   if(c.w.freshness?.enabled&&result.freshness&&ageFreshness(result.freshness,Date.now(),Date.now()).datasets.roster.status!=='fresh'){setMessage('名冊讀取尚未完成，請稍後重試');return}
   setRetry(value=>value+1);
  }catch(error){if(current())setMessage(errorMessage(error))}
  finally{syncing.current=false;if(current())setBusy(false)}
 };
 useEffect(()=>{if(!data?.fetched_at||!['fresh','partial'].includes(data.status))return;const oldest=Math.min(Date.parse(data.fetched_at),...Object.values(data.table_fetched_at).filter((s):s is string=>s!==null).map(s=>Date.parse(s)));const delay=Math.max(0,oldest+data.ttl_seconds*1000-Date.now()+1);const timer=setTimeout(()=>setNow(Date.now()),Math.min(delay,2147483647));return()=>clearTimeout(timer)},[data]);
 return demo||!data?<section className="lark-pilot" aria-label="唯讀 Lark 試讀"><h2>唯讀 Lark 試讀</h2><p role="status" aria-live="polite">{message}</p>{c&&['pilot_roster_stale','pilot_roster_missing'].includes(reason||'')&&<button disabled={busy} onClick={()=>void retryRoster()}>重新核對名冊後重試</button>}</section>:<PilotView data={data} now={now}/>;
}
