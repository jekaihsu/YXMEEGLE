import {Skeleton} from './design';
import {stamp} from './appCommon';
import {Card,Message} from './homeCards';
import {attendanceStatusLabel,type PeopleAttendance} from './peopleAttendance';
import type {PanelRead} from './useHomePanels';
import {PanelNote} from './homeViews/shared';
import {absenceImpact,scopedAttendance,weeklyPeople,weekDays} from './homePeople';

export function PeopleCard({id,scope,department,view,loading,error,today,team}:{id:'absence'|'impact';scope:'assign'|'company';department?:string|null;view?:PeopleAttendance;loading:boolean;error:string;today:string;team?:PanelRead}){
 const href=id==='absence'?'#view=people':'#view=work&tab=assigned&ctx=scope%3Dteam';
 const available=view&&['ok','incomplete','stale'].includes(view.status);
 const scoped=view?scopedAttendance(view,scope,department):{known:false,people:[]};
 const rows=view&&scoped.known?weeklyPeople(view,scoped.people,today):[];
 const impact=absenceImpact(rows,team?.body?.readState==='disabled'?[]:team?.body?.items||[],today);
 const uncertain=!!(error||loading||view?.incomplete||view?.status!=='ok'||view?.refreshing||view?.leaves_available!==true||view?.summary.on_trip===null||rows.some(row=>row.cells.includes('—')));
 const teamKnown=!!team?.body&&team.body.readState!=='disabled';
 const teamComplete=teamKnown&&team?.body?.complete&&!team.body.has_more&&!team.pending&&!team.error&&team.body.freshness.status!=='stale';
 const days=weekDays(today),groups=[...new Set(rows.map(row=>row.person.group))];
 return <Card id={id} subtitle={id==='absence'?`本週 ${days[0].slice(5).replace('-','/')} 至 ${days[4].slice(5).replace('-','/')} · ${scope==='company'?'全公司':department||'組別待核對'}`:'不在的人手上的未完成工作'} href={href} action={id==='absence'?'查看人員與出勤':'開啟分配工作'}>
  {loading&&!view?<Skeleton lines={3}/>:!available?<Message>{error?'出勤資料讀取失敗，請重新讀取。':view?attendanceStatusLabel[view.status]:'出勤資料尚未提供。'}</Message>:!scoped.known?<Message>尚未確認你的所屬組別，無法顯示組員出勤與缺席影響。</Message>:<>
   {id==='absence'?<>
    {!!rows.length&&<p className="home-people-summary">{uncertain?'目前已載入資料中，':''}本週 {rows.filter(row=>row.absenceDays.length).length} 人有缺席{scope==='assign'&&teamKnown?`，${teamComplete?'':'已載入工作中'}影響 ${new Set(impact.flatMap(row=>row.itemIds)).size} 項未完成工作，其中 ${new Set(impact.flatMap(row=>row.dueItemIds)).size} 項本週到期`:''}。</p>}
    {!rows.length?<Message>{uncertain?'人員出勤名單尚待核對。':'目前沒有可顯示的人員出勤紀錄。'}</Message>:<div className="home-attendance-scroll"><table className="home-attendance"><caption className="sr-only">本週週一至週五出勤</caption><thead><tr><th scope="col">人員</th>{days.map((day,index)=><th scope="col" key={day} className={day===today?'is-today':''}>{['一','二','三','四','五'][index]}<small>{day.slice(5).replace('-','/')}</small></th>)}</tr></thead>{groups.map(group=><tbody key={group||''}>{scope==='company'&&<tr className="home-attendance-group"><th colSpan={6} scope="rowgroup">{group||'組別待核對'}</th></tr>}{rows.filter(row=>row.person.group===group).map(row=><tr key={row.person.id}><th scope="row">{row.person.name||'姓名待核對'}</th>{row.cells.map((cell,index)=><td key={days[index]} className={[days[index]===today?'is-today':'',cell==='—'?'is-unknown':''].filter(Boolean).join(' ')}>{cell==='—'?<><span aria-hidden="true">—</span><span className="sr-only">資料未提供</span></>:cell}</td>)}</tr>)}</tbody>)}</table></div>}
   </>:!teamKnown?<Message>{team?.pending?'團隊工作讀取中…':team?.error||'團隊工作來源尚未提供，缺席影響尚待核對。'}</Message>:<>
    {impact.map(row=><div className="home-impact-row" key={row.person.id}><span>{row.person.name||'姓名待核對'}<small>缺席 {row.absenceDays.length} 天（{row.absenceDays.map(day=>day.slice(5).replace('-','/')).join('、')}） · 未完成 {row.open} · 本週到期 {row.due} · <span data-tone={row.overdue?'critical':undefined}>逾期 {row.overdue}</span></small></span><a href={href}>重新分配</a></div>)}
    {!impact.length&&<Message>{uncertain||!teamComplete?'已載入資料中沒有可確認的缺席影響，完整名單尚待核對。':'本週缺席人員目前沒有未完成工作。'}</Message>}
   </>}
   {uncertain&&<p className="home-source-note">{view?.status==='stale'?'舊快照；':error?'更新失敗；':''}資料尚未完整或仍在更新，名單可能不完整。</p>}
   {view?.as_of&&<p className="home-source-note">出勤資料截至 {stamp(view.as_of)}</p>}
   {scope==='assign'&&team&&<PanelNote read={team}/>}
  </>}
 </Card>;
}
