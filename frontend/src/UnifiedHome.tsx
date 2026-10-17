import {useEffect,useState,type ReactNode} from 'react';
import {ArrowDown,ArrowUp,ArrowUpRight,CalendarDays,Check,Settings2,RotateCcw,RefreshCw} from 'lucide-react';
import {Button,Page,Row,Skeleton} from './design';
import {type Ctx,allTasks,active,date,nameOf,STATUS} from './appCommon';
import {isHomeAssigned} from './executableTasks';
import {useHomePanels,type HomePanel,type HomeItem} from './useHomePanels';
import {fetchPeopleAttendance,parsePeopleAttendance,taipeiWeek,attendanceStatusLabel,type PeopleAttendance} from './peopleAttendance';
import {useViewData} from './viewData';
import {ApiError} from './api';
import {HOME_CARDS,defaultHomeLayout,parseHomeLayout,moveHomeCard,homeLayoutKey,homeHref,taipeiToday,type HomeCardId,type HomeLayout} from './homeLayout';
import './UnifiedHome.css';

const PREVIEW_LIMIT=3;
const titles=Object.fromEntries(HOME_CARDS.map(card=>[card.id,card.title]));
function Card({id,subtitle,children,href,action='查看全部',title,priority=false}:{id:HomeCardId;subtitle:string;children:ReactNode;href:string;action?:string;title?:string;priority?:boolean}) {
 return <section className="home-card glass--flat" data-home-card={id} data-priority={priority||undefined} aria-labelledby={`home-${id}`}>
  <header><h2 id={`home-${id}`}>{title||titles[id]}</h2><p>{subtitle}</p></header>
  <div className="home-card-content">{children}</div>
  <a className="home-card-more" href={href}>{action}<ArrowUpRight size={16} aria-hidden="true"/></a>
 </section>;
}
function Message({children}:{children:ReactNode}){return <p className="home-message" role="status">{children}</p>}
function dueText(deadline:string|null|undefined,today:string){
 if(!deadline)return '期限待確認';
 const due=deadline.slice(0,10),days=Math.round((Date.parse(`${due}T00:00:00Z`)-Date.parse(`${today}T00:00:00Z`))/86400000);
 if(days<0)return `已逾期 ${Math.abs(days)} 天`;
 if(days===0)return '今天到期';
 if(days===1)return '明天到期';
 return due.replaceAll('-','/');
}
function Deadline({value,today}:{value:string|null|undefined;today:string}){
 const label=dueText(value,today),tone=label.startsWith('已逾期')?'critical':label==='今天到期'?'warning':label==='明天到期'?'warning':'neutral';
 return <span className="home-deadline" data-tone={tone}>{label}</span>;
}
function WorkPreview({item,today}:{item:HomeItem;today:string}){
 const detail=[item.case.name||item.case.code||'案件關聯待核對',item.source_status||STATUS[item.status]||item.status,item.blocked_reasons[0]].filter(Boolean).join(' · ');
 return <Row label={item.title} detail={detail} value={<Deadline value={item.deadline||item.next_due} today={today}/>} href={item.target?homeHref(item.target):undefined}/>;
}
function WorkCard({c,panel,id,today,priority}:{c:Ctx;panel:HomePanel;id:HomeCardId;today:string;priority:boolean}) {
 const read=useHomePanels(c,{panel,scope:'mine',limit:PREVIEW_LIMIT});
 const body=read.body;
 const demo=c.s.mode==='demo'&&c.w.environment!=='production'&&(!body||body.readState==='disabled');
 const legacy=panel==='assigned'?allTasks(c.w).filter(r=>active(r.t)&&isHomeAssigned(r.t,c.w,c.s.user?.id||'')).sort((a,b)=>(a.t.due_date||'9999').localeCompare(b.t.due_date||'9999')).slice(0,PREVIEW_LIMIT):[];
 const queue=panel==='confirmation'?c.w.home_queues?.awaiting_confirmation:panel==='delegated'?c.w.home_queues?.delegated_by_me:undefined;
 return <Card id={id} title={priority?'優先處理':undefined} priority={priority} subtitle={panel==='assigned'?'依期限排序，先處理最緊急的工作':'需要你覆核或確認的事項'} href={homeHref({view:'work',tab:demo&&panel==='assigned'?'legacy':panel})}>
  {read.pending&&!body&&!demo?<Skeleton lines={3}/>:null}
  {demo?<>
   {legacy.map(r=><Row key={r.t.id} href={homeHref({view:'project',project:r.p.id,node:r.n.id,task:r.t.id,tab:'flow'})} label={r.t.title} detail={`${r.p.name} · ${STATUS[r.t.status]||r.t.status}`} value={<Deadline value={r.t.due_date} today={today}/>}/>)}
   {queue?.slice(0,PREVIEW_LIMIT).map(item=><Row key={item.id} label={item.title} detail={item.reason} href={item.project_id?homeHref({view:'project',project:item.project_id,node:item.node_id||undefined,task:item.task_id||undefined,tab:item.tab||'flow'}):undefined}/>)}
   {!legacy.length&&!queue?.length&&<Message>{panel==='assigned'?'目前資料中沒有指派給你的工作。':'示範資料中尚未提供待確認事項。'}</Message>}
  </>:<>
   {body?.items.slice(0,PREVIEW_LIMIT).map(item=><WorkPreview key={item.id} item={item} today={today}/>)}
   {read.error&&<Message>工作來源更新失敗{body?.items.length?'，以下保留上次資料。':'，請稍後重新讀取。'}</Message>}
   {body&&!body.items.length&&<Message>{body.readState==='disabled'?'目前無法讀取這類工作。':body.complete?'目前沒有待處理的事項。':'工作清單尚未更新完成，請稍後重新讀取。'}</Message>}
   {body&&(!body.complete||body.freshness.status==='stale')&&<p className="home-source-note">{body.freshness.status==='stale'?'上次快照 · ':''}來源尚待更新或核對；預覽不代表完整清單。</p>}
  </>}
 </Card>;
}
function CasesCard({c,today,priority=false}:{c:Ctx;today:string;priority?:boolean}) {
 const cases=c.w.projects.filter(p=>p.case_type!=='intake'&&!['completed','superseded'].includes(p.execution_status||p.status)).sort((a,b)=>(a.due_date||'9999').localeCompare(b.due_date||'9999'));
 return <Card id="cases" title={priority?'優先處理':undefined} priority={priority} subtitle="近期需要留意的進行中案件" href="#view=projects" action="查看案件總覽">
  {cases.slice(0,PREVIEW_LIMIT).map(p=><Row key={p.id} href={homeHref({view:'project',project:p.id})} label={p.name} detail={`${p.code} · ${nameOf(c.w,p.pm_id)}`} value={<Deadline value={p.due_date} today={today}/>}/>)}
  {!cases.length&&<Message>目前載入範圍內沒有進行中的正式案件。</Message>}
 </Card>;
}
function AttendanceCard({id,view,loading,error,today,priority=false}:{id:'leave'|'trips';view?:PeopleAttendance;loading:boolean;error:string;today:string;priority?:boolean}) {
 const unavailable=error||!view||!['ok','incomplete','stale'].includes(view.status);
 const dayIndex=view?.days.indexOf(today)??-1;
 const records=id==='trips'?(view?.trips||[]).filter(item=>item.kind==='trip'&&item.start<=today&&item.end>=today):
  (view?.leaves||[]).filter(item=>item.start<=today&&item.end>=today);
 const namedLeaveFallback=id==='leave'&&!view?.leaves_available&&dayIndex>=0?(view?.people||[]).filter(person=>!records.some(record=>record.person_id===person.id)&&person.attendance[dayIndex]?.split('、').includes('請假')):[];
 const known=id==='trips'?view?.summary.on_trip!==null:view?.leaves_available===true;
 const note=id==='leave'?'請假':'出差';
 return <Card id={id} title={priority?'優先處理':undefined} priority={priority} subtitle="今天的人員狀態" href="#view=people" action="查看人員與出勤">
  {loading&&!view?<Skeleton lines={3}/>:unavailable?<Message>{error?'出勤資料讀取失敗，請重新讀取。':view?attendanceStatusLabel[view.status]:'出勤資料尚未提供。'}</Message>:<>
   {records.slice(0,PREVIEW_LIMIT).map((item,index)=><Row key={`${item.person_id}-${index}`} href="#view=people" label={item.name||'姓名待核對'} detail={`${item.group||'組別待核對'} · ${item.start.replaceAll('-','/')} 至 ${item.end.replaceAll('-','/')}`}/>)}
   {namedLeaveFallback.slice(0,PREVIEW_LIMIT).map(person=><Row key={person.id} href="#view=people" label={person.name||'姓名待核對'} detail={`${person.group||'組別待核對'} · 今日出勤紀錄：請假`}/>)}
   {!records.length&&!namedLeaveFallback.length&&<Message>{known&&view?.status==='ok'?`今日沒有已核實的${note}紀錄。`:`今日${note}名單尚待核對；目前沒有可確認的紀錄。`}</Message>}
   {records.length>PREVIEW_LIMIT&&<p className="home-source-note">另有 {records.length-PREVIEW_LIMIT} 筆，請開啟人員與出勤。</p>}
   {(view?.incomplete||view?.status==='stale'||loading||error)&&<p className="home-source-note">{view?.status==='stale'?'舊快照；':error?'更新失敗；':''}資料尚未完整或仍在更新，名單可能不完整。</p>}
  </>}
 </Card>;
}
export function UnifiedHome({c}:{c:Ctx}) {
 const key=homeLayoutKey(c.s.workspace_id||c.w.workspace_id||'default',c.s.user?.id||'anonymous',c.s.user?.role||'',c.s.mode);
 return <HomeWorkspace key={key} c={c} storageKey={key}/>;
}
function HomeWorkspace({c,storageKey}:{c:Ctx;storageKey:string}) {
 const role=c.s.user?.role;
 const [layout,setLayout]=useState<HomeLayout>(()=>{try{return parseHomeLayout(localStorage.getItem(storageKey),role)}catch{return defaultHomeLayout(role)}});
 const [editing,setEditing]=useState(false),[saved,setSaved]=useState(true),[notice,setNotice]=useState('');
 const [today,setToday]=useState(taipeiToday);
 const [refreshing,setRefreshing]=useState(false),[refreshTick,setRefreshTick]=useState(0),[refreshError,setRefreshError]=useState('');
 const homeContext={...c,reloadVersion:(c.reloadVersion||0)+refreshTick};
 const refresh=async()=>{setRefreshing(true);setRefreshError('');try{await c.refresh()}catch{setRefreshError('工作區重新讀取失敗；已保留上次資料，請稍後再試。')}finally{setRefreshTick(value=>value+1);setRefreshing(false)}};
 useEffect(()=>{const timer=window.setInterval(()=>setToday(taipeiToday()),60000);return()=>window.clearInterval(timer)},[]);
 const attendance=useViewData(`home-attendance:${storageKey}:${taipeiWeek(today)}`,async(signal,current)=>{
  try{return await fetchPeopleAttendance({week:taipeiWeek(today),signal,current})}
  catch(error){if(error instanceof ApiError&&error.status===403)return parsePeopleAttendance({status:'needs-permission'});throw error}
 },[c.reloadVersion,c.w.version,today,refreshTick]);
 const update=(next:HomeLayout,message:string)=>{
  setLayout(next);setNotice(message);
  try{localStorage.setItem(storageKey,JSON.stringify({version:1,...next}));setSaved(true)}catch{setSaved(false)}
 };
 const visible=layout.order.filter(id=>!layout.hidden.includes(id));
 const asOf=c.w.as_of;
 const freshnessDays=asOf?Math.floor((Date.parse(`${taipeiToday()}T00:00:00Z`)-Date.parse(`${asOf.slice(0,10)}T00:00:00Z`))/86400000):null;
 const stale=freshnessDays!==null&&freshnessDays>1;
 const orderedVisible:HomeCardId[]=visible.includes('work')?['work',...visible.filter(id=>id!=='work')]:visible;
 return <div className="unified-home"><Page title="今日工作台" eyebrow={today.replaceAll('-','/')+' · '+(c.s.user?.name||'我的工作空間')} subtitle="你的工作、待確認事項與團隊動向，放在同一處。" actions={<>
  <Button disabled={refreshing||c.busy} onClick={()=>void refresh()}><RefreshCw size={16}/>{refreshing?'讀取中…':'重新讀取'}</Button>
  <Button onClick={()=>c.go({view:'schedule'})}><CalendarDays size={16}/>查看排程</Button>
  <Button variant="plain" aria-expanded={editing} aria-controls="home-customize" onClick={()=>setEditing(value=>!value)}>{editing?<Check size={16}/>:<Settings2 size={16}/>} {editing?'完成設定':'自訂首頁'}</Button>
 </>}>
  {editing&&<section className="home-customize glass--flat" id="home-customize" aria-label="自訂首頁卡片">
   <header><div><h2>安排你的首頁</h2><p>優先處理固定顯示在最前方；其他內容可上下調整順序。設定儲存在此瀏覽器，依登入身分分開。</p></div><Button onClick={()=>update(defaultHomeLayout(role),'已還原建議配置')}><RotateCcw size={15}/>還原建議配置</Button></header>
   <ol>{layout.order.map((id,index)=>{const card=HOME_CARDS.find(card=>card.id===id)!;return <li key={id}>
    <label><input type="checkbox" checked={!layout.hidden.includes(id)} onChange={()=>update({...layout,hidden:layout.hidden.includes(id)?layout.hidden.filter(value=>value!==id):[...layout.hidden,id]},`${card.title}已${layout.hidden.includes(id)?'顯示':'隱藏'}`)}/><span><strong>{card.title}</strong><small>{card.description}</small></span></label>
    <div><Button aria-label={`向上移動${card.title}`} disabled={id==='work'||index===0} onClick={()=>update(moveHomeCard(layout,id,-1),`${card.title}已向上移動`)}><ArrowUp size={16}/></Button><Button aria-label={`向下移動${card.title}`} disabled={id==='work'||index===layout.order.length-1} onClick={()=>update(moveHomeCard(layout,id,1),`${card.title}已向下移動`)}><ArrowDown size={16}/></Button></div>
   </li>})}</ol>
  </section>}
  <span className="sr-only" role="status">{notice}</span>
  {asOf&&<p className={`home-freshness${stale?' is-stale':''}`} role="status">資料截至 {date(asOf)}{stale?' · 可能已過期':''}</p>}
  {refreshError&&<Message>{refreshError}</Message>}
  {!saved&&<Message>瀏覽器無法儲存設定；目前配置在離開此頁後可能重設。</Message>}
  {!visible.length&&<div className="home-empty glass--flat"><h2>挑選今天需要的內容</h2><p>尚未顯示任何卡片。開啟「自訂首頁」加入工作、案件或團隊動向。</p><Button onClick={()=>setEditing(true)}>選擇首頁卡片</Button></div>}
  <div className="home-card-grid">{orderedVisible.map((id,index)=>id==='cases'?<CasesCard key={id} c={c} today={today} priority={index===0}/>:id==='leave'||id==='trips'?<AttendanceCard key={id} id={id} view={attendance.data} loading={attendance.loading} error={attendance.error} today={today} priority={index===0}/>:<WorkCard key={id} id={id} panel={id==='work'?'assigned':id as HomePanel} c={homeContext} today={today} priority={index===0}/>)}</div>
 </Page></div>;
}
