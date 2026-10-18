import {taipeiWeek,type AttendancePerson,type PeopleAttendance} from './peopleAttendance';
import type {HomeItem} from './useHomePanels';

export const weekDays=(today:string)=>Array.from({length:5},(_,index)=>new Date(Date.parse(taipeiWeek(today)+'T00:00:00Z')+index*86400000).toISOString().slice(0,10));
export function absenceCell(view:PeopleAttendance,person:AttendancePerson,day:string):'在'|'請假'|'出差'|'—'{
 if(person.in_service===false)return '—';
 if(view.leaves.some(row=>row.person_id===person.id&&row.start<=day&&row.end>=day))return '請假';
 if(view.trips.some(row=>row.person_id===person.id&&row.kind==='trip'&&row.start<=day&&row.end>=day))return '出差';
 const index=view.days.indexOf(day);
 if(index<0)return '—';
 if(view.leaves_available!==true){
  const cell=person.attendance[index];
  if(cell?.includes('請假'))return '請假';
  if(cell?.includes('出差'))return '出差';
  if(!cell?.trim())return '—';
 }
 return '在';
}
export function scopedAttendance(view:PeopleAttendance,scope:'assign'|'company',department:string|null|undefined){
 const group=department?.trim();
 if(scope==='assign'&&(!group||!view.people.some(person=>person.group===group)))return {known:false,people:[]};
 return {known:true,people:view.people.filter(person=>scope==='company'||person.group===group)};
}
export function weeklyPeople(view:PeopleAttendance,people:AttendancePerson[],today:string){
 const days=weekDays(today);
 return people.map(person=>{const cells=days.map(day=>absenceCell(view,person,day));return {person,cells,absenceDays:days.filter((_,index)=>cells[index]==='請假'||cells[index]==='出差')}});
}
export function absenceImpact(rows:ReturnType<typeof weeklyPeople>,items:HomeItem[],today:string){
 const days=weekDays(today);
 return rows.filter(row=>row.absenceDays.length).map(row=>{
  const open=[...new Map(items.filter(item=>!['done','completed','cancelled','skipped'].includes(item.status)&&item.assignees.some(person=>person.id===row.person.id)).map(item=>[item.id,item])).values()];
  const deadline=(item:HomeItem)=>(item.deadline||item.next_due)?.slice(0,10);
  return {...row,open:open.length,due:open.filter(item=>{const day=deadline(item);return day&&day>=days[0]&&day<=days[4]}).length,overdue:open.filter(item=>{const day=deadline(item);return item.overdue||!!day&&day<today}).length};
 }).filter(row=>row.open);
}
