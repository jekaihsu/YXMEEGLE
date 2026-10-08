import {Section,Button,Badge} from './design';
import './owned-screens.css';
import {ageFreshness,datasetNotice} from './freshness';
import {useState} from 'react';
import {api,getSessionEpoch,liveRefresh} from './api';
import type {Context} from './Operations';

export function PeopleDirectoryPanel({c}:{c:Context}){
 const[busy,setBusy]=useState(false);const[error,setError]=useState('');const[message,setMessage]=useState('');
 const freshness=c.w.freshness?.datasets.roster;
 const status=c.w.people_directory_status||{};
 const canSync=c.s.mode==='lark'&&c.w.environment==='production'&&(c.s.user?.role==='manager'||c.s.user?.capabilities?.some(k=>['manage_people','manage_sources'].includes(k)));
 const sync=async()=>{const epoch=getSessionEpoch();setBusy(true);setError('');setMessage('');try{if(c.w.freshness?.enabled){const result=await liveRefresh(['roster'],true);if(epoch!==getSessionEpoch())return;c.onFreshness?.(result.freshness);const state=result.freshness&&ageFreshness(result.freshness,Date.now(),Date.now()).datasets.roster;if(!state||state.status!=='fresh'){const notice=state?datasetNotice('roster',state)||'名冊讀取結果尚未確認':'名冊讀取結果尚未確認';if(state&&['refreshing','never','stale'].includes(state.status))setMessage(notice);else setError(notice);return}setMessage('名冊資料已讀取，請核對下方人員。')}else await api('/api/people/sync',{method:'POST'});await c.refresh()}catch(e){if(epoch===getSessionEpoch()){c.onRefreshError?.(['roster']);setError((e as Error).message);await c.refresh()}}finally{if(epoch===getSessionEpoch())setBusy(false)}};
 const directoryPeople=c.w.users.filter(u=>!!(u as any).directory_source);
 const reasons:Record<string,string>={missing_account:'未填寫可識別的 Lark 人員帳號',multiple_accounts:'同一筆名冊填入多個人員帳號',missing_name:'缺少人員姓名',employment_unknown:'在職狀態未明確',duplicate_account:'同一人員帳號出現在多筆名冊'};
 const sourceUrl=status.base_token&&status.table_id?`https://yong-xiang-survey.jp.larksuite.com/base/${encodeURIComponent(status.base_token)}?table=${encodeURIComponent(status.table_id)}`:'';
 return <section className="owned-view" aria-label="Lark 動態人員名冊"><h2>Lark 動態人員名冊</h2><Section><p>來源為「薪水計算」中的人員名單及資料，只同步必要人員欄位。指派及標註使用同一份名冊。</p>
  <p className="dataset-as-of" role="status">{c.s.mode==='demo'?'示範資料':`名冊資料 as of ${freshness?.as_of?new Date(freshness.as_of).toLocaleString('zh-TW'):status.last_success_at?new Date(status.last_success_at).toLocaleString('zh-TW'):'尚無讀取紀錄'}`}</p>{c.s.mode!=='demo'&&freshness&&datasetNotice('roster',freshness)&&<p role="status">{datasetNotice('roster',freshness)}</p>}
  <p><Badge>{status.status==='ready'?'名冊已同步':status.status==='review_required'?'名冊已讀取，部分資料待核對':status.status==='error'?'同步失敗，保留上次名冊':'名冊尚未完成真實同步'}</Badge>{status.last_success_at&&<> · 上次成功：{new Date(status.last_success_at).toLocaleString('zh-TW')}</>}</p>
  {status.last_success_at&&<p>來源 {status.source_count??'—'} 筆 · 可辨識 {status.valid_people??'—'} 人 · 已關聯 {directoryPeople.length} 人</p>}
  {status.message&&<p>{status.message}</p>}
  {sourceUrl&&<p><a href={sourceUrl} target="_blank" rel="noreferrer">開啟 Lark 原始人員名冊</a></p>}
  {!!status.issues?.length&&<details className="ops-notice"><summary>{status.issues.length} 項資料待核對；未按姓名自動合併</summary><ul>{status.issues.map((issue:{record_id?:string;reason?:string},index:number)=><li key={`${issue.record_id}-${issue.reason}-${index}`}>{reasons[issue.reason||'']||'來源資料需人工核對'}{sourceUrl&&issue.record_id&&<> · <a href={`${sourceUrl}&record=${encodeURIComponent(issue.record_id)}`} target="_blank" rel="noreferrer">開啟第 {index+1} 項原始紀錄</a></>}</li>)}</ul></details>}
  {!!status.stats?.missing_retained&&<p className="ops-notice">{status.stats.missing_retained} 位既有人員已不在本次來源名冊，保留歷史並暫停新指派，請核對原始名冊。</p>}
  {status.status==='review_required'&&status.source_count===0&&<p className="ops-notice">本次來源名冊沒有紀錄，尚不能確認人員資料完整。</p>}
  {!!status.field_warnings?.length&&<p className="ops-notice">來源欄位待核對：{status.field_warnings.map((w:{field:string})=>({name:'姓名',department:'部門',employment:'在職狀態'}[w.field]||w.field)).join('、')}。</p>}
  <p><small>{c.w.freshness?.enabled?`開啟工作區時檢查更新，名冊資料有效時間 ${freshness?.ttl_seconds??60} 秒；`:'公司背景同步依目前設定檢查更新；'}新增名冊不自動取得管理或審批權限。已停用的人員不因同步自動恢復。</small></p>
  {canSync?<Button variant="primary" disabled={busy||c.busy} onClick={()=>void sync()}>{busy?'正在核對 Lark 名冊…':'同步 Lark 人員名冊'}</Button>:<p><small>{c.s.mode==='demo'?'此為示範名冊；真實名冊需使用 Lark 登入公司正式工作區。':'請由有名冊同步權限的人員，在公司正式工作區執行同步。'}</small></p>}
  {message&&<p role="status">{message}</p>}
  {error&&<p className="owned-alert" role="alert">{error}</p>}
 </Section></section>;
}
