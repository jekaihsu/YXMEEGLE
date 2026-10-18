import {useEffect,useState,type ReactNode} from 'react';
import {ArrowDown,ArrowUp,CalendarDays,Check,Settings2,RotateCcw,RefreshCw} from 'lucide-react';
import {Button,Page} from './design';
import {type Ctx,date} from './appCommon';
import {useHomePanels,type PanelRead} from './useHomePanels';
import {fetchPeopleAttendance,parsePeopleAttendance,taipeiWeek,type PeopleAttendance} from './peopleAttendance';
import {useViewData} from './viewData';
import {ApiError} from './api';
import {HOME_CARDS,HOME_VIEWS,availableViews,resolvePersona,defaultHomeLayout,parseHomeLayout,moveHomeCard,homeLayoutKey,taipeiToday,type HomeCardId,type HomeLayout,type HomeSettings,type HomeViewId} from './homeLayout';
import {AttendanceCard,Message} from './homeCards';
import {HomeHelp} from './homeHelp';
import {MineCard} from './homeViews/MineCards';
import {AssignCard,useAssignData} from './homeViews/AssignCards';
import {CompanyCard} from './homeViews/CompanyCards';
import {useHomeCompany} from './useHomeCompany';
import './UnifiedHome.css';

type ViewProps={ids:HomeCardId[];c:Ctx;today:string;assigned:PanelRead;confirmation:PanelRead;attendance:(id:'leave'|'trips')=>ReactNode;attendanceData?:PeopleAttendance};
function AssignView(props:ViewProps){
 const data=useAssignData(props.c);
 return <>{props.ids.map(id=>id==='leave'||id==='trips'?props.attendance(id):<AssignCard key={id} id={id} {...props} {...data}/> )}</>;
}
function CompanyView(props:ViewProps){
 const read=useHomeCompany(props.c);
 return <>{props.ids.map(id=>id==='leave'||id==='trips'?props.attendance(id):<CompanyCard key={id} id={id} {...props} read={read}/> )}</>;
}
export function UnifiedHome({c}:{c:Ctx}){
 const key=homeLayoutKey(c.s.workspace_id||c.w.workspace_id||'default',c.s.user?.id||'anonymous',c.s.user?.role||'',c.s.mode);
 return <HomeWorkspace key={key} c={c} storageKey={key}/>;
}
function HomeWorkspace({c,storageKey}:{c:Ctx;storageKey:string}){
 const [settings,setSettings]=useState<HomeSettings>(()=>{try{return parseHomeLayout(localStorage.getItem(storageKey))}catch{return parseHomeLayout(null)}});
 const [editing,setEditing]=useState(false),[saved,setSaved]=useState(true),[notice,setNotice]=useState('');
 const [today,setToday]=useState(taipeiToday);
 const [refreshing,setRefreshing]=useState(false),[refreshTick,setRefreshTick]=useState(0),[refreshError,setRefreshError]=useState('');
 const homeContext={...c,reloadVersion:(c.reloadVersion||0)+refreshTick};
 const assigned=useHomePanels(homeContext,{panel:'assigned',scope:'mine',limit:100});
 const confirmation=useHomePanels(homeContext,{panel:'confirmation',scope:'mine',limit:100});
 const manager=assigned.body?.manager_view_available??null;
 const views=availableViews(c.s.user,manager);
 const view=settings.view&&views.includes(settings.view)?settings.view:assigned.pending&&!assigned.body?'mine':resolvePersona(c.s.user,manager);
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
 const choose=(next:HomeViewId)=>persist({...settings,view:next},`已切換至${HOME_VIEWS[next].label}`);
 const visible=layout.order.filter(id=>!layout.hidden.includes(id));
 const asOf=c.w.as_of;
 const freshnessDays=asOf?Math.floor((Date.parse(`${taipeiToday()}T00:00:00Z`)-Date.parse(`${asOf.slice(0,10)}T00:00:00Z`))/86400000):null;
 const stale=freshnessDays!==null&&freshnessDays>1;
 const attendanceCard=(id:'leave'|'trips')=><AttendanceCard key={id} id={id} view={attendance.data} loading={attendance.loading} error={attendance.error} today={today}/>;
 const props:ViewProps={ids:visible,c:homeContext,today,assigned,confirmation,attendance:attendanceCard,attendanceData:attendance.data};
 const renderCard=(id:HomeCardId)=>id==='leave'||id==='trips'?attendanceCard(id):<MineCard key={id} id={id} {...props}/>;
 return <div className="unified-home" data-home-view={view}><Page title="今日工作台" eyebrow={today.replaceAll('-','/')+' · '+(c.s.user?.name||'我的工作空間')} subtitle={HOME_VIEWS[view].label+'，掌握今天需要處理的事。'} actions={<>
  <Button disabled={refreshing||c.busy} onClick={()=>void refresh()}><RefreshCw size={16}/>{refreshing?'讀取中…':'重新讀取'}</Button>
  <Button onClick={()=>c.go({view:'schedule'})}><CalendarDays size={16}/>查看排程</Button>
  {views.length>1&&<div className="home-view-switcher" role="group" aria-label="首頁視圖">{views.map(id=><Button key={id} aria-pressed={view===id} onClick={()=>choose(id)}>{HOME_VIEWS[id].label}</Button>)}</div>}
  <Button variant="plain" aria-expanded={editing} aria-controls="home-customize" onClick={()=>setEditing(value=>!value)}>{editing?<Check size={16}/>:<Settings2 size={16}/>} {editing?'完成設定':'自訂首頁'}</Button>
  <HomeHelp view={view}/>
 </>}>
  {editing&&<section className="home-customize glass--flat" id="home-customize" aria-label="自訂首頁卡片">
   <header><div><h2>安排你的首頁 · {HOME_VIEWS[view].label}</h2><p>顯示、隱藏與排序目前視圖的卡片。設定依登入身分與視圖儲存在此瀏覽器。</p></div><Button onClick={()=>update(defaultHomeLayout(view),'已還原目前視圖的建議配置')}><RotateCcw size={15}/>還原建議配置</Button></header>
   <ol>{layout.order.map((id,index)=>{const card=HOME_CARDS[id];return <li key={id}>
    <label><input type="checkbox" checked={!layout.hidden.includes(id)} onChange={()=>update({...layout,hidden:layout.hidden.includes(id)?layout.hidden.filter(value=>value!==id):[...layout.hidden,id]},`${card.title}已${layout.hidden.includes(id)?'顯示':'隱藏'}`)}/><span><strong>{card.title}</strong><small>{card.description}</small></span></label>
    <div><Button aria-label={`向上移動${card.title}`} disabled={index===0} onClick={()=>update(moveHomeCard(layout,id,-1),`${card.title}已向上移動`)}><ArrowUp size={16}/></Button><Button aria-label={`向下移動${card.title}`} disabled={index===layout.order.length-1} onClick={()=>update(moveHomeCard(layout,id,1),`${card.title}已向下移動`)}><ArrowDown size={16}/></Button></div>
   </li>})}</ol>
  </section>}
  <span className="sr-only" role="status">{notice}</span>
  {asOf&&<p className={`home-freshness${stale?' is-stale':''}`} role="status">資料截至 {date(asOf)}{stale?' · 可能已過期':''}</p>}
  {refreshError&&<Message>{refreshError}</Message>}
  {!saved&&<Message>瀏覽器無法儲存設定；目前配置在離開此頁後可能重設。</Message>}
  {!visible.length&&<div className="home-empty glass--flat"><h2>挑選今天需要的內容</h2><p>尚未顯示任何卡片。開啟「自訂首頁」加入工作、案件或團隊動向。</p><Button onClick={()=>setEditing(true)}>選擇首頁卡片</Button></div>}
  <div className="home-card-grid">{view==='mine'?visible.map(renderCard):view==='assign'?<AssignView {...props}/>:<CompanyView {...props}/>}</div>
 </Page></div>;
}
