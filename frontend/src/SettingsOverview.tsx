import {useEffect,useState} from 'react';
import {api} from './api';
import {taipeiTime} from './taipeiTime';
import {ROLE} from './AppShell';
import {RuntimeHealthPanel} from './RuntimeHealthPanel';
import type {Session} from './types';

type Source={name:string;readState:string;last_success_at:string|null;last_attempt_at:string|null;source_as_of:string|null;loaded_count:number|null;total_count:number|null;complete:boolean;last_error_code:string|null};
type Overview={user:{name:string;role:string;permissions:string[]};environment:string;identity_mode:string;features:Record<string,boolean>;sources:Source[];sources_access:string;directory:{status:string;last_success_at:string|null;roster_size?:number|null;matched_accounts?:number|null};datasets:{name:string;status:string;last_success_at:string|null;last_error_code:string|null}[];node_connection:{name:string;status:string;last_success_at:string|null;last_error_code:string|null}[];manager_details_available:boolean};
type Read={kind:'loading'}|{kind:'error'}|{kind:'ready';data:Overview};
const stamp=(value:string|null)=>taipeiTime(value,'尚無成功同步');
const labels:Record<string,string>={unknown:'尚未核實',unconfigured:'尚未設定',restricted:'無權限查看',ready:'已讀取',complete:'完整',complete_empty:'已核實空表',partial:'部分資料',stale:'資料待更新',error:'讀取失敗',read_failed:'讀取失敗',fresh:'有效',never:'尚無成功同步',review_required:'部分資料待核對',refreshing:'更新中',demo:'示範',production:'正式',test:'測試',application:'應用程式',user:'使用者'};
const label=(value:string)=>labels[value]||value;
const featureLabels:Record<string,string>={node_assignment:'節點指派',change_extension:'變更與展延',routines:'追蹤與檢討'};
const permissionLabels:Record<string,string>={read_own_work:'查看本人工作',manage_people:'人員授權',publish_sop:'發布 SOP',edit_sop:'編修 SOP',manage_sources:'來源管理',finance_approve:'金額核准',finance_edit:'財務編輯',calendar_edit:'工作日曆',issue_confirmation:'發出確認單',review_mapping:'日報核對',manage_handover:'人員交接',manage_training:'訓練管理',approve_capability:'能力核准'};
export function SettingsOverview({s,workspaceId}:{s:Session;workspaceId?:string}){
 const[read,setRead]=useState<Read>({kind:'loading'});const[retry,setRetry]=useState(0);
 useEffect(()=>{const controller=new AbortController();setRead({kind:'loading'});
  void api<Overview>('/api/settings/overview',{signal:controller.signal,timeoutMs:15000}).then(data=>{
   if(!data.user||typeof data.user.name!=='string'||typeof data.user.role!=='string'||!Array.isArray(data.user.permissions)||!data.user.permissions.every(value=>typeof value==='string')||
    typeof data.environment!=='string'||typeof data.identity_mode!=='string'||typeof data.sources_access!=='string'||
    !Array.isArray(data.sources)||!data.sources.every(row=>row&&typeof row.name==='string'&&typeof row.readState==='string')||
    !Array.isArray(data.datasets)||!data.datasets.every(row=>row&&typeof row.name==='string'&&typeof row.status==='string')||
    !Array.isArray(data.node_connection)||!data.node_connection.every(row=>row&&typeof row.name==='string'&&typeof row.status==='string')||
    !data.directory||typeof data.directory.status!=='string'||!data.features||typeof data.features!=='object'||Array.isArray(data.features)||!Object.values(data.features).every(value=>typeof value==='boolean'))throw Error('invalid');
   if(!controller.signal.aborted)setRead({kind:'ready',data});
  }).catch(()=>{if(!controller.signal.aborted)setRead({kind:'error'})});return()=>controller.abort();
 },[s.user?.id,s.user?.role,s.mode,workspaceId,retry]);
 return <section className="owned-view" aria-label="設定概況"><h2>設定概況</h2>
  <button type="button" disabled={read.kind==='loading'} onClick={()=>setRetry(x=>x+1)}>重新讀取</button>
  {read.kind==='loading'&&<p role="status">正在讀取設定摘要…</p>}
  {read.kind==='error'&&<p role="alert">設定摘要無法讀取，請重試。若持續失敗，請聯絡管理員確認連線與權限。</p>}
  {read.kind==='ready'&&<><p>{read.data.user.name} · {ROLE[read.data.user.role] || '角色待核對'} · {label(read.data.environment)}工作區</p>
   <p>Lark 連線身分 {label(read.data.identity_mode)}</p><p>本人權限 {read.data.user.permissions.flatMap(key=>permissionLabels[key]?[permissionLabels[key]]:[]).join('、') || '尚無可顯示權限'}</p>
   <h3>功能開放狀態</h3><ul>{Object.entries(read.data.features).filter(([key])=>featureLabels[key]).map(([key,on])=><li key={key}>{featureLabels[key]} {on?'已開啟':'尚未開放'}</li>)}</ul>
   <h3>來源同步</h3>{read.data.sources_access==='restricted'?<p>逐表維護資訊需來源管理權限。</p>:read.data.sources.length===0?<p>尚無成功同步的來源紀錄。</p>:<ul>{read.data.sources.map((source,index)=><li key={index}><strong>{source.name}</strong> {label(source.readState)} · {source.complete?'完整':'完整性尚未核實'}<p>最近成功 {stamp(source.last_success_at)} · 最近嘗試 {source.last_attempt_at?taipeiTime(source.last_attempt_at):'尚無紀錄'}</p><p>已載入 {source.loaded_count??'未知'} 筆 · 總數 {source.total_count??'未知'} · 來源更新 {source.source_as_of?taipeiTime(source.source_as_of):'未知'}</p>{source.last_error_code&&<p>錯誤代碼 {source.last_error_code}</p>}</li>)}</ul>}
   <h3>即時讀取資料集</h3><ul>{read.data.datasets.map(item=><li key={item.name}>{item.name} · {label(item.status)} · {stamp(item.last_success_at)}{item.last_error_code&&` · ${item.last_error_code}`}</li>)}</ul>
   <h3>人員名冊</h3><p>{label(read.data.directory.status)} · {stamp(read.data.directory.last_success_at)}</p>{read.data.directory.status!=='restricted'&&<p>名冊 {read.data.directory.roster_size??'未知'} 筆 · 可辨識 Lark 帳號 {read.data.directory.matched_accounts??'未知'} 人</p>}
   <h3>節點指派連線</h3><p>僅檢查既有快取，未知不表示可讀取。此頁不發出新的 Lark 查詢。</p>{read.data.node_connection.length?<ul>{read.data.node_connection.map(item=><li key={item.name}>{item.name} · {label(item.status)} · {stamp(item.last_success_at)}{item.last_error_code&&` · ${item.last_error_code}`}</li>)}</ul>:<p>{read.data.sources_access==='restricted'?'連線維護資訊需來源管理權限。':'尚無節點指派連線紀錄。'}</p>}
   {read.data.manager_details_available?<RuntimeHealthPanel s={s} w={{environment:read.data.environment,workspace_id:workspaceId}}/>:<p>背景工作與備份維護資訊僅供正式工作區管理員查看。</p>}
  </>}
 </section>;
}
