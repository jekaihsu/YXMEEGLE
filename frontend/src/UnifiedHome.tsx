import {useEffect,useState,type ReactNode} from 'react';
import {ArrowDown,ArrowUp,CalendarDays,Check,Settings2,RotateCcw,RefreshCw} from 'lucide-react';
import {Button,Eyebrow} from './design';
import {type Ctx,date} from './appCommon';
import {useHomePanels,type PanelRead} from './useHomePanels';
import {fetchPeopleAttendance,parsePeopleAttendance,taipeiWeek} from './peopleAttendance';
import {useViewData} from './viewData';
import {ApiError} from './api';
import {HOME_CARDS,HOME_VIEWS,homeSections,availableViews,resolvePersona,defaultHomeLayout,parseHomeLayout,moveHomeCard,homeLayoutKey,taipeiToday,type HomeCardId,type HomeLayout,type HomeSettings,type HomeViewId} from './homeLayout';
import {PeopleCard} from './homePeopleCards';
import type {PeopleAttendance} from './peopleAttendance';
import {AttendanceCard,Message} from './homeCards';
import {HomeHelp} from './homeHelp';
import {panelSource,workSource} from './homeWorkSource';
import {MineCard} from './homeViews/MineCards';
import {AssignCard,useAssignData} from './homeViews/AssignCards';
import {CompanyCard} from './homeViews/CompanyCards';
import {useHomeCompany} from './useHomeCompany';
import {HOME_PREVIEWS,useHomePreview} from './homeRolePreview';
import {useHomeReports,type HomeReportsRead} from './useHomeReports';
import {isReportCard,canReadHomeReports} from './homeReportCards';
import {ReportCard,CopyReportSummary} from './homeViews/ReportCard';
import './UnifiedHome.css';

function Sections({view,ids,render,reportStale=false}:{view:HomeViewId;ids:HomeCardId[];render:(id:HomeCardId)=>ReactNode;reportStale?:boolean}){return <>{ids.includes('kpi')&&render('kpi')}{homeSections(view,{order:ids,hidden:[]}).map(section=><section className="home-section" data-home-section={section.id} key={section.id} aria-labelledby={`home-section-${section.id}`}><header><h2 id={`home-section-${section.id}`}>{section.label}</h2><p>{section.hint}</p>{reportStale&&section.cards.some(isReportCard)&&<small className="home-source-note">週報資料為舊快照</small>}</header>{section.cards.includes('attention')&&<div className="home-attention-strip">{render('attention')}</div>}<div className="home-card-grid">{section.cards.filter(id=>id!=='attention').map(render)}</div></section>)}</>}

type ViewProps={attendanceRead:{view?:PeopleAttendance;loading:boolean;error:string};ids:HomeCardId[];c:Ctx;today:string;assigned:PanelRead;confirmation:PanelRead;attendance:(id:'leave'|'trips')=>ReactNode};
function AssignView(props:ViewProps){
 const data=useAssignData(props.c);
 const unavailable=!data.team.pending&&!data.review.pending&&!panelSource(data.team)&&!panelSource(data.review);
 return <>{unavailable&&<div className="home-view-notice" role="status">{data.team.error||data.review.error||'團隊工作來源尚未提供。'} <a href="#view=projects">前往案件分配</a></div>}<Sections view="assign" ids={props.ids.filter(id=>!unavailable||!['allocation','workload'].includes(id))} render={id=>id==='absence'||id==='impact'?<PeopleCard key={id} id={id} scope="assign" department={props.c.s.user?.department} today={props.today} team={data.team} {...props.attendanceRead}/>:<AssignCard key={id} id={id} {...props} {...data}/>}/></>;
}
function CompanyView(props:ViewProps&{reports:HomeReportsRead}){
 const read=useHomeCompany(props.c);
 const missing=!read.data&&!read.pending;
 const unavailable=read.data&&read.data.source.status!=='ready'&&!read.data.groups.length&&!read.data.cases.length;
 return <>{(missing||unavailable||read.data?.complete===false)&&<div className="home-view-notice" role="status">{read.error||(unavailable?'公司來源尚未提供，僅顯示已載入總數。':'公司快照尚未完整，統計僅涵蓋已載入來源。')} <a href="#view=company">開啟公司駕駛艙</a></div>}<Sections view="company" reportStale={!!(props.reports.data?.meta.stale||props.reports.data?.meta.refresh_error||props.reports.error&&props.reports.data)} ids={props.ids.filter(id=>(!isReportCard(id)||canReadHomeReports(props.c.s.user?.role)&&!props.reports.unavailable)&&(!unavailable||!['groups','cases','statuses'].includes(id)))} render={id=>isReportCard(id)?<ReportCard key={id} id={id} read={props.reports}/>:id==='absence'?<PeopleCard key={id} id={id} scope="company" today={props.today} {...props.attendanceRead}/>:id==='leave'||id==='trips'?props.attendance(id):<CompanyCard key={id} id={id} {...props} read={read}/>}/></>;
}
export function UnifiedHome({c}:{c:Ctx}){
 const key=homeLayoutKey(c.s.workspace_id||c.w.workspace_id||'default',c.s.user?.id||'anonymous',c.s.user?.role||'',c.s.mode);
 const preview=useHomePreview();
 return <HomeWorkspace key={key+'|'+(preview||'')} c={c} storageKey={key} preview={preview}/>;
}
function HomeWorkspace({c,storageKey,preview}:{c:Ctx;storageKey:string;preview:keyof typeof HOME_PREVIEWS|null}){
 const [previewView,setPreviewView]=useState<HomeViewId|null>(null);
 const [settings,setSettings]=useState<HomeSettings>(()=>{try{return parseHomeLayout(localStorage.getItem(storageKey))}catch{return parseHomeLayout(null)}});
 const [editing,setEditing]=useState(false),[saved,setSaved]=useState(true),[notice,setNotice]=useState('');
 const [today,setToday]=useState(taipeiToday);
 const [refreshing,setRefreshing]=useState(false),[refreshTick,setRefreshTick]=useState(0),[refreshError,setRefreshError]=useState('');
 const homeContext={...c,reloadVersion:(c.reloadVersion||0)+refreshTick};
 const assigned=useHomePanels(homeContext,{panel:'assigned',scope:'mine',limit:100});
 const confirmation=useHomePanels(homeContext,{panel:'confirmation',scope:'mine',limit:100});
 const manager=assigned.body?.manager_view_available??null;
 const views:HomeViewId[]=preview?[...HOME_PREVIEWS[preview].views]:availableViews(c.s.user,manager);
 const chosen=preview?previewView:settings.view;
 const view=chosen&&views.includes(chosen)?chosen:preview?views[0]:assigned.pending&&!assigned.body?'mine':resolvePersona(c.s.user,manager);
 const layout=settings.layouts[view];
 const refresh=async()=>{setRefreshing(true);setRefreshError('');try{await c.refresh()}catch{setRefreshError('工作區重新讀取失敗；已保留上次資料，請稍後再試。')}finally{setRefreshTick(value=>value+1);setRefreshing(false)}};
 useEffect(()=>{const timer=window.setInterval(()=>setToday(taipeiToday()),60000);return()=>window.clearInterval(timer)},[]);
 const attendance=useViewData(`home-attendance:${storageKey}:${taipeiWeek(today)}`,async(signal,current)=>{
  try{return await fetchPeopleAttendance({week:taipeiWeek(today),signal,current})}
  catch(error){if(error instanceof ApiError&&error.status===403)return parsePeopleAttendance({status:'needs-permission'});throw error}
 },[c.reloadVersion,c.w.version,today,refreshTick]);
 const persist=(next:HomeSettings,message:string)=>{
  setSettings(next);setNotice(message);
  try{localStorage.setItem(storageKey,JSON.stringify(next));setSaved(true)}catch{setSaved(false)}
 };
 const update=(next:HomeLayout,message:string)=>persist({...settings,layouts:{...settings.layouts,[view]:next}},message);
 const choose=(next:HomeViewId)=>preview?(setPreviewView(next),setNotice(`已切換至${HOME_VIEWS[next].label}`)):persist({...settings,view:next},`已切換至${HOME_VIEWS[next].label}`);
 const visible=layout.order.filter(id=>!layout.hidden.includes(id));
 const reports=useHomeReports(homeContext,view,visible);
 const asOf=c.w.as_of;
 const freshnessDays=asOf?Math.floor((Date.parse(`${taipeiToday()}T00:00:00Z`)-Date.parse(`${asOf.slice(0,10)}T00:00:00Z`))/86400000):null;
 const stale=freshnessDays!==null&&freshnessDays>1;
 const attendanceCard=(id:'leave'|'trips')=><AttendanceCard key={id} id={id} view={attendance.data} loading={attendance.loading} error={attendance.error} today={today}/>;
 const props:ViewProps={attendanceRead:{view:attendance.data,loading:attendance.loading,error:attendance.error},ids:visible,c:homeContext,today,assigned,confirmation,attendance:attendanceCard};
 const missingMine=!assigned.pending&&!confirmation.pending&&!workSource(homeContext,'assigned',today,assigned)&&!workSource(homeContext,'confirmation',today,confirmation);
 const renderCard=(id:HomeCardId)=>id==='leave'||id==='trips'?attendanceCard(id):<MineCard key={id} id={id} {...props}/>;
 return <div className="unified-home" data-home-view={view}><div className="ds-page"><header className="ds-page-head"><div>
  <Eyebrow>{today.replaceAll('-','/')+' · '+(c.s.user?.name||'我的工作空間')}</Eyebrow><h1>今日工作台</h1><p>{HOME_VIEWS[view].label}，掌握今天需要處理的事。{preview&&<> · 預覽角色：{HOME_PREVIEWS[preview].label}</>}</p>
  {views.length>1&&<div className="home-view-switcher" role="group" aria-label="首頁視圖">{views.map(id=><Button key={id} aria-pressed={view===id} onClick={()=>choose(id)}>{HOME_VIEWS[id].label}</Button>)}</div>}
 </div><div className="ds-actions">
  {view==='company'&&reports.data&&!reports.unavailable&&<CopyReportSummary report={reports.data}/>}
  <Button disabled={refreshing||c.busy} onClick={()=>void refresh()}><RefreshCw size={16}/>{refreshing?'讀取中…':'重新讀取'}</Button>
  <Button onClick={()=>c.go({view:'schedule'})}><CalendarDays size={16}/>查看排程</Button>
  <Button variant="plain" aria-expanded={editing} aria-controls="home-customize" onClick={()=>setEditing(value=>!value)}>{editing?<Check size={16}/>:<Settings2 size={16}/>} {editing?'完成設定':'自訂首頁'}</Button>
  <HomeHelp view={view}/>
 </div></header>
  {editing&&<section className="home-customize glass--flat" id="home-customize" aria-label="自訂首頁卡片">
   <header><div><h2>安排你的首頁 · {HOME_VIEWS[view].label}</h2><p>顯示、隱藏與排序目前視圖的卡片。設定依登入身分與視圖儲存在此瀏覽器。</p></div><Button onClick={()=>update(defaultHomeLayout(view),'已還原目前視圖的建議配置')}><RotateCcw size={15}/>還原建議配置</Button></header>
   {[{id:'summary',label:'工作摘要',cards:layout.order.filter(id=>HOME_CARDS[id].section===null)},...homeSections(view,{...layout,hidden:[]})].filter(section=>section.cards.length).map(section=><section key={section.id} data-customize-section={section.id}><h3>{section.label}</h3><ol>{section.cards.map((id,index)=>{const card=HOME_CARDS[id];return <li key={id}>
    <label><input type="checkbox" checked={!layout.hidden.includes(id)} onChange={()=>update({...layout,hidden:layout.hidden.includes(id)?layout.hidden.filter(value=>value!==id):[...layout.hidden,id]},`${card.title}已${layout.hidden.includes(id)?'顯示':'隱藏'}`)}/><span><strong>{card.title}</strong><small>{card.description}</small></span></label>
    <div><Button aria-label={`向上移動${card.title}`} disabled={index===0} onClick={()=>update(moveHomeCard(layout,id,-1),`${card.title}已向上移動`)}><ArrowUp size={16}/></Button><Button aria-label={`向下移動${card.title}`} disabled={index===section.cards.length-1} onClick={()=>update(moveHomeCard(layout,id,1),`${card.title}已向下移動`)}><ArrowDown size={16}/></Button></div>
   </li>})}</ol></section>)}
  </section>}
  <span className="sr-only" role="status">{notice}</span>
  {asOf&&<p className={`home-freshness${stale?' is-stale':''}`} role="status">資料截至 {date(asOf)}{stale?' · 可能已過期':''}</p>}
  {refreshError&&<Message>{refreshError}</Message>}
  {!saved&&<Message>瀏覽器無法儲存設定；目前配置在離開此頁後可能重設。</Message>}
  {!visible.length&&<div className="home-empty glass--flat"><h2>挑選今天需要的內容</h2><p>尚未顯示任何卡片。開啟「自訂首頁」加入工作、案件或團隊動向。</p><Button onClick={()=>setEditing(true)}>選擇首頁卡片</Button></div>}
  <div className="home-sections">{view==='mine'?<>{missingMine&&<div className="home-view-notice" role="status">{assigned.error||confirmation.error||'個人工作來源尚未提供。'} <a href="#view=work">開啟我的工作</a></div>}<Sections view="mine" ids={visible.filter(id=>!missingMine||!['work','confirmation','deadlines'].includes(id))} render={renderCard}/></>:view==='assign'?<AssignView {...props}/>:<CompanyView {...props} reports={reports}/>}</div>
 </div></div>;
}
