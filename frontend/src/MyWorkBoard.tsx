import {useState} from 'react';
import {ChevronDown, ChevronRight} from 'lucide-react';
import {Ctx,TaskRow,NODE_NAMES,TaskIcon,active,elapsed,isLate,nameOf,openTask,operationallyBlocked,progress,shortDate,taskReadiness} from './appCommon';
import {Avatar} from './AppShell';
import './MyWorkBoard.css';

type Lane='late'|'blocked'|'week'|'later';
const LANES:[Lane,string][]=[['late','逾期'],['blocked','受阻'],['week','本週到期'],['later','之後']];

const day=(value:string,offset:number)=>{const d=new Date(value.slice(0,10)+'T12:00:00');d.setDate(d.getDate()+offset);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};

// Lanes answer "what first": overdue beats blocked, so a late blocked task still shows as late with its blocker on the card.
export function laneOf(r:TaskRow,asOf:string):Lane{
 if(isLate(r.t,asOf))return 'late';
 if(operationallyBlocked(r))return 'blocked';
 return r.t.due_date&&r.t.due_date.slice(0,10)<=day(asOf,7)?'week':'later';
}

export function MyWorkBoard({c,rows,showOwner}:{c:Ctx;rows:TaskRow[];showOwner:boolean}){
 const[showDone,setShowDone]=useState(false);
 const asOf=c.w.as_of;
 const open=rows.filter(r=>active(r.t));
 const lanes=LANES.map(([key,label])=>({key,label,rows:open.filter(r=>laneOf(r,asOf)===key)}));
 const weekStart=day(asOf,-6);
 const done=rows.filter(r=>r.t.status==='completed'&&(r.t.completed_at||'').slice(0,10)>=weekStart).sort((a,b)=>(b.t.completed_at||'').localeCompare(a.t.completed_at||''));
 const card=(r:TaskRow,lane:Lane|'done')=>{
  const reason=lane==='blocked'||lane==='late'?(operationallyBlocked(r)?taskReadiness(r,c)||'受阻':''):'';
  const pct=progress(r.p);
  return <button type="button" key={r.t.id} className="mwb-card" onClick={()=>openTask(c,r)}>
   <span className="mwb-title"><TaskIcon status={r.t.status}/><strong>{r.t.title}</strong></span>
   <small className="mwb-meta"><span>{r.p.code} · {NODE_NAMES[r.n.key]||r.n.name}</span><span>{lane==='done'?`${shortDate(r.t.completed_at as string)} 完成`:r.t.due_date?`${shortDate(r.t.due_date)} 到期`:'未排定'}</span></small>
   {(lane==='late'||reason)&&<span className="mwb-tags">
    {lane==='late'&&<em className="mwb-tag critical">逾期 {elapsed(r.t.due_date,asOf)} 天</em>}
    {reason&&<em className="mwb-tag warning">{reason}</em>}
   </span>}
   <span className="mwb-foot">
    <span className="mwb-progress" title={`案件 ${r.p.code} 任務完成度 ${pct}%`}><i><b style={{width:`${pct}%`}}/></i>案件 {pct}%</span>
    {showOwner&&<span className="mwb-owner"><Avatar small user={c.w.users.find(u=>u.id===r.t.owner_id)}/>{nameOf(c.w,r.t.owner_id)}</span>}
   </span>
  </button>;
 };
 return <div className="mwb-scroll" tabIndex={0} aria-label="任務看板，可左右捲動">
  <div className="mwb-board">
   {lanes.map(l=><section key={l.key} className={`mwb-lane lane-${l.key}${l.rows.length?'':' is-empty'}`} aria-label={`${l.label} ${l.rows.length} 項`}>
    <header><i aria-hidden="true"/><h2>{l.label}</h2><span>{l.rows.length}</span></header>
    <div className="mwb-cards">{l.rows.map(r=>card(r,l.key))}{!l.rows.length&&<p className="mwb-empty">沒有任務</p>}</div>
   </section>)}
   <section className={`mwb-lane lane-done ${showDone?'':'collapsed'}`} aria-label={`本週已完成 ${done.length} 項`}>
    <header><button type="button" aria-expanded={showDone} onClick={()=>setShowDone(!showDone)}><i aria-hidden="true"/><h2>本週已完成</h2><span>{done.length}</span>{showDone?<ChevronDown size={15}/>:<ChevronRight size={15}/>}</button></header>
    {showDone&&<div className="mwb-cards">{done.map(r=>card(r,'done'))}{!done.length&&<p className="mwb-empty">本週尚無完成</p>}</div>}
   </section>
  </div>
 </div>;
}
