import {useEffect,useRef,useState} from 'react';
import {Button} from './design';
import {getSessionEpoch} from './api';
import {DispatchBoardFrame,useDispatchBoardRead} from './DispatchBoard';
import {canReadDispatch,canWriteDispatch} from './dispatchAccess';
import {addDays,dispatchWeek,type DispatchSlot} from './dispatchBoardModel';
import type {DispatchProject} from './dispatchLinks';
import {DispatchWork} from './DispatchWork';
import {DispatchPublishDialog,type DispatchFlow} from './DispatchPublishDialog';
import {dispatchPaths,dispatchRequest,normalizeProposal,parseDraft,parseDrafts,readLocalDrafts,type Action,type SavedDraft,type WorkRow} from './dispatchPublishModel';
import type {Session} from './types';
import './DispatchPublish.css';

export function DispatchWorkflowPage({projects=[],session}:{projects?:DispatchProject[];session:Session}) {
 const [from,setFrom]=useState(dispatchWeek),[tab,setTab]=useState(new URLSearchParams(location.hash.slice(1)).get('tab')==='work'?'work':'board');
 const allowed=canReadDispatch(session),write=canWriteDispatch(session);
 if(!allowed)return <p>目前沒有派工看板權限。</p>;
 return <DispatchWorkspace key={`${getSessionEpoch()}:${from}`} session={session} projects={projects} from={from} setFrom={setFrom} tab={tab} setTab={setTab} write={write}/>;
}

function DispatchWorkspace({session,projects,from,setFrom,tab,setTab,write}:{session:Session;projects:DispatchProject[];from:string;setFrom:(v:string)=>void;tab:string;setTab:(v:string)=>void;write:boolean}){
 const read=useDispatchBoardRead(from),[flow,setFlow]=useState<DispatchFlow>(),[version,setVersion]=useState(0),[message,setMessage]=useState('');
 const storageKey=`yx:dispatch-drafts:${session.workspace_id}:${session.user?.id}`;
 const [drafts,setDrafts]=useState<SavedDraft[]>(()=>{try{return readLocalDrafts(localStorage.getItem(storageKey))}catch{return []}});
 const requests=useRef(new Set<AbortController>());
 useEffect(()=>()=>{requests.current.forEach(c=>c.abort())},[]);

 const save=(draft:SavedDraft)=>{
  setDrafts(previous=>{
   const next=[draft,...previous.filter(d=>d.draft_id!==draft.draft_id)];
   try{localStorage.setItem(storageKey,JSON.stringify(next))}catch{setMessage('瀏覽器儲存空間不可用，請確認伺服器草稿已儲存。')}
   return next;
  });
 };

 const run=async(work:(signal:AbortSignal)=>Promise<void>)=>{
  const c=new AbortController();
  requests.current.add(c);
  try{await work(c.signal)}catch(e){if(!c.signal.aborted)setMessage(e instanceof Error?e.message:'操作未完成。')}
  finally{requests.current.delete(c)}
 };

 const reloadDrafts=()=>void run(async signal=>{
  const remote=parseDrafts(await dispatchRequest(dispatchPaths.drafts,signal));
  setDrafts(previous=>[...new Map([...previous,...remote.map(d=>previous.find(local=>local.draft_id===d.draft_id&&local.command_id)||d)].map(d=>[d.draft_id,d])).values()]);
  setMessage('已重新讀取伺服器草稿。');
 });

 const create=(slot?:DispatchSlot)=>setFlow({
  action:'new',
  proposal:normalizeProposal({
   title:slot?.work_content??'',
   project_ref:'',
   case_ref:slot?.case.ref??'',
   kind:'execution',
   start:`${slot?.interval.start?.slice(0,10)||from}T08:00:00+08:00`,
   end:`${slot?.interval.start?.slice(0,10)||from}T12:00:00+08:00`,
   instruments:slot?.resources.filter(r=>r.kind==='instrument').map(r=>r.ref)??[],
   vehicles:slot?.resources.filter(r=>r.kind==='vehicle').map(r=>r.ref)??[]
  })
 });

 const rowAction=(row:WorkRow,action:Action)=>{
  if((!write&&!['approve','return'].includes(action))||action!=='review_preview'&&!row.allowed_actions.includes(action))return;
  if(action==='approve'||action==='return'||action==='review_preview'){if(!row.preview_id){setMessage('此工作尚未提供可操作預覽，請更新工作進度。');return}setFlow({action,proposal:normalizeProposal({}),row});return}
  if(action==='reconcile'&&row.command&&session.user?.role==='manager'){setFlow({action,proposal:normalizeProposal({}),row});return}
  if(action==='cancel_draft')void run(async signal=>{await dispatchRequest(dispatchPaths.draft(row.draft_id),signal,undefined,'DELETE');setVersion(v=>v+1);setDrafts(previous=>{const next=previous.filter(d=>d.draft_id!==row.draft_id);try{localStorage.setItem(storageKey,JSON.stringify(next))}catch{}return next});setMessage('草稿已取消。')});
 };

 return <div className="dp-page">
  <nav className="dp-tabs" aria-label="派工檢視">
   <div className="dp-tab-group">
    <Button aria-pressed={tab==='board'} onClick={()=>setTab('board')}>派工看板</Button>
    <Button aria-pressed={tab==='work'} onClick={()=>setTab('work')}>工作進度</Button>
   </div>
   {write&&<Button variant="primary" onClick={()=>create()}>新增排班</Button>}
  </nav>

  {write&&<details className="dp-drafts glass--flat">
   <summary>草稿 · {drafts.length} 件</summary>
   <div className="dp-drafts-body">
    <p className="db-muted">草稿不占用容量。重新開啟後，請重新核對資料與預覽有效期限。</p>
    <Button onClick={reloadDrafts}>重新讀取草稿</Button>
    {drafts.length>0&&<div className="dp-drafts-list">
     {drafts.map(d=><div key={d.draft_id}>
      <Button onClick={()=>void run(async signal=>{let current=d;if(d.version!==undefined&&!d.command_id&&!d.preview_id){const remote=parseDraft(await dispatchRequest(dispatchPaths.draft(d.draft_id),signal));current={...remote,preview_id:d.preview_id,command_id:d.command_id}}setFlow({action:current.proposal.task_id?'edit_detail':'new',proposal:current.proposal,draft:current})})}>{d.proposal.title||'未命名草稿'} · {d.saved_at||'時間未提供'}</Button>
     </div>)}
    </div>}
   </div>
  </details>}

  <p className="dp-live" role="status">{message}</p>

  {tab==='board'?<DispatchBoardFrame from={from} read={read} onWeek={setFrom} projects={projects} onAssign={write?create:undefined}/>:<><div className="dp-week"><Button onClick={()=>setFrom(addDays(from,-7))}>上一週</Button><span>{from} ～ {addDays(from,6)}</span><Button onClick={()=>setFrom(addDays(from,7))}>下一週</Button></div><DispatchWork refreshVersion={version} from={from} write={write} onProposal={(proposal,row,action)=>{if(row.draft_id)void run(async signal=>{const draft=parseDraft(await dispatchRequest(dispatchPaths.draft(row.draft_id),signal));setFlow({proposal:draft.proposal,row,action,draft})});else setFlow({proposal,row,action})}} onAction={rowAction}/></>}
  {flow&&<DispatchPublishDialog flow={flow} session={session} onSaved={save} onClose={()=>setFlow(undefined)} onPublished={()=>{read.reload();setVersion(v=>v+1)}}/>}
 </div>;
}
