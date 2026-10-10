import {Section,Row,Button,Badge} from './design';
import {ViewSkeleton} from './viewData';
import './owned-screens.css';
import {useEffect,useState} from 'react';
import {api} from './api';
import type {Session} from './types';

type HealthItem={status:string;last_success_at?:string|null;last_heartbeat_at?:string|null;last_checked_at?:string|null;recovery_hint?:string;blocking?:boolean};
type Health={checked_at:string;status:string;worker:HealthItem;backup:HealthItem;directory:HealthItem};
const labels:Record<string,string>={ok:'正常',warning:'即將逾期或資料待核對',attention:'需要處理',missing:'尚無紀錄',unavailable:'暫時無法讀取',invalid:'紀錄格式待處理',stale:'紀錄已逾期',degraded:'最近執行異常',starting:'啟動中，尚無成功紀錄',not_configured:'尚未設定',local_only:'僅本機備份'};
const stamp=(value?:string|null)=>value&&Number.isFinite(Date.parse(value))?new Date(value).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'尚無';
export function RuntimeHealthPanel({w,s}:{w:{environment?:string;workspace_id?:string};s:Session}){
 const[health,setHealth]=useState<Health|null>(null);const[error,setError]=useState('');const[loading,setLoading]=useState(false);const[reload,setReload]=useState(0);
 const allowed=s.mode==='lark'&&w.environment==='production'&&s.user?.role==='manager';
 useEffect(()=>{if(!allowed){setHealth(null);return}const abort=new AbortController();setLoading(true);setHealth(null);setError('');void api<Health>('/api/admin/runtime-health',{signal:abort.signal}).then(result=>{if(!result.worker||!result.backup||!result.directory)throw Error('維護狀態回應不完整');setHealth(result)}).catch(e=>{if(!abort.signal.aborted)setError((e as Error).message)}).finally(()=>{if(!abort.signal.aborted)setLoading(false)});return()=>abort.abort()},[allowed,reload,w.workspace_id]);
 if(!allowed)return null;
 return <section aria-label="系統維護狀態" className="owned-view">
  <div className="section-heading"><div><h2>系統維護狀態</h2><p>名冊有效時間、背景工作與備份排程，時間以台灣時區顯示。</p></div><Button disabled={loading} onClick={()=>setReload(x=>x+1)}>{loading?'讀取中…':'更新維護狀態'}</Button></div>
  {error&&<p role="alert" className="owned-alert">維護狀態未能讀取：{error}</p>}
  {loading&&<ViewSkeleton rows={3}/>}
  {health&&<><p role="status">{labels[health.status]||'狀態待核對'} · 查詢時間 {stamp(health.checked_at)}</p>
   <Section>{[['directory','公司名冊'],['worker','背景工作'],['backup','備份排程']].map(([key,name])=>{
    const item=health[key as 'directory'|'worker'|'backup'];return <Row key={key} label={<div>
     <header><strong>{name}</strong><Badge>{labels[item.status]||'狀態待核對'}</Badge></header><p>最近成功：{stamp(item.last_success_at)}</p>
     {key==='directory'?<p>{item.status==='ok'?'名冊來源目前有效；個別人員仍依各自資格核對。':item.recovery_hint}</p>:<p>{key==='worker'?'最近心跳':'最近檢查'}：{stamp(key==='worker'?item.last_heartbeat_at:item.last_checked_at)}</p>}
    </div>}/>})}</Section>
   <p>名冊依來源成功讀取時間判斷，背景心跳不會延長名冊效期。本頁不代表 Lark 各項串接或異地備份還原已驗收，也未發送外部告警。</p>
  </>}
 </section>;
}
