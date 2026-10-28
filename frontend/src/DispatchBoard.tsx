import {useEffect,useRef,useState,type KeyboardEvent} from 'react';
import {CalendarDays,ChevronLeft,ChevronRight,RefreshCw,X} from 'lucide-react';
import {api,getSessionEpoch} from './api';
import {Badge,Button,Skeleton} from './design';
import {useViewData} from './viewData';
import {useDialogFocus} from './useDialogFocus';
import {taipeiTime} from './taipeiTime';
import {addDays,boardDisplay,dispatchReason,dispatchWeek,feasibilityLabels,personDayGrid,slotTitle,slotsByGroup,slotsPerDay,snapshotAge,unassignedQueue,weekDays,type DispatchSlot,type Feasibility} from './dispatchBoardModel';
import {dispatchCaseHref,parseDispatchProjects,type DispatchProject} from './dispatchLinks';
import {useDispatchBoardRead,type DispatchRead} from './dispatchBoardRead';
import './DispatchBoard.css';

const kinds={execution:'執行任務',work:'出工',leave:'休假',standby:'待命',support:'支援',unknown:'類型待確認'};
const planning={publishing:'發布中，尚未確認',confirmed:'來源已預排',unassigned:'待派工',unknown:'安排待確認'};

function FeasibilityBadge({value}:{value:Feasibility}) {
 return <Badge tone={value==='conflict'?'critical':value==='unavailable'?'warning':value==='feasible'?'positive':undefined}>{feasibilityLabels[value]}</Badge>;
}

function SlotCard({slot,onOpen,onAssign}:{slot:DispatchSlot;onOpen:(slot:DispatchSlot)=>void;onAssign?:(slot:DispatchSlot)=>void}) {
 const warning=[...slot.crew,...slot.resources].find(p=>p.feasibility==='conflict'||p.feasibility==='unavailable');
 const timeLabel=slot.interval.precision==='datetime'&&slot.interval.start?new Date(slot.interval.start).toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false}):'僅日期，時段待確認';
 const crewLabel=slot.crew.length?slot.crew.map(p=>p.name||'姓名待確認').join('、'):'尚未安排人員';
 return <div className="db-slot-wrapper">
  <button className="db-slot" onClick={()=>onOpen(slot)} aria-label={`查看 ${slotTitle(slot)} 派工明細，${crewLabel}，${planning[slot.planning_status]}${warning||slot.crew.some(p=>p.reasons.includes('same_day_other_slot'))?'，':''}${warning?feasibilityLabels[warning.feasibility]:slot.crew.some(p=>p.reasons.includes('same_day_other_slot'))?'同日重疊待確認':''}`}>
   <div className="db-slot-header">
    <strong>{slotTitle(slot)}</strong>
    <span className="db-slot-badge">{warning?<FeasibilityBadge value={warning.feasibility}/>:<Badge>{slot.crew.some(p=>p.reasons.includes('same_day_other_slot'))?'同日重疊待確認':planning[slot.planning_status]}</Badge>}</span>
   </div>
   <span className="db-slot-content">{slot.work_content||kinds[slot.kind]}</span>
   <div className="db-slot-meta">
    <small className="db-slot-time">{timeLabel}</small>
    <span className="db-crew">{crewLabel}</span>
   </div>
  </button>
  {onAssign&&slot.planning_status==='unassigned'&&<Button variant="secondary" onClick={()=>onAssign(slot)}>排班</Button>}
 </div>;
}

function SlotDetail({slot,slots,onOpen,onClose,projects}:{projects:DispatchProject[];slot:DispatchSlot;slots:DispatchSlot[];onOpen:(slot:DispatchSlot)=>void;onClose:()=>void}) {
 const ref=useDialogFocus(onClose);
 const localHref=dispatchCaseHref(slot.case,projects);
 const query=[...new Set([slot.case.code,slot.case.name].filter((value):value is string=>!!value?.trim()))];
 const resolution=useViewData(`dispatch-case:${getSessionEpoch()}:${JSON.stringify(slot.case)}`,async(signal,current)=>{
  if(localHref||!query.length)return [];
  const pages=await Promise.all(query.map(q=>api<unknown>(`/api/projects?${new URLSearchParams({view:'overview',tab:'all',q,limit:'100',offset:'0'})}`,{signal,cache:'no-store'},current)));
  const parsed=pages.map(parseDispatchProjects);
  if(parsed.some(page=>page===null))return [];
  const found=parsed.flatMap(page=>page??[]);
  return [...new Map(found.map(project=>[project.id,project])).values()];
 });
 const caseHref=localHref||dispatchCaseHref(slot.case,resolution.data??[]);
 return <div className="db-scrim" onClick={onClose}>
  <section className="db-drawer glass--card" ref={ref} role="dialog" aria-modal="true" aria-labelledby="dispatch-detail-title" tabIndex={-1} onClick={e=>e.stopPropagation()}>
   <header className="db-drawer-header">
    <div>
     <h2 id="dispatch-detail-title">{slotTitle(slot)}</h2>
     <p className="db-drawer-sub">{slot.group||'組別待確認'} · {slot.discipline||'作業別待確認'} · {kinds[slot.kind]}</p>
    </div>
    <Button aria-label="關閉派工明細" onClick={onClose}><X size={18}/></Button>
   </header>

   <div className="db-drawer-section">
    <p className="db-case-link">{caseHref?<a href={caseHref}>開啟案件 {slot.case.code||slot.case.name}</a>:<span className="db-muted">案件連結未能解析</span>}</p>
    <p className="db-work-desc">{slot.work_content||'工作內容待確認'}</p>
    <p className="db-time-range">{slot.interval.start?(slot.interval.precision==='datetime'?taipeiTime(slot.interval.start):slot.interval.start):'開始日期待確認'} ～ {slot.interval.end?(slot.interval.precision==='datetime'?taipeiTime(slot.interval.end):slot.interval.end):'結束日期待確認'}</p>
    <div className="db-provenance-box">
     <Badge>{planning[slot.planning_status]}</Badge>
     <p className="db-muted">{slot.provenance==='v4_task'?'此列來自 V4 任務。發布中仍須等待命令讀回確認。':'已預排代表 V4 已有紀錄，尚未由此工作台發布或確認回讀。'}</p>
    </div>
   </div>

   <div className="db-drawer-section">
    <h3>人員</h3>
    {slot.crew.length?slot.crew.map((p,i)=><article className="db-detail-row" key={i}>
     <div><strong>{p.name||'姓名待確認'}</strong><FeasibilityBadge value={p.feasibility}/></div>
     {p.reasons.length?<ul>{p.reasons.map((r,i)=><li key={i}>{dispatchReason(r)}</li>)}</ul>:<p className="db-muted">來源未提供檢核原因。</p>}
    </article>):<p className="db-muted">尚未安排人員。</p>}
   </div>

   <div className="db-drawer-section">
    <h3>儀器與車輛</h3>
    {slot.resources.length?slot.resources.map((r,i)=><article className="db-detail-row" key={i}>
     <div><strong>{r.label||(r.kind==='vehicle'?'車輛名稱待確認':r.kind==='instrument'?'儀器名稱待確認':'資源名稱待確認')}</strong><FeasibilityBadge value={r.feasibility}/></div>
     <p className="db-muted">{r.kind==='vehicle'?'車輛':r.kind==='instrument'?'儀器':'資源類型待確認'}</p>
     {r.reasons.map((reason,i)=><p key={i}>{dispatchReason(reason)}</p>)}
    </article>):<p className="db-muted">尚無已安排的儀器與車輛。</p>}
   </div>

   <div className="db-drawer-section">
    <h3>資格與出勤檢核</h3>
    <p><FeasibilityBadge value="unknown"/> 沒有能力與資格來源，尚無法核實。</p>
    <p className="db-muted">缺少完整請假資料，預排不代表出勤已確認。</p>
    {!!slot.gaps.length&&<><h3>待補資料</h3><ul>{slot.gaps.map((g,i)=><li key={i}>{dispatchReason(g)}</li>)}</ul></>}
    {!!slot.issues.length&&<><h3>同人員或資源的其他預排</h3>{slot.issues.map((id,i)=>{const related=slots.find(s=>s.slot_id===id);return related?<Button key={id} onClick={()=>onOpen(related)}>{slotTitle(related)}</Button>:<p key={i} className="db-muted">關聯預排尚未載入。</p>})}</>}
   </div>
  </section>
 </div>;
}


export function DispatchBoardFrame({from,read,onWeek,projects=[],onAssign}:{from:string;read:DispatchRead;onWeek:(day:string)=>void;projects?:DispatchProject[];onAssign?:(slot?:DispatchSlot)=>void}) {
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
  <header className="ds-page-head">
   <div className="ds-page-title-block">
    <h1>派工看板</h1>
    <p className="ds-page-sub">先看待派工作，再核對每日人員與資源安排。</p>
   </div>
   <div className="ds-page-head-actions">
    <Button onClick={read.reload} disabled={read.loading}><RefreshCw size={15}/>{read.loading?'讀取中…':'重新讀取'}</Button>
   </div>
  </header>

  <section className="db-week glass--flat" aria-label="派工週次">
   <div className="db-week-range">
    <CalendarDays size={18}/>
    <h2>{from.replaceAll('-','/')} ～ {addDays(from,6).replaceAll('-','/')}</h2>
    <span className="db-muted db-tz">台北時間</span>
   </div>
   <div className="db-week-nav">
    <Button aria-label="上一週" onClick={()=>onWeek(addDays(from,-7))}><ChevronLeft size={16}/></Button>
    <Button onClick={()=>onWeek(dispatchWeek())}>本週</Button>
    <Button aria-label="下一週" onClick={()=>onWeek(addDays(from,7))}><ChevronRight size={16}/></Button>
   </div>
  </section>

  <div className="db-source">
   <span role="status" aria-live="polite">
    {hidden?'沒有派工資料的檢視權限。':skeleton?'正在讀取工作預排，人員與資源名稱會陸續補上。':<>{board?'已載入工作預排。':'尚未成功讀取的派工資料。'}{(read.stale||board?.source.quality.states.includes('stale')||display.kind==='retained')&&' · 上次成功快照，資料待更新'}{read.loading&&' · 更新中'}</>}
   </span>
   {board&&<> · 資料時間 {board.source.fetched_at?taipeiTime(board.source.fetched_at):'來源未提供'} · {board.source.quality.age_seconds!==null?`${Math.floor(board.source.quality.age_seconds/60)} 分鐘前`:snapshotAge(board.source.fetched_at,now)}</>}
  </div>

  <div className="db-kpis" aria-label="本週派工摘要" aria-busy={skeleton}>
   {(['slots','unassigned','unknown_overlap','conflict'] as const).map((key,i)=>{
    const count=display.counts?display.counts[key]:undefined;
    const toneClass=key==='unassigned'&&count&&count>0?'db-kpi--attention':key==='conflict'&&count&&count>0?'db-kpi--critical':'';
    return <div className={`db-kpi glass--flat ${toneClass}`} key={key}>
     <span>{['預排工作','待派工作','同日重疊待確認','已核實時段衝突'][i]}</span>
     {skeleton?<Skeleton width="3rem" height="2rem"/>:<strong>{display.counts?display.counts[key]:'—'}</strong>}
     <small>{hidden?'權限不足':display.kind==='empty'?'來源未涵蓋本週':display.kind==='failed'?'未能讀取來源':display.kind==='stale'||display.kind==='retained'?'上次快照筆數':'依本週清單'}</small>
    </div>;
   })}
  </div>

  <div className="db-notice-space">
   {read.error||board?.source.quality.states.includes('read_failed')||display.kind==='failed'?<div className="db-notice" role="alert">派工資料讀取失敗。{board?'已保留上次成功資料。':'目前無法核實預排，未以零代替。'}<Button disabled={read.loading} onClick={read.reload}>重試</Button></div>:display.kind==='empty'?<p className="db-notice">{display.message}</p>:hidden?<p className="db-notice">請聯絡管理員確認派工資料權限。</p>:board?.source.quality.states.some(s=>s==='partial'||s==='unknown')?<p className="db-notice">部分來源尚待確認，清單僅代表已載入的預排。</p>:<p className="db-muted">日期相同不代表時段衝突。資格與出勤仍須核對。</p>}
  </div>

  <section className="db-queue glass--flat" aria-label="待派工作">
   <header className="db-queue-head">
    <div className="db-queue-title">
     <h2>待派工作</h2>
     <span className="db-muted">尚未安排人員的來源預排</span>
    </div>
    {queue.length>0&&<Badge tone="warning">{queue.length} 件待派</Badge>}
   </header>
   <div className="db-queue-items" aria-busy={skeleton}>
    {skeleton?Array.from({length:3},(_,i)=><div className="db-slot db-skeleton" key={i}><Skeleton lines={3}/></div>):hidden?<p className="db-muted">權限不足，無法顯示待派工作。</p>:queue.length?queue.map(slot=><SlotCard key={slot.slot_id} slot={slot} onOpen={s=>setSelectedId(s.slot_id)} onAssign={onAssign}/>):<p className="db-muted">{board?.slots.length?'已載入清單沒有待派工作。':display.kind==='empty'?'本週來源沒有預排，無法核實待派需求。':'待派工作尚未讀取。'}</p>}
   </div>
  </section>

  <section className="db-schedule" aria-label="每日預排">
   <header className="db-schedule-head">
    <div>
     <h2>每日預排</h2>
     <p className="db-muted">左右方向鍵切換日期，Enter 開啟明細，Esc 關閉。</p>
    </div>
    <div role="group" aria-label="預排檢視" className="db-view-switch">
     <Button aria-pressed={mode==='group'} onClick={()=>setMode('group')}>依組別</Button>
     <Button aria-pressed={mode==='person'} onClick={()=>setMode('person')}>依人員</Button>
    </div>
   </header>
   {mode==='group'?<div className="db-days">
    {days.map((day,index)=><section key={day} className="db-day glass--flat" tabIndex={0} ref={el=>{dayRefs.current[index]=el}} onKeyDown={e=>moveDay(e,index)} aria-label={`${day} 預排`}>
     <h3>{['一','二','三','四','五','六','日'][index]}<span>{day.slice(5).replace('-','/')}</span></h3>
     <div className="db-day-body">
      {skeleton?<div className="db-slot db-skeleton"><Skeleton lines={4}/></div>:slotsPerDay(slots,day).length?slotsByGroup(slotsPerDay(slots,day)).map(g=><div className="db-group" key={g.label}><h4>{g.label}</h4>{g.slots.map(s=><SlotCard key={s.slot_id} slot={s} onOpen={s=>setSelectedId(s.slot_id)} onAssign={onAssign}/>)}</div>):<p className="db-muted">{hidden?'權限不足':board?'來源未列預排':'等待資料'}</p>}
     </div>
    </section>)}
   </div>:<div className="db-person-grid glass--flat">
    {board?personDayGrid(board,days).map(p=><section key={p.person_ref} className="db-person-row">
     <div className="db-person-name">
      <h3>{p.name||'姓名待確認'}</h3>
      <span className="db-muted">{p.days.reduce((acc,d)=>acc+d.booked_slots,0)} 筆預排</span>
     </div>
     <div className="db-person-days">
      {p.days.map((d,index)=><div key={d.day} tabIndex={0} className="db-person-day" aria-label={`${p.name||'姓名待確認'} ${d.day} 預排`} onKeyDown={e=>{
       if(e.key==='Enter'&&e.target===e.currentTarget){const first=d.slots[0];if(first){e.preventDefault();setSelectedId(first.slot_id)}return}
       const step=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0;if(!step)return;
       e.preventDefault();const next=e.currentTarget.parentElement?.children[(index+step+7)%7];if(next instanceof HTMLElement)(next.querySelector<HTMLElement>('.db-slot')??next).focus();
      }}>
       <div className="db-person-day-head">
        <strong>{d.day.slice(5)}</strong>
        <span className="db-person-day-count">{d.booked_slots?`${d.booked_slots} 筆預排`:'無預排，出勤待確認'}</span>
       </div>
       <div className="db-person-day-slots">
        {d.slots.map(s=><SlotCard key={s.slot_id} slot={s} onOpen={s=>setSelectedId(s.slot_id)} onAssign={onAssign}/>)}
       </div>
      </div>)}
     </div>
    </section>):<p className="db-muted">人員資料尚未提供。</p>}
    {board&&!personDayGrid(board,days).length&&<p className="db-muted">本週沒有可核實的人員預排。</p>}
   </div>}
  </section>

  <section className="db-gaps glass--flat">
   <header className="db-gaps-head">
    <h2>資料缺口</h2>
    <span className="db-muted">最後預排日期 · {board?.source.latest_booking_date??'來源未提供'}</span>
   </header>
   {hidden?<p className="db-muted">權限不足，無法顯示來源資訊。</p>:skeleton?<Skeleton lines={2}/>:<ul className="db-gaps-list">
    <li>沒有能力與資格來源，所有資格檢核均待確認。</li>
    {board?.gaps.filter(g=>g.code!=='no_capability_source').map((g,i)=><li key={i}>{g.message}</li>)}
    {board&&Object.values(board.source.joins).some(s=>s!=='ok')&&<li>部分人員、案件或資源名稱尚未載入，暫以待確認顯示。</li>}
    {slots.some(s=>!s.interval.start||!s.interval.end)&&<li>部分預排缺少有效日期，保留於摘要與待派清單，無法放入日期格。</li>}
   </ul>}
  </section>

  {selected&&!hidden&&<SlotDetail projects={projects} slot={selected} slots={slots} onOpen={s=>setSelectedId(s.slot_id)} onClose={()=>setSelectedId('')}/>}
 </div>;
}

export function DispatchBoard({projects=[]}:{projects?:DispatchProject[]}) {
 const [from,setFrom]=useState(dispatchWeek);
 const read=useDispatchBoardRead(from);
 return <DispatchBoardFrame key={`${getSessionEpoch()}:${from}`} from={from} read={read} onWeek={setFrom} projects={projects}/>;
}
