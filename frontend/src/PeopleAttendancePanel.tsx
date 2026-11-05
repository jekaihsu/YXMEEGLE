import {createPortal} from 'react-dom';
import {DataState,Sheet,Button} from './design';
import {Select as FormSelect} from './design/Select';
import {Avatar} from './Avatar';
import {useLayoutEffect,useRef,useState} from 'react';
import {Search,RefreshCw} from 'lucide-react';
import {usePageOwner,usePageResource,ViewSkeleton} from './viewData';
import {fetchPeopleAttendance,taipeiWeek,attendanceValue,attendanceStatusLabel,parsePeopleAttendance} from './peopleAttendance';
import {WeeklyAttendanceTable} from './AttendanceWorkSchedules';
import {taipeiTime} from './taipeiTime';
import {ApiError} from './api';
import type {Context} from './Operations';
import './people-attendance.css';

export function PeopleAttendancePanel({c}:{c:Context&{reloadVersion?:number}}){
 const [filterOpen,setFilterOpen]=useState(false),[weekly,setWeekly]=useState(false),[selectedDay,setSelectedDay]=useState(new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'})),[limits,setLimits]=useState<Record<string,number>>({});
 const [week,setWeek]=useState(taipeiWeek),[weekChanged,setWeekChanged]=useState(false);
 const pendingReveal=useRef<HTMLElement|null>(null);
 const [revealAnnouncement,setRevealAnnouncement]=useState({id:0,text:''});
 useLayoutEffect(()=>{const section=pendingReveal.current;if(!section)return;pendingReveal.current=null;section.querySelector<HTMLElement>('h3')?.focus()},[limits]);
 const [query,setQuery]=useState('');
 const [group,setGroup]=useState('');
 const [employment,setEmployment]=useState('');
 const [tripKind,setTripKind]=useState('');
 const owner=usePageOwner({workspace:c.s.workspace_id||'',identityFingerprint:JSON.stringify([c.s.user?.id,c.s.user?.role,c.s.user?.authz_version,c.s.user?.capabilities]),openId:'people'});
 const [refreshId,setRefreshId]=useState(0),[queryReloadVersion,setQueryReloadVersion]=useState(c.reloadVersion??0);
 const result=usePageResource(owner,{endpoint:'/api/people/attendance',query:{week}},refreshId||(c.reloadVersion??0)!==queryReloadVersion?{reason:'explicit_refresh',id:`${c.reloadVersion??0}:${refreshId}`}:{reason:weekChanged?'user_query_change':'initial_open'},async(signal,current,intent)=>{
  let data;
  try{data=await fetchPeopleAttendance({week,signal,current,intent})}
  catch(error){if(error instanceof ApiError&&error.status===403)data=parsePeopleAttendance({status:'needs-permission'});else throw error}
  return {data,snapshotId:null,fetchedAt:data.as_of,verifiedAt:null,changedAt:null,completeness:data.status==='loading'?'unknown':data.incomplete?'partial':'complete',localRevision:null,empty:data.people.length===0&&!data.incomplete&&data.status!=='loading',stale:data.status==='stale'};
 });
 const value='value' in result?result.value:result.kind!=='Denied'&&'previous' in result?result.previous:undefined;
 const state={data:value?.data,loading:result.kind==='Loading',stale:result.kind==='Stale',error:'error' in result?String(result.error):'',reload:()=>setRefreshId(v=>v+1)};
 const view=state.data;
 const search=query.trim().toLocaleLowerCase();
 const groups=[...new Set(view?.people.flatMap(person=>person.group?[person.group]:[])??[])].sort();
 const people=(view?.people??[]).filter(person=>{
  const matchesSearch=!search||`${person.name??''} ${person.group??''}`.toLocaleLowerCase().includes(search);
  const matchesGroup=!group||(group==='unknown'?person.group===null:person.group===group.slice(6));
  const matchesEmployment=!employment||(employment==='unknown'?person.in_service===null:person.in_service===(employment==='active'));
  return matchesSearch&&matchesGroup&&matchesEmployment;
 });
 const visibleIds=new Set(people.map(person=>person.id));
 const visibleGroups=[...new Set(people.map(person=>person.group))];
 const trips=(view?.trips??[]).filter(trip=>visibleIds.has(trip.person_id)&&(!tripKind||trip.kind===tripKind));
 const filtered=!!(query||group||employment||tripKind);
 const reset=()=>{setQuery('');setGroup('');setEmployment('');setTripKind('')};
 const day=view?.days.includes(selectedDay)?selectedDay:view?.days[0]||week;
 const unavailable=result.kind==='Denied'||view&&['loading','needs-permission','not-connected','read-failed'].includes(view.status);
 return <section className="people-page page" aria-label="人員／資源與出勤" aria-busy={state.loading}>
  <header className="people-heading"><div><h1>人員／資源與出勤</h1><p id="people-description">台北時間週一至週日；空白代表待核對。</p></div>
   <button className="button" disabled={state.loading} onClick={state.reload}><RefreshCw size={16} aria-hidden="true"/>{state.loading?'讀取中…':'重新讀取'}</button>
  </header>
  <p className="people-data-time">資料時間 {taipeiTime(view?.as_of,'來源未提供')}</p>
  {(state.loading||state.stale||state.error||view?.status!=='ok'||view?.incomplete)&&<DataState kind={result.kind==='Denied'||view?.status==='needs-permission'?'Denied':state.error?(view?'Stale':'Error'):state.loading||view?.status==='loading'?'Loading':state.stale||view?.status==='stale'?'Stale':unavailable?'Error':'Partial'} title={result.kind==='Denied'||view?.status==='needs-permission'?'缺少唯讀權限':state.error?'暫時無法更新':state.loading?'正在讀取':state.stale&&view?.status==='ok'?'保留上次讀取資料':view?attendanceStatusLabel[view.status]:'準備讀取'} body={result.kind==='Denied'||view?.status==='needs-permission'?'目前無法讀取名冊，已清除先前資料。':state.error?(view?'更新失敗，保留同週上次成功資料。請重新讀取。':'尚未取得出勤資料。請重新讀取。'):state.stale&&view?.status==='ok'?'正在重新讀取，下方保留上次資料。':view?.incomplete?'部分名冊或打卡資料待核對，不代表未出勤。':'未知紀錄顯示待核對，未來日期不預判缺勤。'}/>}
  {!!view?.missing_scopes.length&&<p className="people-permissions" role="alert">缺少唯讀權限：{view.missing_scopes.join('、')}</p>}
  <section className="people-filterbar" aria-label="查找人員與週次">
   <div className="people-filters">
    <label className="people-search">搜尋人員或組別<div><Search size={17} aria-hidden="true"/><input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="輸入姓名或組別"/></div></label>
    <label>週日期<input type="date" aria-label="出勤週日期" value={week} onChange={event=>{if(event.target.value){const next=taipeiWeek(event.target.value);if(next!==week){setWeekChanged(true);setRefreshId(0);setQueryReloadVersion(c.reloadVersion??0)};setWeek(next);setGroup('')}}}/></label>
   </div>
   <Button onClick={e=>{e.currentTarget.focus();setFilterOpen(true)}}>更多篩選{group||employment?' · 已套用':''}</Button>{filterOpen&&createPortal(<Sheet title="人員篩選" onClose={()=>setFilterOpen(false)}><div className="people-filter-sheet">
    <div className="people-filters">
     <label>組別<FormSelect value={group} onChange={event=>setGroup(event.target.value)}><option value="">全部組別</option><option value="unknown">組別待核對</option>{groups.map(name=><option key={name} value={'group:'+name}>{name}</option>)}</FormSelect></label>
     <label>在職狀態<FormSelect value={employment} onChange={event=>setEmployment(event.target.value)}><option value="">全部狀態</option><option value="active">在職</option><option value="left">離職</option><option value="unknown">待核對</option></FormSelect></label>
    </div>
   <Button onClick={()=>setFilterOpen(false)}>套用篩選</Button></div></Sheet>,document.body)}
   {filtered&&<button className="people-text-button" onClick={reset}>清除篩選</button>}
  </section>
  <section className="people-surface" aria-labelledby="people-week-title">
   <div className="people-section-heading"><div><h2 id="people-week-title">每週出勤</h2><p>{view?.week_start||week}{view?.week_end&&` 至 ${view.week_end}`}{!!view?.people.length&&` · 已載入名冊 ${view.people.length} 筆${filtered?` · 符合篩選 ${people.length} 筆`:''}`}</p></div></div>
   <div className="people-legend" aria-label="出勤狀態說明"><span className="attendance-status attendance-ok">到班／免打卡</span><span className="attendance-status attendance-away">請假／出差／外出</span><span className="attendance-status attendance-attention">遲到／早退／缺卡</span><span className="attendance-status attendance-unknown">— 待核對</span></div>
   <div className="people-day-controls"><label>出勤日期<FormSelect value={day} onChange={e=>setSelectedDay(e.target.value)}>{(view?.days??[week]).map(d=><option key={d}>{d}</option>)}</FormSelect></label><Button aria-pressed={weekly} onClick={()=>setWeekly(v=>!v)}>{weekly?'返回當日名單':'每週總覽'}</Button></div>
   {state.loading&&!view&&<ViewSkeleton/>}
   {!unavailable&&visibleGroups.map(name=>{const members=people.filter(person=>person.group===name),key=name??'unknown',limit=limits[key]??25;return <div className="people-group" key={key}><h3 tabIndex={-1}>{name??'組別待核對'}<span>顯示 {Math.min(limit,members.length)} / {members.length} 筆</span></h3><div className={weekly?'people-week-view is-selected':'people-week-view'}><WeeklyAttendanceTable days={view?.days??[]} people={members.slice(0,limit)}/></div>{!weekly&&<ul className="people-day-list" aria-label={`${day} 出勤`}>{members.slice(0,limit).map(person=><li key={person.id}><div><strong>{person.name??'姓名待核對'}</strong><small>{person.in_service===null?'在職狀態待核對':person.in_service?'在職':'離職'}</small></div><span>{person.attendance[view?.days.indexOf(day)??0]??'待核對'}</span></li>)}</ul>}{limit<members.length&&<Button onClick={e=>{pendingReveal.current=limit+25>=members.length?e.currentTarget.closest('.people-group'):null;setLimits(v=>({...v,[key]:limit+25}));setRevealAnnouncement(a=>({id:a.id+1,text:`已顯示 ${Math.min(limit+25,members.length)} / ${members.length} 筆`}))}}>顯示更多（再 {Math.min(25,members.length-limit)} 筆）</Button>}</div>})}
   <p className="people-reveal-status sr-only" role="status" aria-atomic="true"><span key={revealAnnouncement.id}>{revealAnnouncement.text}</span></p>
   {!state.loading&&!people.length&&!unavailable&&<DataState kind={view?.incomplete?'Partial':'Empty'} title={view?.incomplete?'已讀取名冊尚無符合項目':filtered?'沒有符合篩選的人員':'尚無名冊紀錄'} body={view?.incomplete?'資料不完整，不能判定全部結果。':'請調整或清除篩選，或重新讀取。'}/>}
  </section>
  {!!view?.trips.length&&<section className="people-surface" aria-labelledby="people-trips-title">
   <div className="people-section-heading"><div><h2 id="people-trips-title">本週出差／外出</h2><p>符合人員篩選的已讀取紀錄，不代表完整申請母體。</p></div><label>紀錄類型<FormSelect value={tripKind} onChange={event=>setTripKind(event.target.value)}><option value="">全部類型</option><option value="trip">出差</option><option value="out">外出</option></FormSelect></label></div>
   {trips.length?<div className="people-table-scroll" role="region" aria-label="本週出差與外出紀錄，可左右捲動" tabIndex={0}><table className="data-table"><caption className="sr-only">本週出差與外出紀錄</caption><thead><tr>{['人員','組別','類型','起日','迄日'].map(title=><th scope="col" key={title}>{title}</th>)}</tr></thead><tbody>{trips.map((trip,index)=><tr key={`${trip.person_id}-${trip.kind}-${index}`}><th scope="row"><span className="person-cell"><Avatar small user={{name:trip.name??'未',avatar_url:view?.people.find(person=>person.id===trip.person_id)?.avatar_url}}/>{attendanceValue(trip.name)}</span></th><td>{attendanceValue(trip.group)}</td><td><span className="attendance-status attendance-away">{trip.kind==='trip'?'出差':'外出'}</span></td><td>{trip.start}</td><td>{trip.end}</td></tr>)}</tbody></table></div>:<p className="people-empty-note">{filtered?'目前篩選沒有出差／外出紀錄。':'目前快照沒有已讀取的出差／外出紀錄；不代表沒有申請。'}</p>}
  </section>}
 </section>;
}
