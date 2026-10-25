import {HomeDispatchCard} from './HomeDispatchCard';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {ArrowDown,ArrowUp,Check,Settings2,RotateCcw,RefreshCw} from 'lucide-react';
import {Button,Eyebrow} from './design';
import {type Ctx,date} from './appCommon';
import {useHomePanels,type PanelRead} from './useHomePanels';
import {fetchPeopleAttendance,parsePeopleAttendance,taipeiWeek} from './peopleAttendance';
import {useViewData} from './viewData';
import {ApiError} from './api';
import {HOME_CARDS,HOME_VIEWS,homeSections,availableCardIds,availableViews,resolvePersona,defaultHomeLayout,parseHomeLayout,moveHomeCard,homeLayoutKey,taipeiToday,type HomeCardId,type HomeLayout,type HomeSettings,type HomeViewId} from './homeLayout';
import {PeopleCard} from './homePeopleCards';
import type {PeopleAttendance} from './peopleAttendance';
import {AttendanceCard,Message} from './homeCards';
import {HomeHelp} from './homeHelp';
import {panelSource,workSource} from './homeWorkSource';
import {MineCard} from './homeViews/MineCards';
import {AssignCard,useAssignData} from './homeViews/AssignCards';
import {CompanyCard} from './homeViews/CompanyCards';
import {useHomeCompany} from './useHomeCompany';
import {HOME_PREVIEWS} from './homeRolePreview';
import {useHomeReports,type HomeReportsRead} from './useHomeReports';
import {isReportCard} from './homeReportCards';
import {ReportCard,CopyReportSummary} from './homeViews/ReportCard';
import './UnifiedHome.css';

function Sections({view,ids,render,reportStale=false}:{view:HomeViewId;ids:HomeCardId[];render:(id:HomeCardId)=>ReactNode;reportStale?:boolean}){
 const sections=homeSections(view,{order:ids,hidden:[]});
 const renderSection=(section:typeof sections[number])=><section className="home-section" data-home-section={section.id} key={section.id} aria-labelledby={`home-section-${section.id}`}><header><h2 id={`home-section-${section.id}`}>{section.label}</h2>{reportStale&&section.cards.some(isReportCard)&&<small className="home-source-note">週報資料為舊快照</small>}</header>{section.cards.includes('attention')&&<div className="home-attention-strip">{render('attention')}</div>}<div className="home-card-grid">{section.cards.filter(id=>id!=='attention').map(render)}</div></section>;
 return <>{sections.filter(section=>section.id==='todo').map(renderSection)}{ids.includes('kpi')&&render('kpi')}{sections.filter(section=>section.id!=='todo').map(renderSection)}</>;
}

type ViewProps={attendanceRead:{view?:PeopleAttendance;loading:boolean;error:string};ids:HomeCardId[];c:Ctx;today:string;assigned:PanelRead;confirmation:PanelRead;dispatch:()=>ReactNode;attendance:(id:'leave'|'trips')=>ReactNode};
function AssignView(props:ViewProps){
 const data=useAssignData(props.c);
 const unavailable=!data.team.pending&&!data.review.pending&&!panelSource(data.team)&&!panelSource(data.review);
 return <>{unavailable&&<div className="home-view-notice" role="status">{data.team.error||data.review.error||'團隊工作來源尚未提供。'} <a href="#view=projects">前往案件分配</a></div>}<Sections view="assign" ids={props.ids.filter(id=>!unavailable||!['allocation','workload'].includes(id))} render={id=>id==='dispatch'?props.dispatch():id==='absence'||id==='impact'?<PeopleCard key={id} id={id} scope="assign" department={props.c.s.user?.department} today={props.today} team={data.team} {...props.attendanceRead}/>:<AssignCard key={id} id={id} {...props} {...data}/>}/></>;
}
function CompanyView(props:ViewProps&{reports:HomeReportsRead}){
 const read=useHomeCompany(props.c);
 const missing=!read.data&&!read.pending;
 const unavailable=read.data&&read.data.source.status!=='ready'&&!read.data.groups.length&&!read.data.cases.length;
 return <>{(missing||unavailable||read.data?.complete===false)&&<div className="home-view-notice" role="status">{read.error||(unavailable?'公司資料尚未完整。':'公司快照尚未完整，統計僅涵蓋已載入來源。')} <a href="#view=projects">開啟案件總覽</a></div>}<Sections view="company" reportStale={!!(props.reports.data?.meta.stale||props.reports.data?.meta.refresh_error||props.reports.error&&props.reports.data)} ids={props.ids.filter(id=>(!unavailable||!['kpi','groups','cases','statuses'].includes(id)))} render={id=>id==='dispatch'?props.dispatch():isReportCard(id)?<ReportCard key={id} id={id} read={props.reports}/>:id==='absence'?<PeopleCard key={id} id={id} scope="company" today={props.today} {...props.attendanceRead}/>:id==='leave'||id==='trips'?props.attendance(id):<CompanyCard key={id} id={id} {...props} read={read}/>}/></>;
}
export function UnifiedHome({c}:{c:Ctx}){
 const key=homeLayoutKey(c.s.workspace_id||c.w.workspace_id||'default',c.s.user?.id||'anonymous',c.s.user?.role||'',c.s.mode);
 useEffect(()=>{try{localStorage.removeItem('yx.home.preview')}catch{}},[]);
 return <HomeWorkspace key={key} c={c} storageKey={key} preview={null}/>;
}
function HomeWorkspace({c,storageKey,preview}:{c:Ctx;storageKey:string;preview:keyof typeof HOME_PREVIEWS|null}){
 const [previewView,setPreviewView]=useState<HomeViewId|null>(null);
 const [settings,setSettings]=useState<HomeSettings>(()=>{try{return parseHomeLayout(localStorage.getItem(storageKey))}catch{return parseHomeLayout(null)}});
 const [editing,setEditing]=useState(false),[saved,setSaved]=useState(true),[notice,setNotice]=useState('');
 const [today,setToday]=useState(taipeiToday);
 const [refreshing,setRefreshing]=useState(false),[refreshTick,setRefreshTick]=useState(0),[refreshError,setRefreshError]=useState('');
 const readGeneration=useRef((c.reloadVersion??c.w.version)+refreshTick);
 if(!refreshing)readGeneration.current=(c.reloadVersion??c.w.version)+refreshTick;
 const homeContext={...c,reloadVersion:readGeneration.current};
 const [workKind,setWorkKind]=useState('');
 const assigned=useHomePanels(homeContext,{panel:'assigned',scope:'mine',limit:100,kinds:workKind||undefined});
 const manager=assigned.body?.manager_view_available??null;
 const views:HomeViewId[]=preview?[...HOME_PREVIEWS[preview].views]:availableViews(c.s.user,manager);
 const chosen=preview?previewView:settings.view;
 const view=chosen&&views.includes(chosen)?chosen:preview?views[0]:assigned.pending&&!assigned.body?'mine':resolvePersona(c.s.user,manager);
 const layout=settings.layouts[view];
 const visible=layout.order.filter(id=>!layout.hidden.includes(id));
 const needsConfirmation=visible.includes('confirmation');
 const needsAttendance=visible.some(id=>['leave','trips','absence','impact'].includes(id));
 const confirmation=useHomePanels(homeContext,{panel:'confirmation',scope:'mine',limit:100},needsConfirmation);
 const refresh=async()=>{setRefreshing(true);setRefreshError('');try{await c.refresh()}catch{setRefreshError('工作區重新讀取失敗；已保留上次資料，請稍後再試。')}finally{setRefreshTick(value=>value+1);setRefreshing(false)}};
 useEffect(()=>{const timer=window.setInterval(()=>setToday(taipeiToday()),60000);return()=>window.clearInterval(timer)},[]);
 const attendance=useViewData(`home-attendance:${storageKey}:${taipeiWeek(today)}:${needsAttendance}`,async(signal,current)=>{
  if(!needsAttendance)return undefined;
  try{return await fetchPeopleAttendance({week:taipeiWeek(today),signal,current})}
  catch(error){if(error instanceof ApiError&&error.status===403)return parsePeopleAttendance({status:'needs-permission'});throw error}
 },[homeContext.reloadVersion,today]);
 const persist=(next:HomeSettings,message:string)=>{
  setSettings(next);setNotice(message);
  try{localStorage.setItem(storageKey,JSON.stringify(next));setSaved(true)}catch{setSaved(false)}
 };
 const update=(next:HomeLayout,message:string)=>persist({...settings,layouts:{...settings.layouts,[view]:next}},message);
 const choose=(next:HomeViewId)=>preview?(setPreviewView(next),setNotice(`已切換至${HOME_VIEWS[next].label}`)):persist({...settings,view:next},`已切換至${HOME_VIEWS[next].label}`);
 const reports=useHomeReports(homeContext,view,visible,today);
 const available=availableCardIds(view,c.s.user,reports,c.s);
 const availableOrder=layout.order.filter(id=>available.includes(id));
 const availableVisible=visible.filter(id=>available.includes(id));
 const move=(id:HomeCardId,direction:-1|1)=>{
  const next=moveHomeCard(layout,id,direction,available);
  if(next!==layout)update(next,`${HOME_CARDS[id].title}已向${direction===1?'下':'上'}移動`);
 };
 const asOf=c.w.as_of;
 const freshnessDays=asOf?Math.floor((Date.parse(`${taipeiToday()}T00:00:00Z`)-Date.parse(`${asOf.slice(0,10)}T00:00:00Z`))/86400000):null;
 const stale=freshnessDays!==null&&freshnessDays>1;
 const attendanceCard=(id:'leave'|'trips')=><AttendanceCard key={id} id={id} view={attendance.data} loading={attendance.loading} error={attendance.error} today={today}/>;
 const dispatchCard=()=><HomeDispatchCard key="dispatch" today={today} reloadVersion={homeContext.reloadVersion}/>;
 const attendanceUnavailable=!attendance.loading&&(!attendance.data||!['ok','incomplete','stale'].includes(attendance.data.status));
 const contentIds=availableVisible.filter(id=>!attendanceUnavailable||!['leave','trips','absence','impact'].includes(id));
 const props:ViewProps={dispatch:dispatchCard,attendanceRead:{view:attendance.data,loading:attendance.loading,error:attendance.error},ids:contentIds,c:homeContext,today,assigned,confirmation,attendance:attendanceCard};
 const missingMine=!assigned.pending&&!confirmation.pending&&!workSource(homeContext,'assigned',today,assigned)&&!workSource(homeContext,'confirmation',today,confirmation);
 const renderCard=(id:HomeCardId)=>id==='dispatch'?dispatchCard():id==='leave'||id==='trips'?attendanceCard(id):<MineCard key={id} id={id} {...props}/>;
 return <div className="unified-home" data-home-view={view}><div className="ds-page"><header className="ds-page-head"><div>
  <Eyebrow>{today.replaceAll('-','/')+' · '+(c.s.user?.name||'我的工作空間')}</Eyebrow><h1>今日工作台</h1>{preview&&<p>預覽角色：{HOME_PREVIEWS[preview].label}</p>}
  {views.length>1&&<div className="home-view-switcher" role="group" aria-label="首頁視圖">{views.map(id=><Button key={id} aria-pressed={view===id} onClick={()=>choose(id)}>{HOME_VIEWS[id].label}</Button>)}</div>}
 </div><div className="ds-actions">
  {view==='company'&&reports.data&&!reports.unavailable&&<CopyReportSummary report={reports.data}/>}
  <Button disabled={refreshing||c.busy} onClick={()=>void refresh()}><RefreshCw size={16}/>{refreshing?'讀取中…':'重新讀取'}</Button>
 </div></header>
  {editing&&<section className="home-customize glass--flat" id="home-customize" aria-label="自訂首頁卡片">
   <header><div><h2>安排你的首頁 · {HOME_VIEWS[view].label}</h2><p>顯示、隱藏與排序目前視圖的卡片。設定依登入身分與視圖儲存在此瀏覽器。</p></div><Button onClick={()=>update(defaultHomeLayout(view),'已還原目前視圖的建議配置')}><RotateCcw size={15}/>還原建議配置</Button></header>
   {[{id:'summary',label:'工作摘要',cards:availableOrder.filter(id=>HOME_CARDS[id].section===null)},...homeSections(view,{order:availableOrder,hidden:[]})].filter(section=>section.cards.length).map(section=><section key={section.id} data-customize-section={section.id}><h3>{section.label}</h3><ol>{section.cards.map((id,index)=>{const card=HOME_CARDS[id];return <li key={id}>
    <label><input type="checkbox" checked={!layout.hidden.includes(id)} onChange={()=>update({...layout,hidden:layout.hidden.includes(id)?layout.hidden.filter(value=>value!==id):[...layout.hidden,id]},`${card.title}已${layout.hidden.includes(id)?'顯示':'隱藏'}`)}/><span><strong>{card.title}</strong><small>{card.description}</small></span></label>
    <div><Button aria-label={`向上移動${card.title}`} disabled={index===0||id==='attention'||section.cards[index-1]==='attention'} onClick={()=>move(id,-1)}><ArrowUp size={16}/></Button><Button aria-label={`向下移動${card.title}`} disabled={index===section.cards.length-1||id==='attention'} onClick={()=>move(id,1)}><ArrowDown size={16}/></Button></div>
   </li>})}</ol></section>)}
  </section>}
  <span className="sr-only" role="status">{notice}</span>
  {refreshError&&<Message>{refreshError}</Message>}
  {!saved&&<Message>瀏覽器無法儲存設定；目前配置在離開此頁後可能重設。</Message>}
  {!availableVisible.length&&<div className="home-empty glass--flat"><h2>挑選今天需要的內容</h2><p>尚未顯示任何卡片。開啟「自訂首頁」加入工作、案件或團隊動向。</p><Button onClick={()=>setEditing(true)}>選擇首頁卡片</Button></div>}
  {attendanceUnavailable&&availableVisible.some(id=>['leave','trips','absence','impact'].includes(id))&&<p className="home-source-note" role="status">出勤資料尚未提供。 <a href="#view=people">查看人員與出勤</a></p>}
  <div className="home-sections">{view==='mine'?<>{missingMine&&<div className="home-view-notice" role="status">{assigned.error||confirmation.error||'個人工作來源尚未提供。'} <a href="#view=work">開啟我的工作</a></div>}<Sections view="mine" ids={contentIds.filter(id=>!missingMine||!['work','confirmation','deadlines'].includes(id))} render={renderCard}/></>:view==='assign'?<AssignView {...props}/>:<CompanyView {...props} reports={reports}/>}</div>
 </div></div>;
}
