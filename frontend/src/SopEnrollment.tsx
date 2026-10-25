import {useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import {Button, Sheet} from './design';
import {sopApi, sopErrorText, type SopEnrollment, type SopNodeKey} from './sopTaskApi';

export function enrollmentLabel(enrollment:SopEnrollment) {
 if(enrollment.policy==='legacy') return '舊案 · 維持原流程';
 if(enrollment.policy==='needs_review') return '案件待核對';
 const attempt=enrollment.attempt;
 if(attempt?.status==='succeeded') return `已自動帶入 ${attempt.createdCount} 項`;
 if(attempt?.lastError==='template_unavailable') return '範本尚未發布';
 if(attempt?.status==='failed') return '帶入失敗';
 if(attempt?.lastError==='import_unavailable') return '任務帶入尚未開放';
 return '等待自動帶入';
}

export function SopEnrollmentStatus({projectId,enrollment,current,reload,startLabel}:{projectId:string;enrollment:SopEnrollment;current:()=>boolean;reload:()=>Promise<void>;startLabel?:string}) {
 const [open,setOpen]=useState(false),[confirm,setConfirm]=useState(false),[keys,setKeys]=useState<SopNodeKey[]>([]);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const run=async(optIn:boolean)=>{
  if(busy)return;
  setBusy(true);setError('');
  try {
   if(optIn) await sopApi.optIn(projectId,keys,current);
   else if(enrollment.attempt) await sopApi.retryEnrollment(projectId,enrollment.attempt.id,current);
   if(current()){setOpen(false);await reload()}
  } catch(e){if(current())setError(sopErrorText(e))}
  finally{if(current())setBusy(false)}
 };
 return <div className="sop-enrollment">
  <span role="status" className="sop-muted">{enrollmentLabel(enrollment)}</span>
  {enrollment.canRetry && enrollment.attempt && enrollment.attempt.status!=='succeeded' && <Button variant="plain" disabled={busy} onClick={()=>void run(false)}>重試</Button>}
  {enrollment.canOptIn && <Button variant={startLabel?'primary':'plain'} onClick={()=>{setKeys(enrollment.nodes.filter(n=>n.eligible).map(n=>n.key));setConfirm(false);setOpen(true)}}>{startLabel||'套用 SOP 到剩餘節點'}</Button>}
  {error && <p role="alert">{error}</p>}
  {open && createPortal(<Sheet title="套用 SOP 到剩餘節點" onClose={()=>{if(!busy)setOpen(false)}}>
   <div className="sop-form sop-enroll-form">
    <p>選擇尚未開始的節點。已開始或已完成的節點維持原流程。</p>
    <fieldset disabled={busy}><legend>套用節點</legend>{enrollment.nodes.map(n=><label key={n.key}>
     <input type="checkbox" checked={keys.includes(n.key)} disabled={!n.eligible} onChange={e=>{setConfirm(false);setKeys(old=>e.target.checked?[...old,n.key]:old.filter(k=>k!==n.key))}}/>
     {n.name}{!n.eligible && ' · 維持原流程'}
    </label>)}</fieldset>
    <label><input type="checkbox" checked={confirm} disabled={busy} onChange={e=>setConfirm(e.target.checked)}/>確認將 SOP 任務帶入所選的 {keys.length} 個節點，之後再指派人員。</label>
    <div className="sop-sheet-actions"><Button onClick={()=>setOpen(false)} disabled={busy}>取消</Button><Button variant="primary" disabled={!confirm||keys.length===0||busy} disabledReason="請選擇節點並勾選確認" onClick={()=>void run(true)}>{busy?'套用中…':'確認套用'}</Button></div>
   </div>
  </Sheet>,document.body)}
 </div>;
}

const policyLabel={legacy:'舊案',managed:'已納管',needs_review:'待核對'};
type Readiness=Awaited<ReturnType<typeof sopApi.readiness>>;
type Read={kind:'loading'}|{kind:'error'}|{kind:'ready';items:Readiness};
export function SopReadiness() {
 const [read,setRead]=useState<Read>({kind:'loading'}),[revision,setRevision]=useState(0),[filter,setFilter]=useState('all');
 const [busy,setBusy]=useState(''),[error,setError]=useState('');
 useEffect(()=>{const abort=new AbortController();void sopApi.readiness(abort.signal).then(items=>{if(!abort.signal.aborted)setRead({kind:'ready',items})}).catch(()=>{if(!abort.signal.aborted)setRead({kind:'error'})});return()=>abort.abort()},[revision]);
 const retry=async(projectId:string,id:string)=>{
  setBusy(id);setError('');
  try {await sopApi.retryEnrollment(projectId,id,()=>true);setRevision(v=>v+1)}catch(e){setError(sopErrorText(e))}finally{setBusy('')}
 };
 const items=read.kind==='ready'?read.items.filter(c=>filter==='all'||c.policy===filter||filter==='pending'&&c.enrollments.some(e=>e.status!=='succeeded')):[];
 return <section className="so-card sop-readiness" aria-label="SOP 帶入狀態">
  <div className="so-card-header"><h3>SOP 帶入狀態</h3><Button variant="plain" onClick={()=>setRevision(v=>v+1)}>重新讀取</Button></div>
  <label>案件範圍 <select value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部案件</option><option value="legacy">舊案</option><option value="managed">已納管</option><option value="needs_review">待核對</option><option value="pending">等待或帶入失敗</option></select></label>
  {read.kind==='loading'&&<p role="status">讀取中…</p>}{read.kind==='error'&&<p role="alert">目前無法讀取，請重新讀取。</p>}{error&&<p role="alert">{error}</p>}
  {read.kind==='ready'&&<><p className="sop-muted">共 {items.length} 案</p><ul className="sop-readiness-list">{items.map(c=><li key={c.projectId}>
   <div><strong>{c.code} {c.name}</strong><span className="sop-muted">{policyLabel[c.policy]}</span></div>
   {c.enrollments.map(e=><div key={e.id}><span>{e.status==='succeeded'?`已帶入 ${e.createdCount} 項`:e.lastError==='template_unavailable'?'範本尚未發布':e.status==='failed'?'帶入失敗':'等待帶入'} · 已嘗試 {e.attempts} 次</span>{e.status!=='succeeded'&&<Button variant="plain" disabled={!!busy} onClick={()=>void retry(c.projectId,e.id)}>{busy===e.id?'處理中…':'重試'}</Button>}</div>)}
  </li>)}</ul>{items.length===0&&<p className="sop-muted">目前沒有符合的案件。</p>}</>}
 </section>;
}
