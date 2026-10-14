import {useState} from 'react';
import {Search,RefreshCw,Users,Plane,SlidersHorizontal} from 'lucide-react';
import {useViewData,ViewSkeleton} from './viewData';
import {fetchPeopleAttendance,taipeiWeek,attendanceValue,attendanceStatusLabel,parsePeopleAttendance} from './peopleAttendance';
import {WeeklyAttendanceTable} from './AttendanceWorkSchedules';
import {taipeiTime} from './taipeiTime';
import {ApiError} from './api';
import type {Context} from './Operations';
import './people-attendance.css';

export function PeopleAttendancePanel({c}:{c:Context&{reloadVersion?:number}}){
 const [week,setWeek]=useState(taipeiWeek);
 const [query,setQuery]=useState('');
 const [group,setGroup]=useState('');
 const [employment,setEmployment]=useState('');
 const [tripKind,setTripKind]=useState('');
 const state=useViewData(`people-attendance:${c.s.user?.id}:${week}`,async(signal,current)=>{
  try{return await fetchPeopleAttendance({week,signal,current})}
  catch(error){
   if(error instanceof ApiError&&error.status===403)return parsePeopleAttendance({status:'needs-permission'});
   throw error;
  }
 },[c.reloadVersion]);
 const view=state.data;
 const hasSnapshot=!!view?.as_of&&['ok','incomplete','stale'].includes(view.status);
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
 const tone=state.error||view?.status==='read-failed'||view?.status==='needs-permission'?'error':view?.incomplete||view?.status==='stale'?'warning':view?.status==='ok'?'success':'neutral';
 return <section className="people-page page" aria-label="人員／資源與出勤" aria-busy={state.loading}>
  <header className="people-heading"><div><p className="people-eyebrow">人員與資源</p><h1>人員／資源與出勤</h1><p id="people-description">台北時間週一至週日的名冊、出勤與出差紀錄。空白代表待核對，不代表未出勤。</p></div>
   <button className="button" disabled={state.loading} onClick={state.reload}><RefreshCw size={16} aria-hidden="true"/>{state.loading?'讀取中…':'重新讀取'}</button>
  </header>
  <div className={`people-status people-status-${tone}`} role={state.error?'alert':'status'}>
   <span className="people-status-dot" aria-hidden="true"/><div><strong>{state.error?'暫時無法更新':state.loading?'正在讀取':view?attendanceStatusLabel[view.status]:'準備讀取'}</strong>
    <p>{state.error?`保留上次快照。${state.error}`:state.loading&&view?'保留上次快照，讀取完成後更新。':view?.refreshing?'來源正在背景更新。需要查看最新結果時，請按重新讀取。':'僅在進入頁面、切換週次或按重新讀取時更新。'}<span>資料時間 {taipeiTime(view?.as_of,'尚無成功快照')}</span></p></div>
  </div>
  {!!view?.missing_scopes.length&&<p className="people-permissions" role="alert">缺少唯讀權限：{view.missing_scopes.join('、')}</p>}
  <div className="people-summary" aria-label="已讀取快照摘要">
   <div><Users size={19} aria-hidden="true"/><span>已讀取名冊紀錄</span><strong>{hasSnapshot?view?.people.length:'—'}</strong><small>已載入紀錄，非全公司在職人數</small></div>
   <div><SlidersHorizontal size={19} aria-hidden="true"/><span>符合目前篩選</span><strong>{hasSnapshot?people.length:'—'}</strong><small>依姓名、組別與在職狀態篩選</small></div>
   <div><Plane size={19} aria-hidden="true"/><span>本週出差／外出紀錄</span><strong>{hasSnapshot?view?.trips.length:'—'}</strong><small>已讀取紀錄，非出差人數</small></div>
  </div>
  <section className="people-surface" aria-labelledby="people-filter-title">
   <div className="people-section-heading"><div><h2 id="people-filter-title">查找人員與週次</h2><p>搜尋與篩選只整理目前已讀取的紀錄。</p></div>{filtered&&<button className="people-text-button" onClick={reset}>清除篩選</button>}</div>
   <div className="people-filters">
    <label className="people-search">搜尋人員或組別<div><Search size={17} aria-hidden="true"/><input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="輸入姓名或組別"/></div></label>
    <label>週日期<input type="date" aria-label="出勤週日期" value={week} onChange={event=>{if(event.target.value){setWeek(taipeiWeek(event.target.value));setGroup('')}}}/></label>
    <label>組別<select value={group} onChange={event=>setGroup(event.target.value)}><option value="">全部組別</option><option value="unknown">組別待核對</option>{groups.map(name=><option key={name} value={'group:'+name}>{name}</option>)}</select></label>
    <label>在職狀態<select value={employment} onChange={event=>setEmployment(event.target.value)}><option value="">全部狀態</option><option value="active">在職</option><option value="left">離職</option><option value="unknown">待核對</option></select></label>
   </div>
  </section>
  <section className="people-surface" aria-labelledby="people-week-title">
   <div className="people-section-heading"><div><h2 id="people-week-title">每週出勤</h2><p>{view?.week_start??week} 至 {view?.week_end??'—'}{view&&` · 顯示 ${people.length} / ${view.people.length} 筆已讀取名冊紀錄`}</p></div></div>
   <div className="people-legend" aria-label="出勤狀態說明"><span className="attendance-status attendance-ok">到班／免打卡</span><span className="attendance-status attendance-away">請假／出差／外出</span><span className="attendance-status attendance-attention">遲到／早退／缺卡</span><span className="attendance-status attendance-unknown">— 待核對</span></div>
   {view?.incomplete&&<p className="people-notice">部分識別、組別或打卡證據待核對。請假 {attendanceValue(state.error?null:view.summary.on_leave)} 人、出差 {attendanceValue(state.error?null:view.summary.on_trip)} 人；不推算應到人日或出勤率。</p>}
   {state.loading&&!view&&<ViewSkeleton/>}
   {visibleGroups.map(name=><div className="people-group" key={name??'unknown'}><h3>{name??'組別待核對'}<span>{people.filter(person=>person.group===name).length} 筆</span></h3><WeeklyAttendanceTable days={view?.days??[]} people={people.filter(person=>person.group===name)}/></div>)}
   {!state.loading&&!people.length&&<div className="people-empty"><Users size={25} aria-hidden="true"/><strong>{filtered?'沒有符合篩選的人員':'尚無可顯示的名冊紀錄'}</strong><p>{filtered?'試試其他姓名或清除篩選。':'請查看上方讀取狀態，再按重新讀取。'}</p>{filtered&&<button className="button" onClick={reset}>清除篩選</button>}</div>}
  </section>
  <section className="people-surface" aria-labelledby="people-trips-title">
   <div className="people-section-heading"><div><h2 id="people-trips-title">本週出差／外出</h2><p>符合人員篩選的已讀取紀錄，不代表完整申請母體。</p></div><label>紀錄類型<select value={tripKind} onChange={event=>setTripKind(event.target.value)}><option value="">全部類型</option><option value="trip">出差</option><option value="out">外出</option></select></label></div>
   {trips.length?<div className="people-table-scroll" role="region" aria-label="本週出差與外出紀錄，可左右捲動" tabIndex={0}><table className="data-table"><caption className="sr-only">本週出差與外出紀錄</caption><thead><tr>{['人員','組別','類型','起日','迄日'].map(title=><th scope="col" key={title}>{title}</th>)}</tr></thead><tbody>{trips.map((trip,index)=><tr key={`${trip.person_id}-${trip.kind}-${index}`}><th scope="row">{attendanceValue(trip.name)}</th><td>{attendanceValue(trip.group)}</td><td><span className="attendance-status attendance-away">{trip.kind==='trip'?'出差':'外出'}</span></td><td>{trip.start}</td><td>{trip.end}</td></tr>)}</tbody></table></div>:<p className="people-empty-note">{filtered?'目前篩選沒有出差／外出紀錄。':'目前快照沒有已讀取的出差／外出紀錄；不代表沒有申請。'}</p>}
  </section>
 </section>;
}
