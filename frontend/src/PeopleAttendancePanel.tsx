import {useEffect,useState} from 'react';
import {Section,Button} from './design';
import {useViewData,ViewSkeleton} from './viewData';
import {fetchPeopleAttendance,taipeiWeek,attendanceValue,attendanceStatusLabel} from './peopleAttendance';
import {WeeklyAttendanceTable} from './AttendanceWorkSchedules';
import {taipeiTime} from './taipeiTime';
import type {Context} from './Operations';

export function PeopleAttendancePanel({c}:{c:Context}){
 const [week,setWeek]=useState(taipeiWeek);
 const state=useViewData('people-attendance:'+week,(signal,current)=>fetchPeopleAttendance({week,signal,current}),[c.w.version]);
 const view=state.data;
 useEffect(()=>{
  if(!view?.refreshing)return;
  const timer=setTimeout(state.reload,2000);
  return()=>clearTimeout(timer);
 },[view,state.reload]);
 const groups=[...new Set(view?.people.map(p=>p.group)??[])];
 return <section className="owned-view"><h1>人員／資源與出勤</h1><p>Lark 唯讀資料，以台北時間週一至週日查看。未核對的組別及出勤顯示「—」。</p>
 <Section><div className="ops-fields"><label>週日期<input type="date" aria-label="出勤週日期" value={week} onChange={e=>{if(e.target.value)setWeek(taipeiWeek(e.target.value))}}/></label><Button disabled={state.loading} onClick={state.reload}>重新讀取</Button></div>
 {state.error&&<p role="alert">讀取失敗：{state.error}</p>}
 {state.loading&&!view&&<ViewSkeleton/>}
 {view&&<><p role="status">{attendanceStatusLabel[view.status]}{view.refreshing&&' · 正在讀取'} · as of {taipeiTime(view.as_of,'—')}{state.error&&' · 保留上次快照'}</p>
 {!!view.missing_scopes.length&&<p>缺少 scopes：{view.missing_scopes.join('、')}</p>}
 <p>{view.week_start} 至 {view.week_end}</p><p>名冊 {attendanceValue(state.error?null:view.summary.people)} 人 · 在職 {attendanceValue(state.error?null:view.summary.in_service)} 人 · 本週請假 {attendanceValue(state.error?null:view.summary.on_leave)} 人 · 出差 {attendanceValue(state.error?null:view.summary.on_trip)} 人 · 出差單 {attendanceValue(state.error?null:view.summary.trips)} 張</p>
 {view.incomplete&&<p>部分人員識別、組別或打卡證據待核對；空白不代表未出勤。只顯示 Lark 回傳的打卡結果，不推算應到人日或出勤率。</p>}
 {groups.map(group=><div key={group??'unknown'}><h2>{group??'組別 —'}</h2><WeeklyAttendanceTable days={view.days} people={view.people.filter(p=>p.group===group)}/></div>)}
 {!view.people.length&&<p>尚無可顯示的名冊資料。</p>}
 <h2>本週出差／外出紀錄</h2>{view.trips.length?<div className="owned-table"><table className="data-table"><thead><tr><th>人員</th><th>組別</th><th>類型</th><th>起日</th><th>迄日</th></tr></thead><tbody>{view.trips.map((trip,i)=><tr key={`${trip.person_id}-${trip.kind}-${i}`}><td>{attendanceValue(trip.name)}</td><td>{attendanceValue(trip.group)}</td><td>{trip.kind==='trip'?'出差':'外出'}</td><td>{trip.start}</td><td>{trip.end}</td></tr>)}</tbody></table></div>:<p>{view.summary.trips===null?'—':'本週沒有已讀取的出差／外出紀錄。'}</p>}
 </>}
 </Section></section>;
}
