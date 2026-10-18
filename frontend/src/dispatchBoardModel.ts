export type Feasibility = 'feasible'|'conflict'|'unavailable'|'unknown';
export type DispatchQuality = 'complete'|'partial'|'stale'|'read_failed'|'forbidden'|'unknown';
export type DispatchCrew = {person_ref:string;name:string|null;active:boolean|null;feasibility:Feasibility;reasons:string[]};
export type DispatchResource = {kind:'instrument'|'vehicle'|'unknown';ref:string;label:string|null;feasibility:Feasibility;reasons:string[]};
export type DispatchSlot = {
 slot_id:string;record_id:string;kind:'work'|'leave'|'standby'|'support'|'unknown';planning_status:'unassigned'|'confirmed'|'unknown';provenance:'v4_row'|'unknown';
 interval:{start:string|null;end:string|null;precision:'date'|'datetime'|'unknown'};group:string|null;discipline:string|null;
 case:{ref:string|null;code:string|null;name:string|null};work_content:string|null;crew:DispatchCrew[];resources:DispatchResource[];gaps:string[];issues:string[];
};
export type CapacityDay = {booked_slots:number;state:'free'|'booked'|'overbooked_unknown'|'unknown'};
export type DispatchBoardData = {
 schema_version:1;window:{from:string;to:string;tz:'Asia/Taipei'};
 source:{dataset_key:string;registry_key:string;table_id:string;fetched_at:string|null;latest_booking_date:string|null;quality:{states:DispatchQuality[];reason:string|null};joins:Record<'people'|'instruments'|'vehicles'|'cases','ok'|'partial'|'unavailable'|'unknown'>};
 kpi:{slots:number;unassigned:number;unknown_overlap:number;conflict:number};unassigned_queue:string[];slots:DispatchSlot[];
 capacity:{people:{person_ref:string;name:string|null;days:Record<string,CapacityDay>}[]};gaps:{code:string;message:string;count:number|null}[];
};
const object = (value:unknown):Record<string,unknown> => value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:{};
const list = (value:unknown):unknown[] => Array.isArray(value)?value:[];
const text = (value:unknown):string|null => typeof value==='string'&&value.trim()?value:null;
const strings = (value:unknown) => list(value).flatMap(v=>typeof v==='string'?[v]:[]);
const count = (value:unknown):number|null => typeof value==='number'&&Number.isInteger(value)&&value>=0?value:null;
function enumValue<T extends string>(value:unknown, values:readonly T[]):T|'unknown' {return values.find(v=>v===value)??'unknown'}
function dateOnly(value:unknown):string|null {
 if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;
 const time=Date.parse(value+'T00:00:00Z');return Number.isFinite(time)&&new Date(time).toISOString().slice(0,10)===value?value:null;
}
function timestamp(value:unknown):string|null {return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T/.test(value)&&Number.isFinite(Date.parse(value))?value:null}
function parseCrew(value:unknown):DispatchCrew {
 const p=object(value),active=typeof p.active==='boolean'?p.active:null;
 return {person_ref:text(p.person_ref)??'',name:text(p.name),active,feasibility:active===false?'unavailable':enumValue(p.feasibility,['feasible','conflict','unavailable','unknown']),reasons:[...new Set([...strings(p.reasons),...(active===false?['inactive']:[])])]};
}
function parseSlot(value:unknown):DispatchSlot|null {
 const s=object(value),id=text(s.slot_id);if(!id)return null;
 const interval=object(s.interval),c=object(s.case),precision=enumValue(interval.precision,['date','datetime']);
 const start=precision==='date'?dateOnly(interval.start):precision==='datetime'?timestamp(interval.start):null;
 const end=precision==='date'?dateOnly(interval.end):precision==='datetime'?timestamp(interval.end):null;
 return {slot_id:id,record_id:text(s.record_id)??'',kind:enumValue(s.kind,['work','leave','standby','support']),planning_status:enumValue(s.planning_status,['unassigned','confirmed']),provenance:enumValue(s.provenance,['v4_row']),
 interval:{start,end:end&&start&&Date.parse(end)>=Date.parse(start)?end:null,precision},group:text(s.group),discipline:text(s.discipline),case:{ref:text(c.ref),code:text(c.code),name:text(c.name)},work_content:text(s.work_content),
 crew:list(s.crew).map(parseCrew),resources:list(s.resources).map(value=>{const r=object(value);return {kind:enumValue(r.kind,['instrument','vehicle']),ref:text(r.ref)??'',label:text(r.label),feasibility:strings(r.reasons).some(v=>v==='repair'||v==='inactive')?'unavailable':enumValue(r.feasibility,['feasible','conflict','unavailable','unknown']),reasons:strings(r.reasons)}}),gaps:strings(s.gaps),issues:strings(s.issues)};
}
function parseCapacity(value:unknown):DispatchBoardData['capacity']['people'][number] {
 const p=object(value);
 return {person_ref:text(p.person_ref)??'',name:text(p.name),days:Object.fromEntries(
  Object.entries(object(p.days)).filter(([day])=>dateOnly(day)).map(([day,value])=>{
   const d=object(value);return [day,{booked_slots:count(d.booked_slots)??0,state:enumValue(d.state,['free','booked','overbooked_unknown','unknown'])}];
  })
 )};
}
export function parseDispatchBoard(value:unknown):DispatchBoardData {
 const b=object(value),w=object(b.window),source=object(b.source),quality=object(source.quality),joins=object(source.joins);
 const from=dateOnly(w.from),to=dateOnly(w.to);
 if(b.schema_version!==1||!from||!to||to<from||Date.parse(to)-Date.parse(from)>31*86400000||w.tz!=='Asia/Taipei'||!Array.isArray(b.slots))throw new Error('派工資料格式不正確，請重新讀取。');
 const states:DispatchQuality[]=list(quality.states).map(v=>enumValue(v,['complete','partial','stale','read_failed','forbidden','unknown']));
 const forbidden=states.includes('forbidden');
 const slots=forbidden?[]:list(b.slots).flatMap(value=>{const slot=parseSlot(value);return slot?[slot]:[]}).filter((s,i,all)=>all.findIndex(other=>other.slot_id===s.slot_id)===i);
 if(!forbidden&&slots.length!==b.slots.length)states.push('partial');
 const board:DispatchBoardData={
  schema_version:1,window:{from,to,tz:'Asia/Taipei'},
  source:{
   dataset_key:text(source.dataset_key)??'',registry_key:text(source.registry_key)??'',table_id:forbidden?'':text(source.table_id)??'',
   fetched_at:forbidden?null:timestamp(source.fetched_at),latest_booking_date:forbidden?null:dateOnly(source.latest_booking_date),
   quality:{states:forbidden?['forbidden']:[...new Set(states.length?states:['unknown' as const])],reason:forbidden?null:text(quality.reason)},
   joins:{people:enumValue(joins.people,['ok','partial','unavailable']),instruments:enumValue(joins.instruments,['ok','partial','unavailable']),vehicles:enumValue(joins.vehicles,['ok','partial','unavailable']),cases:enumValue(joins.cases,['ok','partial','unavailable'])}
  },
  slots,kpi:dispatchKpi(slots),unassigned_queue:unassignedQueue(slots).map(s=>s.slot_id),
  capacity:{people:forbidden?[]:list(object(b.capacity).people).map(parseCapacity)},
  gaps:forbidden?[]:list(b.gaps).map(value=>{const g=object(value);return {code:text(g.code)??'unknown',message:text(g.message)??'部分來源尚未提供',count:count(g.count)}})
 };
 return board;
}
export function unassignedQueue(slots:DispatchSlot[]) {return slots.filter(s=>s.planning_status==='unassigned')}
export function dispatchKpi(slots:DispatchSlot[]) {
 return {slots:slots.length,unassigned:unassignedQueue(slots).length,unknown_overlap:slots.filter(s=>[...s.crew,...s.resources].some(p=>p.reasons.includes('same_day_other_slot'))).length,conflict:slots.filter(s=>[...s.crew,...s.resources].some(p=>p.feasibility==='conflict')).length};
}
export function addDays(day:string,offset:number) {return new Date(Date.parse(day+'T00:00:00Z')+offset*86400000).toISOString().slice(0,10)}
export function weekDays(from:string) {return Array.from({length:7},(_,i)=>addDays(from,i))}
export function dispatchWeek(today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'})) {return addDays(today,-((new Date(today+'T00:00:00Z').getUTCDay()+6)%7))}
function intervalDay(value:string) {return value.length===10?value:new Date(value).toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'})}
export function slotsPerDay(slots:DispatchSlot[],day:string) {return slots.filter(s=>s.interval.start&&s.interval.end&&intervalDay(s.interval.start)<=day&&intervalDay(s.interval.end)>=day)}
export function slotsByGroup(slots:DispatchSlot[]) {return [...new Set(slots.map(s=>s.group))].map(group=>({group,label:group??'組別待確認',slots:slots.filter(s=>s.group===group)}))}
export function personDayGrid(board:DispatchBoardData,days=weekDays(board.window.from)) {
 const people=new Map(board.capacity.people.map(p=>[p.person_ref,{person_ref:p.person_ref,name:p.name}]));
 for(const s of board.slots)for(const p of s.crew)people.set(p.person_ref,{person_ref:p.person_ref,name:p.name??people.get(p.person_ref)?.name??null});
 return [...people.values()].map(p=>({...p,days:days.map(day=>{const slots=slotsPerDay(board.slots,day).filter(s=>s.crew.some(c=>c.person_ref===p.person_ref));return {day,slots,booked_slots:slots.length,state:slots.length>1?'overbooked_unknown' as const:slots.length?'booked' as const:'unknown' as const}})}));
}
export function boardDisplay(board:DispatchBoardData|undefined,error='') {
 if(board?.source.quality.states.includes('forbidden'))return {kind:'forbidden' as const,counts:null,message:'沒有派工資料的檢視權限。'};
 if(!board)return {kind:error?'failed' as const:'loading' as const,counts:null,message:error||'派工資料載入中'};
 const states=board.source.quality.states;
 if(states.includes('read_failed'))return {kind:'failed' as const,counts:null,message:'派工資料讀取失敗，請重試。'};
 if(!board.slots.length)return {kind:'empty' as const,counts:null,message:board.source.latest_booking_date?(board.window.from>board.source.latest_booking_date?`來源在 ${board.source.latest_booking_date} 之後沒有預排紀錄。本週尚無可核實的預排。`:`本週沒有預排紀錄，最後預排日期為 ${board.source.latest_booking_date}。`):'本週沒有預排紀錄，來源未提供最後預排日期。'};
 return {kind:error?'retained' as const:states.includes('stale')?'stale' as const:'ready' as const,counts:dispatchKpi(board.slots),message:error||''};
}
export function snapshotAge(value:string|null,now=Date.now()) {const time=value?Date.parse(value):NaN;return Number.isFinite(time)?`${Math.max(0,Math.floor((now-time)/60000))} 分鐘前`:'來源未提供時間'}
export const feasibilityLabels:Record<Feasibility,string>={feasible:'可用',conflict:'時段衝突',unavailable:'不可用',unknown:'待確認'};
const reasonLabels:Record<string,string>={inactive:'來源標示未在職或未啟用',timed_overlap:'與另一筆有明確時間的預排重疊',same_day_other_slot:'同日另有預排，缺少時間，無法判定衝突',no_leave_source:'缺少請假來源，出勤仍待確認',no_capability_source:'沒有能力與資格資料，尚無法核實',repair:'儀器送修或狀態異常，無法派用',no_crew:'尚未安排人員',no_case:'案件關聯待確認',no_instrument_for_field_work:'外業尚未安排儀器'};
export function dispatchReason(reason:string) {return reasonLabels[reason]??'來源提供未識別的檢核原因，請人工核對'}
export const slotTitle = (s:DispatchSlot) => s.case.code||s.case.name||s.work_content||'案件待確認';
