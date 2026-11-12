import {useState} from 'react';
import {api,perfMark} from './api';
import {useViewData} from './viewData';
import {taipeiTime} from './taipeiTime';
import type {LinkSummary} from './reportLinksModel';
import type {Session} from './types';
import './settings-overview.css';
type Overview={user?:{name:string};directory:{status:string;last_success_at:string|null;roster_size?:number|null;matched_accounts?:number|null;linked_identities?:number|null;review_items?:number|null};admin_summary?:{templates:{version:number;status:string}[]|null;jobs:{loaded:number;blocked:number}|null;attendance:{ready:number|null;manual:number|null}|null}};
export function SettingsOverview({s,workspaceId}:{s:Session;workspaceId?:string}){
 const[revision,setRevision]=useState(0);
 const read=useViewData<Overview>(`settings-cards:${workspaceId}:${s.user?.id}`,async(signal)=>{const data=await api<Overview>('/api/settings/overview',{signal,timeoutMs:15000});if(!data.directory)throw Error('設定摘要格式待核對');perfMark('settings-summary-ready');return data},[revision]);
 const allowed=!!s.user&&['manager','admin','pm'].includes(s.user.role);
 const links=useViewData<LinkSummary>(`settings-links:${workspaceId}:${s.user?.id}:${allowed}`,async(signal)=>allowed?api<LinkSummary>('/api/report-links/summary',{signal}):null as unknown as LinkSummary,[revision]);
 const d=read.data?.directory,summary=read.data?.admin_summary;
 const count=(n:number|null|undefined)=>n??'未知';
 const cards=[
  {tab:'people',title:'人員與權限',text:d?.status==='restricted'?'無權限查看名冊統計':`來源 ${count(d?.roster_size)} 筆 · 可辨識 ${count(d?.matched_accounts)} 人 · 已關聯身份 ${count(d?.linked_identities)} · ${count(d?.review_items)} 項待核對`,note:`名冊資料時間 ${taipeiTime(d?.last_success_at,'來源未提供')}`},
  {tab:'daily',title:'日報核對',text:links.data?`日報已連結 ${links.data.linked} / ${links.data.total} 筆 · ${links.data.unlinked} 筆待配對`:'日報連結筆數未知',note:links.error?'摘要讀取失敗，請重新讀取':'全公司日報範圍；配對不代表審核完成'},
  {tab:'sop',title:'SOP 範本',text:summary?.templates?.map(t=>`v${t.version??'未知'} ${t.status==='published'?'已發布':t.status==='draft'?'草稿':'狀態待核對'}`).join(' · ')||'版本資料尚未取得',note:'案件保留案內版本；已發布版本不可直接改寫'},
  {tab:'configuration',title:'日曆與連線',text:`班表可用 ${count(summary?.attendance?.ready)} 筆 · 人工優先 ${count(summary?.attendance?.manual)} 筆`,note:'缺少員工對應或班次時保持待設定'},
  {tab:'jobs',title:'背景工作',text:summary?.jobs?`已載入 ${summary.jobs.loaded} 筆工作 · ${summary.jobs.blocked} 筆功能尚未開放`:'背景工作筆數未知',note:'追蹤與檢討功能尚未開放；不表示執行失敗'},
 ];
 return <section className="owned-view settings-overview-container" aria-label="設定概況"><header className="so-topbar"><h2>設定概況</h2><button className="so-retry-btn" disabled={read.loading||links.loading} onClick={()=>setRevision(n=>n+1)}>重新讀取</button></header><p>{read.data?.user?.name} · 選擇設定區查看來源與待核對事項。</p>{read.loading&&!read.data&&<p role="status">正在讀取設定摘要…</p>}{read.error&&<p role="alert">設定摘要無法讀取；{read.data?'保留上次資料。':'統計未知，請重新讀取。'}</p>}<div className="admin-summary-cards">{cards.map(card=><a key={card.tab} className="admin-summary-card" href={`#view=admin&tab=${card.tab}`}><h3>{card.title}<span aria-hidden="true"> →</span></h3><p>{card.text}</p><small>{card.note}</small></a>)}</div></section>;
}
