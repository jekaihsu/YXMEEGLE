import {api} from './api';

export const attendanceStatuses=['loading','ok','incomplete','stale','needs-permission','not-connected','read-failed'] as const;
export type AttendanceStatus=typeof attendanceStatuses[number];
export type AttendancePerson={id:string;name:string|null;avatar_url?:string;group:string|null;in_service:boolean|null;attendance:(string|null)[]};
export type AttendanceTrip={person_id:string;name:string|null;group:string|null;kind:'trip'|'out';start:string;end:string};
export type AttendanceLeave={person_id:string;name:string|null;group:string|null;start:string;end:string};
export type PeopleAttendance={status:AttendanceStatus;week_start:string;week_end:string;days:string[];people:AttendancePerson[];trips:AttendanceTrip[];leaves:AttendanceLeave[];leaves_available:boolean|null;as_of:string|null;missing_scopes:string[];refreshing:boolean;incomplete:boolean;summary:{people:number|null;in_service:number|null;on_leave:number|null;on_trip:number|null;trips:number|null}};
const field=(value:unknown,key:string):unknown=>value!==null&&typeof value==='object'?Reflect.get(value,key):undefined;
const string=(value:unknown):string|null=>typeof value==='string'&&value?value:null;
const strings=(value:unknown):string[]=>Array.isArray(value)?value.filter((item:unknown):item is string=>typeof item==='string'):[];
const count=(value:unknown):number|null=>typeof value==='number'&&Number.isInteger(value)&&value>=0?value:null;
const status=(value:unknown):AttendanceStatus=>attendanceStatuses.find(s=>s===value)??'read-failed';
export const attendanceValue=(value:number|string|boolean|null|undefined):string=>value===null||value===undefined||value===''?'—':typeof value==='boolean'?value?'在職':'離職':String(value);
export function taipeiWeek(value=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'})):string{
 const date=new Date(value+'T00:00:00Z');
 date.setUTCDate(date.getUTCDate()-((date.getUTCDay()+6)%7));
 return date.toISOString().slice(0,10);
}
export function parsePeopleAttendance(raw:unknown):PeopleAttendance{
 const state=status(field(raw,'status'));
 const known=state==='ok'||state==='incomplete'||state==='stale';
 const summary=field(raw,'summary');
 const people:AttendancePerson[]=[];const trips:AttendanceTrip[]=[];const leaves:AttendanceLeave[]=[];
 const rawPeople=field(raw,'people');
 if(Array.isArray(rawPeople))for(const row of rawPeople){
  const id=string(field(row,'id'));if(!id)continue;
  const service=field(row,'in_service'),days=field(row,'attendance'),photo=string(field(row,'avatar_url'));
  people.push({id,name:string(field(row,'name')), ...(photo ? {avatar_url:photo} : {}),group:string(field(row,'group')),in_service:typeof service==='boolean'?service:null,attendance:Array.isArray(days)?days.map((d:unknown)=>string(d)):[]});
 }
 const rawTrips=field(raw,'trips');
 if(Array.isArray(rawTrips))for(const row of rawTrips){
  const id=string(field(row,'person_id')),kind=field(row,'kind'),start=string(field(row,'start')),end=string(field(row,'end'));
  if(id&&(kind==='trip'||kind==='out')&&start&&end)trips.push({person_id:id,name:string(field(row,'name')),group:string(field(row,'group')),kind,start,end});
 }
 const rawLeaves=field(raw,'leaves');
 if(known&&Array.isArray(rawLeaves))for(const row of rawLeaves){
  const id=string(field(row,'person_id')),start=string(field(row,'start')),end=string(field(row,'end'));
  if(id&&start&&end&&/^\d{4}-\d{2}-\d{2}$/.test(start)&&/^\d{4}-\d{2}-\d{2}$/.test(end)&&end>=start)leaves.push({person_id:id,name:string(field(row,'name')),group:string(field(row,'group')),start,end});
 }
 const available=field(raw,'leaves_available');
 return {status:state,week_start:string(field(raw,'week_start'))??'',week_end:string(field(raw,'week_end'))??'',days:strings(field(raw,'days')),people,trips,leaves,leaves_available:known?(typeof available==='boolean'?available:null):false,as_of:string(field(raw,'as_of')),missing_scopes:strings(field(raw,'missing_scopes')),refreshing:field(raw,'refreshing')===true,incomplete:field(raw,'incomplete')===true||state==='incomplete',summary:{people:known?count(field(summary,'people')):null,in_service:known?count(field(summary,'in_service')):null,on_leave:known?count(field(summary,'on_leave')):null,on_trip:known?count(field(summary,'on_trip')):null,trips:known?count(field(summary,'trips')):null}};
}
export async function fetchPeopleAttendance({week,signal,current}:{week?:string;signal?:AbortSignal;current?:()=>boolean}={}):Promise<PeopleAttendance>{
 const query=week?'?'+new URLSearchParams({week}):'';
 return parsePeopleAttendance(await api<unknown>('/api/people/attendance'+query,{signal},current));
}
export const attendanceStatusLabel:Record<AttendanceStatus,string>={loading:'讀取中',ok:'已讀取',incomplete:'資料不完整',stale:'舊快照，更新中', 'needs-permission':'needs-permission：缺少唯讀權限','not-connected':'尚未連接 Lark','read-failed':'讀取失敗'};
