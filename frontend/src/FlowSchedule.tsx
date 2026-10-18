import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {getSessionEpoch} from './api';
import {Button,Sheet} from './design';
import {canWriteDispatch} from './dispatchAccess';
import {DispatchPublishDialog,type DispatchFlow} from './DispatchPublishDialog';
import {dispatchPaths,dispatchRequest,normalizeProposal,parseWork,readLocalDrafts,type SavedDraft,type WorkRow} from './dispatchPublishModel';
import {nodeDispatchProposal,productionKey,type FlowNode} from './flowModel';
import type {Project,Session} from './types';
import {FlowAction} from './FlowActions';
import './DispatchBoard.css';
import './DispatchPublish.css';
let parentEpoch=getSessionEpoch();
const parentCache=new Map<string,{rows:WorkRow[];at:number}>();
async function readParents(projectId:string,signal:AbortSignal){
 const epoch=getSessionEpoch();if(parentEpoch!==epoch){parentCache.clear();parentEpoch=epoch}
 const cached=parentCache.get(projectId);if(cached && Date.now()-cached.at<60000)return cached.rows;
 const work=parseWork(await dispatchRequest(dispatchPaths.work(new URLSearchParams({scope:'all'})),signal));
 if(work.states.some(s=>['forbidden','read_failed'].includes(s)))throw Error('父義務來源暫不可用，請重試。');
 if(!signal.aborted && epoch===getSessionEpoch())parentCache.set(projectId,{rows:work.rows,at:Date.now()});
 return work.rows;
}
export function FlowSchedule({project,node,session,onPublished}:{project:Project;node:FlowNode;session:Session;onPublished:()=>void}){
 const [flow,setFlow]=useState<DispatchFlow>();
 const [parents,setParents]=useState<WorkRow[]>();
 const [loading,setLoading]=useState(false),[error,setError]=useState('');
 const controller=useRef<AbortController>();
 useEffect(()=>()=>controller.current?.abort(),[]);
 const save=(draft:SavedDraft)=>{const key=`yx:dispatch-drafts:${session.workspace_id}:${session.user?.id}`;try{localStorage.setItem(key,JSON.stringify([draft,...readLocalDrafts(localStorage.getItem(key)).filter(d=>d.draft_id!==draft.draft_id)]))}catch{setError('瀏覽器儲存空間不可用，請確認伺服器草稿已儲存。')}};
 const open=(parent:WorkRow)=>{setParents(undefined);setFlow({action:'new',proposal:normalizeProposal({...nodeDispatchProposal({project,node,parentTaskId:parent.task_id}),project_ref:parent.project_id,case_ref:parent.case.ref,package_id:parent.package_id,department:parent.department})})};
 const load=async()=>{
  if(loading)return;const request=new AbortController();controller.current=request;setLoading(true);setError('');
  try{
   const rows=await readParents(project.id,request.signal);
   const candidates=rows.filter(r=>r.kind==='obligation' && r.source==='v4_task' && (r.project_id===project.id || typeof project.project_ref==='string' && r.project_id===project.project_ref) && node.departments.includes(r.department) && (r.node_position===node.label || r.node_position.startsWith(node.label+'（') || r.node_position.startsWith(node.label+' ')) && !['已完成','取消'].includes(r.status));
   if(candidates.length===1)open(candidates[0]);else setParents(candidates);
  }catch(failure){if(!request.signal.aborted)setError(failure instanceof Error ? failure.message : '派工來源讀取失敗。')}
  finally{if(!request.signal.aborted)setLoading(false)}
 };
 if(!canWriteDispatch(session) || !productionKey(node.key))return null;
 return <><FlowAction allowed={!loading} reason="正在讀取父義務。" onClick={()=>void load()}>{loading ? '讀取排班…' : '排班'}</FlowAction>
 {error && <p role="alert">{error}<Button onClick={()=>void load()}>重試排班來源</Button></p>}
 {parents && createPortal(<Sheet title="選擇排班的父義務" onClose={()=>{controller.current?.abort();setParents(undefined)}}><div className="pf-inspector">{parents.length ? parents.map(parent=><Button key={parent.task_id} onClick={()=>open(parent)}>{parent.title} · {parent.department}</Button>) : <><p>此節點尚無可核實的父義務，請先在派工工作流程建立義務，再回來排班。</p><Button onClick={()=>setParents(undefined)}>返回流程</Button></>}</div></Sheet>,document.body)}
 {flow && createPortal(<DispatchPublishDialog flow={flow} session={session} onClose={()=>setFlow(undefined)} onSaved={save} onPublished={()=>{parentCache.delete(project.id);onPublished()}}/>,document.body)}</>;
}
