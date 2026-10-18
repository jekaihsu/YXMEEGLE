import type {ReactNode} from 'react';
import {ArrowUpRight} from 'lucide-react';
import {Row,Skeleton} from './design';
import {type Ctx,allTasks,active,STATUS} from './appCommon';
import {isHomeAssigned} from './executableTasks';
import type {HomePanel,HomeItem,PanelRead} from './useHomePanels';
import {attendanceStatusLabel,type PeopleAttendance} from './peopleAttendance';
import {HOME_CARDS,homeHref,type HomeCardId} from './homeLayout';
const PREVIEW_LIMIT=5;

export function Card({id,subtitle,children,href,action='查看全部'}:{id:HomeCardId;subtitle:string;children:ReactNode;href:string;action?:string}) {
 return <section className="home-card glass--flat" data-home-card={id} aria-labelledby={`home-${id}`}>
  <header><h2 id={`home-${id}`}>{HOME_CARDS[id].title}</h2><p>{subtitle}</p></header>
  <div className="home-card-content">{children}</div>
  <a className="home-card-more" href={href}>{action}<ArrowUpRight size={16} aria-hidden="true"/></a>
 </section>;
}
export function Message({children}:{children:ReactNode}){return <p className="home-message" role="status">{children}</p>}
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
export function WorkPreview({item,today}:{item:HomeItem;today:string}){
 const detail=[item.case.name||item.case.code||'案件關聯待核對',item.source_status||STATUS[item.status]||item.status,item.blocked_reasons[0]].filter(Boolean).join(' · ');
 return <Row label={item.title} detail={detail} value={<Deadline value={item.deadline||item.next_due} today={today}/>} href={item.target?homeHref(item.target):undefined}/>;
}
export function WorkCard({c,panel,id,today,read}:{c:Ctx;panel:HomePanel;id:HomeCardId;today:string;read:PanelRead}) {
 const body=read.body;
 const demo=c.s.mode==='demo'&&c.w.environment!=='production'&&(!body||body.readState==='disabled');
 const legacy=panel==='assigned'?allTasks(c.w).filter(r=>active(r.t)&&isHomeAssigned(r.t,c.w,c.s.user?.id||'')).sort((a,b)=>(a.t.due_date||'9999').localeCompare(b.t.due_date||'9999')).slice(0,PREVIEW_LIMIT):[];
 const queue=panel==='confirmation'?c.w.home_queues?.awaiting_confirmation:panel==='delegated'?c.w.home_queues?.delegated_by_me:undefined;
 return <Card id={id}  subtitle={panel==='assigned'?'依期限排序，先處理最緊急的工作':panel==='delegated'?'你交辦給他人的工作與目前進度':'需要你覆核或確認的事項'} href={homeHref({view:'work',tab:demo&&panel==='assigned'?'legacy':panel})}>
  {read.pending&&!body&&!demo?<Skeleton lines={3}/>:null}
  {demo?<>
   {legacy.map(r=><Row key={r.t.id} href={homeHref({view:'project',project:r.p.id,node:r.n.id,task:r.t.id,tab:'flow'})} label={r.t.title} detail={`${r.p.name} · ${STATUS[r.t.status]||r.t.status}`} value={<Deadline value={r.t.due_date} today={today}/>}/>)}
   {queue?.slice(0,PREVIEW_LIMIT).map(item=><Row key={item.id} label={item.title} detail={item.reason} href={item.project_id?homeHref({view:'project',project:item.project_id,node:item.node_id||undefined,task:item.task_id||undefined,tab:item.tab||'flow'}):undefined}/>)}
   {!legacy.length&&!queue?.length&&<Message>{panel==='assigned'?'目前資料中沒有指派給你的工作。':'示範資料中尚未提供待確認事項。'}</Message>}
  </>:<>
   {body?.items.slice(0,PREVIEW_LIMIT).map(item=><WorkPreview key={item.id} item={item} today={today}/>)}
   {read.error&&<Message>工作來源更新失敗{body?.items.length?'，以下保留上次資料。':'，請稍後重新讀取。'}</Message>}
   {body&&!body.items.length&&<Message>{body.readState==='disabled'?'目前無法讀取這類工作。':body.complete?'目前沒有待處理的事項。':'工作清單尚未更新完成，請稍後重新讀取。'}</Message>}
   {body&&(!body.complete||body.freshness.status==='stale')&&<p className="home-source-note">{body.freshness.status==='stale'?'上次快照 · ':''}資料尚未完整；預覽不代表完整清單。</p>}
  </>}
 </Card>;
}
export function AttendanceCard({id,view,loading,error,today}:{id:'leave'|'trips';view?:PeopleAttendance;loading:boolean;error:string;today:string}) {
 const unavailable=error||!view||!['ok','incomplete','stale'].includes(view.status);
 const dayIndex=view?.days.indexOf(today)??-1;
 const records=id==='trips'?(view?.trips||[]).filter(item=>item.kind==='trip'&&item.start<=today&&item.end>=today):
  (view?.leaves||[]).filter(item=>item.start<=today&&item.end>=today);
 const namedLeaveFallback=id==='leave'&&!view?.leaves_available&&dayIndex>=0?(view?.people||[]).filter(person=>!records.some(record=>record.person_id===person.id)&&person.attendance[dayIndex]?.split('、').includes('請假')):[];
 const known=id==='trips'?view?.summary.on_trip!==null:view?.leaves_available===true;
 const note=id==='leave'?'請假':'出差';
 return <Card id={id}  subtitle="今天的人員狀態" href="#view=people" action="查看人員與出勤">
  {loading&&!view?<Skeleton lines={3}/>:unavailable?<Message>{error?'出勤資料讀取失敗，請重新讀取。':view?attendanceStatusLabel[view.status]:'出勤資料尚未提供。'}</Message>:<>
   {records.slice(0,PREVIEW_LIMIT).map((item,index)=><Row key={`${item.person_id}-${index}`} href="#view=people" label={item.name||'姓名待核對'} detail={`${item.group||'組別待核對'} · ${item.start.replaceAll('-','/')} 至 ${item.end.replaceAll('-','/')}`}/>)}
   {namedLeaveFallback.slice(0,Math.max(0,PREVIEW_LIMIT-records.length)).map(person=><Row key={person.id} href="#view=people" label={person.name||'姓名待核對'} detail={`${person.group||'組別待核對'} · 今日出勤紀錄：請假`}/>)}
   {!records.length&&!namedLeaveFallback.length&&<Message>{known&&view?.status==='ok'?`今日沒有已核實的${note}紀錄。`:`今日${note}名單尚待核對；目前沒有可確認的紀錄。`}</Message>}
   {records.length+namedLeaveFallback.length>PREVIEW_LIMIT&&<p className="home-source-note">另有 {records.length+namedLeaveFallback.length-PREVIEW_LIMIT} 筆，請開啟人員與出勤。</p>}
   {(view?.incomplete||view?.status==='stale'||loading||error)&&<p className="home-source-note">{view?.status==='stale'?'舊快照；':error?'更新失敗；':''}資料尚未完整或仍在更新，名單可能不完整。</p>}
  </>}
 </Card>;
}
