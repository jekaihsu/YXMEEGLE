import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {ChevronDown,ChevronLeft,ChevronRight,CalendarOff} from 'lucide-react';
import {Ctx,TaskRow,NODE_NAMES,TaskIcon,elapsed,isLate,nameOf,openTask,shortDate,taskReadiness} from './appCommon';
import {Avatar} from './AppShell';
import {Segmented} from './design';
import {laneOf} from './MyWorkBoard';
import './TaskTimeline.css';

export type TimelineGroup='person'|'case';
export type TimelineScale='week'|'fortnight'|'month';
type Tone='late'|'blocked'|'week'|'later'|'done';
const TONES:[Tone,string][]=[['late','逾期'],['blocked','受阻'],['week','本週到期'],['later','進行中'],['done','已完成']];
const SCALES:[TimelineScale,string][]=[['week','週'],['fortnight','雙週'],['month','月']];
/** Zoom = how many days fit across the visible calendar. */
const FIT:Record<TimelineScale,number>={week:7,fortnight:14,month:31};
const MIN_COL=22;
const WEEKDAY=['日','一','二','三','四','五','六'];
const RANK:Record<Tone,number>={late:0,blocked:1,week:2,later:3,done:4};
/** Days loaded on each side at first, and how many more to add when the scroll nears an edge. */
const BEFORE=35,AFTER=70,GROW=56;

// Frame and resize helpers fall back gracefully where the browser APIs are missing (server-side test renders).
const raf=(fn:()=>void)=>typeof requestAnimationFrame==='function'?requestAnimationFrame(fn):setTimeout(fn,16) as unknown as number;
const caf=(id:number)=>{if(typeof cancelAnimationFrame==='function')cancelAnimationFrame(id);else clearTimeout(id)};
const DAY=86400000;
const toUtc=(s:string)=>Date.UTC(+s.slice(0,4),+s.slice(5,7)-1,+s.slice(8,10));
const fromUtc=(t:number)=>new Date(t).toISOString().slice(0,10);
const addDays=(s:string,n:number)=>fromUtc(toUtc(s)+n*DAY);
const diff=(a:string,b:string)=>Math.round((toUtc(b)-toUtc(a))/DAY);
const weekday=(s:string)=>new Date(toUtc(s)).getUTCDay();
const readScale=(key:string|undefined,fallback:TimelineScale):TimelineScale=>{try{const v=key&&localStorage.getItem(key);return v==='week'||v==='fortnight'||v==='month'?v:fallback}catch{return fallback}};

/** Gantt-style view. The task list is a fixed left pane; the calendar on the right is one continuous strip that keeps
 *  loading days as you scroll either way. The page scrolls vertically; the date header sticks under the app top bar.
 *  Open overdue tasks stretch to today so they stay in view after their due date. */
export function TaskTimeline({c,rows,groupBy,defaultScale='week',storageKey}:{c:Ctx;rows:TaskRow[];groupBy:TimelineGroup;defaultScale?:TimelineScale;storageKey?:string}){
 const asOf=c.w.as_of.slice(0,10);
 const[scale,setScaleState]=useState<TimelineScale>(()=>readScale(storageKey,defaultScale));
 const[range,setRange]=useState(()=>({start:addDays(asOf,-BEFORE),days:BEFORE+AFTER}));
 const[viewW,setViewW]=useState(0);
 const[visible,setVisible]=useState({from:0,to:0});
 const[closed,setClosed]=useState<Record<string,boolean>>({});
 const[showUndated,setShowUndated]=useState(false);
 const head=useRef<HTMLDivElement>(null);
 const body=useRef<HTMLDivElement>(null);
 const pending=useRef<{shift?:number;focus?:string;smooth?:boolean}>({focus:asOf});
 const frame=useRef(0);

 const hasBody=rows.some(r=>r.t.due_date);
 const col=Math.max(MIN_COL,viewW?Math.floor(viewW/FIT[scale]):40);
 const days=Array.from({length:range.days},(_,i)=>addDays(range.start,i));
 const last=days[days.length-1];
 const idx=(d:string)=>diff(range.start,d);
 const {holidays,workdays}=c.w.calendar;
 const isOff=(d:string)=>!workdays.includes(d)&&([0,6].includes(weekday(d))||holidays.includes(d));

 // Track the calendar pane's width so a zoom level always fits its number of days.
 useLayoutEffect(()=>{const el=body.current;if(!el)return;if(typeof ResizeObserver!=='function'){setViewW(el.clientWidth);return}const ro=new ResizeObserver(()=>setViewW(el.clientWidth));ro.observe(el);setViewW(el.clientWidth);return()=>ro.disconnect()},[hasBody]);
 // The scroll pane unmounts when there are no tasks; when it comes back it starts at scrollLeft 0, so reset the range around today
 // and re-focus today, otherwise the edge-loading would keep prepending days and drift years into the past.
 const mounted=useRef(false);
 useLayoutEffect(()=>{if(!hasBody)return;if(mounted.current){setRange({start:addDays(asOf,-BEFORE),days:BEFORE+AFTER});pending.current={focus:asOf}}mounted.current=true},[hasBody]);

 const readVisible=useCallback(()=>{const el=body.current;if(!el)return;
  const from=Math.floor(el.scrollLeft/col),to=Math.floor((el.scrollLeft+el.clientWidth-1)/col);
  setVisible(v=>v.from===from&&v.to===to?v:{from,to})},[col]);

 // After a render: keep position when days were prepended, or scroll to a requested day (today, or the centre before a zoom).
 // Visible-day state is read on the next frame, never synchronously here, so a smooth scroll can't loop renders.
 useLayoutEffect(()=>{const el=body.current;if(!el||!viewW)return;const p=pending.current;
  if(!p.shift&&!p.focus)return;
  if(p.shift){el.scrollLeft+=p.shift*col;p.shift=undefined}
  if(p.focus){const i=idx(p.focus);const target=Math.max(0,i*col-el.clientWidth/4);
   if(p.smooth&&Math.abs(target-el.scrollLeft)<el.clientWidth*2)el.scrollTo({left:target,behavior:'smooth'});else el.scrollLeft=target;p.focus=undefined;p.smooth=undefined}
  if(head.current)head.current.scrollLeft=el.scrollLeft;caf(frame.current);frame.current=raf(readVisible)});
 useEffect(()=>{readVisible()},[readVisible,viewW]);

 const onScroll=()=>{const el=body.current;if(!el)return;if(head.current)head.current.scrollLeft=el.scrollLeft;
  caf(frame.current);frame.current=raf(()=>{readVisible();
   const edge=el.clientWidth*1.5;
   if(el.scrollLeft<edge){pending.current.shift=GROW;setRange(r=>({start:addDays(r.start,-GROW),days:r.days+GROW}))}
   else if(el.scrollWidth-el.scrollLeft-el.clientWidth<edge)setRange(r=>({...r,days:r.days+GROW}))})};
 useEffect(()=>()=>caf(frame.current),[]);

 // Jump to a day, loading enough days around it first so it never lands at an edge.
 const goTo=(day:string,smooth=true)=>{const i=idx(day);const pad=FIT[scale]*2;
  const before=i<pad?pad-i:0,after=i+pad>range.days?i+pad-range.days:0;
  if(before)pending.current.shift=before;
  pending.current.focus=day;pending.current.smooth=smooth&&!before;
  setRange(r=>({start:addDays(r.start,-before),days:r.days+before+after}))};
 const page=(dir:1|-1)=>{const el=body.current;if(el)el.scrollBy({left:dir*el.clientWidth*.85,behavior:'smooth'})};
 const todayIdxNow=diff(range.start,asOf);
 const setScale=(s:TimelineScale)=>{const todayInView=todayIdxNow>=visible.from&&todayIdxNow<=visible.to;const centre=addDays(range.start,Math.round((visible.from+visible.to)/2));
  // Zoom around today when it is on screen, otherwise around whatever the user was looking at.
  pending.current.focus=todayInView?asOf:addDays(centre,-Math.round(FIT[s]/4));setScaleState(s);
  try{if(storageKey)localStorage.setItem(storageKey,s)}catch{/* storage blocked: keep for this visit */}};

 const span=(r:TaskRow)=>{
  const due=r.t.due_date?.slice(0,10);if(!due)return null;
  const start=r.t.start_date?.slice(0,10)||due;
  const end=isLate(r.t,asOf)&&asOf>due?asOf:due;
  return {start,end,due};
 };
 const placed=rows.flatMap(r=>{const s=span(r);return s?[{r,s,tone:(r.t.status==='completed'?'done':laneOf(r,asOf)) as Tone}]:[]});
 const undated=rows.filter(r=>r.t.status!=='completed'&&!r.t.due_date);
 const showOwner=groupBy==='case'&&new Set(placed.map(x=>x.r.t.owner_id)).size>1;
 const keyOf=(r:TaskRow)=>groupBy==='person'?r.t.owner_id||'':r.p.id;
 const groups=[...new Set(placed.map(x=>keyOf(x.r)))].map(key=>{
  const items=placed.filter(x=>keyOf(x.r)===key).sort((a,b)=>RANK[a.tone]-RANK[b.tone]||a.s.due.localeCompare(b.s.due));
  return {key,items,late:items.filter(x=>x.tone==='late').length,blocked:items.filter(x=>x.tone==='blocked').length};
 }).sort((a,b)=>b.late-a.late||b.blocked-a.blocked||b.items.length-a.items.length);

 const groupLabel=(key:string,sample:TaskRow)=>{
  if(groupBy==='person'){const u=c.w.users.find(x=>x.id===key);return <><Avatar small user={u}/><strong>{nameOf(c.w,key)}</strong>{u?.department&&<small>{u.department}</small>}</>}
  return <><strong>{sample.p.code}</strong><small>{sample.p.name}</small></>;
 };
 // Bars only say what the list cannot: how late, what blocks, or that the deadline falls this week.
 const barText=(x:typeof placed[number])=>x.tone==='late'?`逾期 ${elapsed(x.s.due,asOf)} 天`:x.tone==='blocked'?taskReadiness(x.r,c)||'受阻':x.tone==='week'?'本週到期':x.tone==='done'?'已完成':'';
 const node=(r:TaskRow)=>NODE_NAMES[r.n.key]||r.n.name;
 const meta=(x:typeof placed[number])=>`${groupBy==='person'?`${x.r.p.code} · `:''}${node(x.r)}`;

 // Month bands and merged runs of non-working days, so the background costs a handful of elements, not one per cell.
 const months=days.reduce<{key:string;label:string;from:number;n:number}[]>((acc,d,i)=>{const key=d.slice(0,7);const tail=acc[acc.length-1];if(tail?.key===key)tail.n++;else acc.push({key,label:`${d.slice(0,4)} 年 ${Number(d.slice(5,7))} 月`,from:i,n:1});return acc},[]);
 const offRuns=days.reduce<{from:number;n:number}[]>((acc,d,i)=>{if(!isOff(d))return acc;const tail=acc[acc.length-1];if(tail&&tail.from+tail.n===i)tail.n++;else acc.push({from:i,n:1});return acc},[]);
 const todayIdx=idx(asOf);
 const vFrom=days[visible.from]||range.start,vTo=days[Math.min(visible.to,days.length-1)]||last;
 const title=vFrom.slice(0,7)===vTo.slice(0,7)?`${vFrom.slice(0,4)} 年 ${Number(vFrom.slice(5,7))} 月`:`${vFrom.slice(0,4)} 年 ${Number(vFrom.slice(5,7))} 月 – ${vFrom.slice(0,4)===vTo.slice(0,4)?'':`${vTo.slice(0,4)} 年 `}${Number(vTo.slice(5,7))} 月`;
 const todayInView=todayIdx>=visible.from&&todayIdx<=visible.to;
 const width=days.length*col;

 return <div className={`tl scale-${scale} ${showOwner?'with-owner':''}`} style={{['--tl-colw' as string]:`${col}px`}}>
  <div className="tl-toolbar">
   <strong className="tl-range">{title}</strong>
   <div className="tl-legend" aria-label="顏色說明">{TONES.map(([k,t])=><span key={k} className={`tone-${k}`}><i aria-hidden="true"/>{t}</span>)}</div>
   <div className="tl-nav">
    {undated.length>0&&<button type="button" className="button compact" aria-expanded={showUndated} onClick={()=>setShowUndated(!showUndated)}><CalendarOff size={15}/>未排定 ({undated.length})</button>}
    <Segmented label="縮放" options={SCALES} value={scale} onChange={setScale}/>
    <span className="tl-step">
     <button type="button" className="icon-button" onClick={()=>page(-1)} aria-label="往前捲動"><ChevronLeft size={17}/></button>
     <button type="button" className="button compact" disabled={todayInView} onClick={()=>goTo(asOf)}>今天</button>
     <button type="button" className="icon-button" onClick={()=>page(1)} aria-label="往後捲動"><ChevronRight size={17}/></button>
    </span>
   </div>
  </div>
  {showUndated&&<ul className="tl-undated" aria-label="未排定期限的任務">{undated.map(r=><li key={r.t.id}><button type="button" onClick={()=>openTask(c,r)}><TaskIcon status={r.t.status}/><strong>{r.t.title}</strong><small>{r.p.code} · {node(r)} · {nameOf(c.w,r.t.owner_id)}</small></button></li>)}</ul>}

  <div className="tl-sheet">
   <div className="tl-head">
    <div className="tl-list tl-cols tl-cols-head"><span>任務</span>{showOwner&&<span>負責人</span>}</div>
    <div className="tl-head-scroll" ref={head}>
     <div className="tl-months" style={{width}}>{months.map(m=><span key={m.key} style={{left:m.from*col,width:m.n*col}}><b>{m.label}</b></span>)}</div>
     <div className="tl-days" style={{width}}>{offRuns.map(o=><i key={o.from} className="tl-off" style={{left:o.from*col,width:o.n*col}}/>)}{days.map((d,i)=><div key={d} className={`tl-day ${d===asOf?'today':''} ${isOff(d)?'off':''} ${d.slice(8)==='01'?'month-start':''}`} style={{left:i*col}} title={`${d.replaceAll('-','/')} 週${WEEKDAY[weekday(d)]}`}>{scale!=='month'&&<span>{WEEKDAY[weekday(d)]}</span>}<strong>{Number(d.slice(8))}</strong></div>)}</div>
    </div>
   </div>
   {!groups.length?<p className="tl-empty">沒有排定期限的任務</p>:<div className="tl-body">
    <div className="tl-list">
     {groups.map(g=>{const open=!closed[g.key];return <div key={g.key} className="tl-group">
      <button type="button" className="tl-group-head" aria-expanded={open} onClick={()=>setClosed(s=>({...s,[g.key]:open}))}>
       {open?<ChevronDown size={16}/>:<ChevronRight size={16}/>}
       <span className="tl-group-name">{groupLabel(g.key,g.items[0].r)}</span>
       <span className="tl-group-count">{g.items.length}</span>
       {g.late>0&&<em className="tl-chip tone-late">逾期 {g.late}</em>}
       {g.blocked>0&&<em className="tl-chip tone-blocked">受阻 {g.blocked}</em>}
      </button>
      {open&&g.items.map(x=><button type="button" key={x.r.t.id} className={`tl-row tl-cols tone-${x.tone}`} onClick={()=>openTask(c,x.r)}>
       <span className="tl-name"><TaskIcon status={x.r.t.status}/><span><strong title={x.r.t.title}>{x.r.t.title}</strong><small>{meta(x)} · <b className={x.tone==='late'?'is-late':''}>{shortDate(x.s.due)} 到期</b></small></span></span>
       {showOwner&&<span className="tl-owner"><Avatar small user={c.w.users.find(u=>u.id===x.r.t.owner_id)}/><span>{nameOf(c.w,x.r.t.owner_id)}</span></span>}
      </button>)}
     </div>})}
    </div>
    <div className="tl-body-scroll" ref={body} onScroll={onScroll} tabIndex={0} aria-label="時間軸，可左右捲動，會持續載入更多日期">
     <div className="tl-tracks" style={{width}}>
      <div className="tl-shade" aria-hidden="true">{offRuns.map(o=><i key={o.from} className="tl-off" style={{left:o.from*col,width:o.n*col}}/>)}{todayIdx>=0&&todayIdx<days.length&&<i className="tl-today" style={{left:todayIdx*col+col/2}}/>}</div>
      {groups.map(g=>{const open=!closed[g.key];return <div key={g.key} className="tl-group">
       <div className="tl-group-track" aria-hidden="true"/>
       {open&&g.items.map(x=>{
        const from=Math.max(0,idx(x.s.start)),to=Math.min(days.length-1,idx(x.s.end));
        const shown=to>=0&&from<=days.length-1&&to>=from;
        const before=shown?to<visible.from:idx(x.s.end)<0,after=shown?from>visible.to:idx(x.s.start)>days.length-1;
        const text=barText(x);
        return <div key={x.r.t.id} className={`tl-track tone-${x.tone}`}>
         {shown&&<button type="button" className={`tl-bar ${idx(x.s.start)<0?'cut-start':''} ${idx(x.s.end)>days.length-1?'cut-end':''}`} style={{left:from*col+3,width:Math.max(col-6,(to-from+1)*col-6)}} onClick={()=>openTask(c,x.r)} title={`${x.r.t.title}｜${shortDate(x.s.start)} → ${shortDate(x.s.due)}${text?`｜${text}`:''}`}>{text&&<span>{text}</span>}</button>}
         {/* Off-screen bars leave a pointer at the visible edge so an empty row never looks unscheduled. */}
         {before&&<button type="button" className="tl-edge left" style={{left:visible.from*col+4}} onClick={()=>goTo(x.s.start)}><ChevronLeft size={13}/>{shortDate(x.s.due)}</button>}
         {after&&<button type="button" className="tl-edge right" style={{left:(visible.to+1)*col-4}} onClick={()=>goTo(x.s.start)}>{shortDate(x.s.start)}<ChevronRight size={13}/></button>}
        </div>})}
      </div>})}
     </div>
    </div>
   </div>}
  </div>
 </div>;
}

export default TaskTimeline;
