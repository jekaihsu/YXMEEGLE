import {useEffect,useRef,useState,type KeyboardEvent} from 'react';
import {CalendarDays,ChevronLeft,ChevronRight,RefreshCw,X} from 'lucide-react';
import {api,ApiError,getSessionEpoch} from './api';
import {Badge,Button,Eyebrow,Skeleton} from './design';
import {useViewData} from './viewData';
import {useDialogFocus} from './useDialogFocus';
import {taipeiTime} from './taipeiTime';
import {addDays,boardDisplay,dispatchReason,dispatchWeek,feasibilityLabels,parseDispatchBoard,personDayGrid,slotTitle,slotsByGroup,slotsPerDay,snapshotAge,unassignedQueue,weekDays,type DispatchBoardData,type DispatchSlot,type Feasibility} from './dispatchBoardModel';
import './DispatchBoard.css';

const kinds={work:'出工',leave:'休假',standby:'待命',support:'支援',unknown:'類型待確認'};
const planning={confirmed:'來源已預排',unassigned:'待派工',unknown:'安排待確認'};
function FeasibilityBadge({value}:{value:Feasibility}) {return <Badge tone={value==='conflict'?'critical':value==='unavailable'?'warning':value==='feasible'?'positive':undefined}>{feasibilityLabels[value]}</Badge>}
function SlotCard({slot,onOpen}:{slot:DispatchSlot;onOpen:(slot:DispatchSlot)=>void}) {
 const warning=[...slot.crew,...slot.resources].find(p=>p.feasibility==='conflict'||p.feasibility==='unavailable');
 return <button className="db-slot" onClick={()=>onOpen(slot)} aria-label={`查看 ${slotTitle(slot)} 派工明細`}><strong>{slotTitle(slot)}</strong><span>{slot.work_content||kinds[slot.kind]}</span><small>{slot.interval.precision==='datetime'&&slot.interval.start?new Date(slot.interval.start).toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false}):'僅日期，時段待確認'}</small><span className="db-crew">{slot.crew.length?slot.crew.map(p=>p.name||'姓名待確認').join('、'):'尚未安排人員'}</span><span>{warning?<FeasibilityBadge value={warning.feasibility}/>:<Badge>{slot.crew.some(p=>p.reasons.includes('same_day_other_slot'))?'同日重疊待確認':planning[slot.planning_status]}</Badge>}</span></button>;
}
function SlotDetail({slot,slots,onOpen,onClose}:{slot:DispatchSlot;slots:DispatchSlot[];onOpen:(slot:DispatchSlot)=>void;onClose:()=>void}) {
 const ref=useDialogFocus(onClose);
 return <div className="db-scrim" onClick={onClose}><section className="db-drawer glass--card" ref={ref} role="dialog" aria-modal="true" aria-labelledby="dispatch-detail-title" tabIndex={-1} onClick={e=>e.stopPropagation()}>
 <header><div><Eyebrow>預排明細 · 唯讀</Eyebrow><h2 id="dispatch-detail-title">{slotTitle(slot)}</h2></div><Button aria-label="關閉派工明細" onClick={onClose}><X size={18}/></Button></header>
 <p>{slot.work_content||'工作內容待確認'}</p><p className="db-muted">{slot.group||'組別待確認'} · {slot.discipline||'作業別待確認'} · {kinds[slot.kind]}</p>
 <p>{slot.interval.start?(slot.interval.precision==='datetime'?taipeiTime(slot.interval.start):slot.interval.start):'開始日期待確認'} ～ {slot.interval.end?(slot.interval.precision==='datetime'?taipeiTime(slot.interval.end):slot.interval.end):'結束日期待確認'}</p>
 <p><Badge>{planning[slot.planning_status]}</Badge></p><p className="db-muted">已預排代表 V4 已有紀錄，尚未由此工作台發布或確認回讀。</p>
 <h3>人員</h3>{slot.crew.length?slot.crew.map((p,i)=><article className="db-detail-row" key={i}><div><strong>{p.name||'姓名待確認'}</strong><FeasibilityBadge value={p.feasibility}/></div>{p.reasons.length?<ul>{p.reasons.map((r,i)=><li key={i}>{dispatchReason(r)}</li>)}</ul>:<p className="db-muted">來源未提供檢核原因。</p>}</article>):<p>尚未安排人員。</p>}
 <h3>儀器與車輛</h3>{slot.resources.length?slot.resources.map((r,i)=><article className="db-detail-row" key={i}><div><strong>{r.label||(r.kind==='vehicle'?'車輛名稱待確認':r.kind==='instrument'?'儀器名稱待確認':'資源名稱待確認')}</strong><FeasibilityBadge value={r.feasibility}/></div><p className="db-muted">{r.kind==='vehicle'?'車輛':r.kind==='instrument'?'儀器':'資源類型待確認'}</p>{r.reasons.map((reason,i)=><p key={i}>{dispatchReason(reason)}</p>)}</article>):<p>尚無已安排的儀器與車輛。</p>}
 <h3>資格與出勤檢核</h3><p><FeasibilityBadge value="unknown"/> 沒有能力與資格來源，尚無法核實。</p><p className="db-muted">缺少完整請假資料，預排不代表出勤已確認。</p>
 {!!slot.gaps.length&&<><h3>待補資料</h3><ul>{slot.gaps.map((g,i)=><li key={i}>{dispatchReason(g)}</li>)}</ul></>}
 {!!slot.issues.length&&<><h3>同人員或資源的其他預排</h3>{slot.issues.map((id,i)=>{const related=slots.find(s=>s.slot_id===id);return related?<Button key={id} onClick={()=>onOpen(related)}>{slotTitle(related)}</Button>:<p key={i}>關聯預排尚未載入。</p>})}</>}
 </section></div>;
}
export type DispatchRead = {data?:DispatchBoardData;loading:boolean;error:string;reload:()=>void};
export function DispatchBoardFrame({from,read,onWeek}:{from:string;read:DispatchRead;onWeek:(day:string)=>void}) {
 const [selectedId,setSelectedId]=useState(''),[mode,setMode]=useState<'group'|'person'>('group');
 const [now,setNow]=useState(Date.now);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),60000);return()=>clearInterval(timer)},[]);
 const display=boardDisplay(read.data,read.error),hidden=display.kind==='forbidden';
 const board=hidden?undefined:read.data,days=weekDays(from),skeleton=display.kind==='loading';
 const slots=board?.slots??[],selected=slots.find(s=>s.slot_id===selectedId),queue=unassignedQueue(slots);
 const dayRefs=useRef<(HTMLElement|null)[]>([]);
 const moveDay=(e:KeyboardEvent,index:number)=>{
  if(e.key==='Enter'&&e.target===e.currentTarget){const first=slotsPerDay(slots,days[index])[0];if(first){e.preventDefault();setSelectedId(first.slot_id)}return}
  const step=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0;if(!step)return;
  e.preventDefault();const next=(index+step+7)%7;const target=dayRefs.current[next];
  (target?.querySelector<HTMLElement>('.db-slot')??target)?.focus();
 };
 return <div className="dispatch-board ds-page" data-dispatch-state={display.kind}>
 <header className="ds-page-head"><div><Eyebrow>工作預排 · 人員與資源</Eyebrow><h1>派工看板</h1><p>先看待派工作，再核對每日人員與資源安排。</p></div><Button onClick={read.reload} disabled={read.loading}><RefreshCw size={16}/>{read.loading?'讀取中…':'重新讀取'}</Button></header>
 <section className="db-week glass--card" aria-label="派工週次"><div><CalendarDays size={20}/><h2>{from.replaceAll('-','/')} ～ {addDays(from,6).replaceAll('-','/')}</h2><span className="db-muted">台北時間</span></div><div><Button aria-label="上一週" onClick={()=>onWeek(addDays(from,-7))}><ChevronLeft size={17}/></Button><Button onClick={()=>onWeek(dispatchWeek())}>本週</Button><Button aria-label="下一週" onClick={()=>onWeek(addDays(from,7))}><ChevronRight size={17}/></Button></div></section>
 <div className="db-source" role="status" aria-live="polite">{hidden?'沒有派工資料的檢視權限。':skeleton?'正在讀取工作預排，人員與資源名稱會陸續補上。':<>{board?`資料時間 ${board.source.fetched_at?taipeiTime(board.source.fetched_at):'來源未提供'} · ${snapshotAge(board.source.fetched_at,now)}`:'尚無成功讀取的派工資料。'}{(board?.source.quality.states.includes('stale')||display.kind==='retained')&&' · 上次成功快照，資料待更新'}{read.loading&&' · 更新中'}</>}</div>
 <div className="db-kpis" aria-label="本週派工摘要" aria-busy={skeleton}>{(['slots','unassigned','unknown_overlap','conflict'] as const).map((key,i)=><div className="db-kpi glass--flat" key={key}><span>{['預排工作','待派工作','同日重疊待確認','已核實時段衝突'][i]}</span>{skeleton?<Skeleton width="3rem" height="2rem"/>:<strong>{display.counts?display.counts[key]:'—'}</strong>}<small>{hidden?'權限不足':display.kind==='empty'?'來源未涵蓋本週':display.kind==='failed'?'未能讀取來源':display.kind==='stale'||display.kind==='retained'?'上次快照筆數':'依本週清單'}</small></div>)}</div>
 <div className="db-notice-space">{read.error||display.kind==='failed'?<div className="db-notice" role="alert">派工資料讀取失敗。{board?'已保留上次成功資料。':'目前無法核實預排，未以零代替。'}<Button disabled={read.loading} onClick={read.reload}>重試</Button></div>:display.kind==='empty'?<p className="db-notice">{display.message}</p>:hidden?<p className="db-notice">請聯絡管理員確認派工資料權限。</p>:board?.source.quality.states.some(s=>s==='partial'||s==='unknown')?<p className="db-notice">部分來源尚待確認，清單僅代表已載入的預排。</p>:<p className="db-muted">日期相同不代表時段衝突。資格與出勤仍須核對。</p>}</div>
 <section className="db-queue glass--card" aria-label="待派工作"><header><h2>待派工作</h2><span className="db-muted">尚未安排人員的來源預排</span></header><div className="db-queue-items" aria-busy={skeleton}>{skeleton?Array.from({length:3},(_,i)=><div className="db-slot db-skeleton" key={i}><Skeleton lines={3}/></div>):hidden?<p>權限不足，無法顯示待派工作。</p>:queue.length?queue.map(slot=><SlotCard key={slot.slot_id} slot={slot} onOpen={s=>setSelectedId(s.slot_id)}/>):<p className="db-muted">{board?.slots.length?'已載入清單沒有待派工作。':display.kind==='empty'?'本週來源沒有預排，無法核實待派需求。':'待派工作尚未讀取。'}</p>}</div></section>
 <section className="db-schedule" aria-label="每日預排"><header><div><h2>每日預排</h2><p className="db-muted">左右方向鍵切換日期，Enter 開啟明細，Esc 關閉。</p></div><div role="group" aria-label="預排檢視"><Button aria-pressed={mode==='group'} onClick={()=>setMode('group')}>依組別</Button><Button aria-pressed={mode==='person'} onClick={()=>setMode('person')}>依人員</Button></div></header>
 {mode==='group'?<div className="db-days">{days.map((day,index)=><section key={day} className="db-day glass--flat" tabIndex={0} ref={el=>{dayRefs.current[index]=el}} onKeyDown={e=>moveDay(e,index)} aria-label={`${day} 預排`}><h3>{['一','二','三','四','五','六','日'][index]}<span>{day.slice(5).replace('-','/')}</span></h3><div className="db-day-body">{skeleton?<div className="db-slot db-skeleton"><Skeleton lines={4}/></div>:slotsPerDay(slots,day).length?slotsByGroup(slotsPerDay(slots,day)).map(g=><div className="db-group" key={g.label}><h4>{g.label}</h4>{g.slots.map(s=><SlotCard key={s.slot_id} slot={s} onOpen={s=>setSelectedId(s.slot_id)}/>)}</div>):<p className="db-muted">{hidden?'權限不足':board?'來源未列預排':'等待資料'}</p>}</div></section>)}</div>:<div className="db-person-grid glass--flat">{board?personDayGrid(board,days).map(p=><section key={p.person_ref}><h3>{p.name||'姓名待確認'}</h3><div className="db-person-days">{p.days.map((d,index)=><div key={d.day} tabIndex={0} aria-label={`${p.name||'姓名待確認'} ${d.day} 預排`} onKeyDown={e=>{
  if(e.key==='Enter'&&e.target===e.currentTarget){const first=d.slots[0];if(first){e.preventDefault();setSelectedId(first.slot_id)}return}
  const step=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0;if(!step)return;
  e.preventDefault();const next=e.currentTarget.parentElement?.children[(index+step+7)%7];if(next instanceof HTMLElement)(next.querySelector<HTMLElement>('.db-slot')??next).focus();
 }}><strong>{d.day.slice(5)}</strong><p>{d.booked_slots?`${d.booked_slots} 筆預排`:'無預排，出勤待確認'}</p>{d.slots.map(s=><SlotCard key={s.slot_id} slot={s} onOpen={s=>setSelectedId(s.slot_id)}/>)}</div>)}</div></section>):<p>人員資料尚未提供。</p>}{board&&!personDayGrid(board,days).length&&<p>本週沒有可核實的人員預排。</p>}</div>}
 </section>
 <section className="db-gaps glass--card"><h2>資料缺口</h2>{hidden?<p>權限不足，無法顯示來源資訊。</p>:skeleton?<Skeleton lines={2}/>:<><p className="db-muted">最後預排日期 · {board?.source.latest_booking_date??'來源未提供'}</p><ul><li>沒有能力與資格來源，所有資格檢核均待確認。</li>{board?.gaps.filter(g=>g.code!=='no_capability_source').map((g,i)=><li key={i}>{g.message}</li>)}{board&&Object.values(board.source.joins).some(s=>s!=='ok')&&<li>部分人員、案件或資源名稱尚未載入，暫以待確認顯示。</li>}{slots.some(s=>!s.interval.start||!s.interval.end)&&<li>部分預排缺少有效日期，保留於摘要與待派清單，無法放入日期格。</li>}</ul></>}</section>
 {selected&&!hidden&&<SlotDetail slot={selected} slots={slots} onOpen={s=>setSelectedId(s.slot_id)} onClose={()=>setSelectedId('')}/>}
 </div>;
}
export function DispatchBoard() {
 const [from,setFrom]=useState(dispatchWeek);
 const query=new URLSearchParams({from,to:addDays(from,6)});
 const key=`dispatch:${getSessionEpoch()}:${query}`;
 const read=useViewData(key,async(signal,current)=>{
  let raw:unknown;
  try {raw=await api<unknown>(`/api/v2/dispatch/board?${query}`,{signal,cache:'no-store',timeoutMs:30000},current)}
  catch(error){if(error instanceof ApiError&&error.status===403)raw={schema_version:1,window:{from,to:addDays(from,6),tz:'Asia/Taipei'},source:{quality:{states:['forbidden']}},slots:[]};else throw error}
  const board=parseDispatchBoard(raw);
  if(board.window.from!==from||board.window.to!==addDays(from,6))throw new Error('回應週次與目前查詢不符，請重試。');
  if(board.source.quality.states.includes('read_failed'))throw new Error('派工來源讀取失敗。');
  return board;
 });
 const refreshes=useRef({key,attempts:0});
 useEffect(()=>{
  if(refreshes.current.key!==key)refreshes.current={key,attempts:0};
  if(!read.data||read.loading||read.error||refreshes.current.attempts>=3||read.data.source.quality.states.includes('forbidden'))return;
  const pending=read.data.source.quality.states.includes('stale')||Object.values(read.data.source.joins).some(s=>s==='partial'||s==='unavailable');
  if(!pending)return;
  const timer=setTimeout(()=>{refreshes.current.attempts++;read.reload()},1500);
  return()=>clearTimeout(timer);
 },[key,read.data,read.loading,read.error,read.reload]);
 return <DispatchBoardFrame key={key} from={from} read={read} onWeek={setFrom}/>;
}
