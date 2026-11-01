import {useCallback,useEffect,useId,useRef,useState,type ReactNode} from 'react';
import {Button} from '../design';
import {listConversations,openConversation,deleteConversation,relativeTime,type ConversationDetail,type HistoryPage,type HistoryScope} from './history';

type HistoryState={status:'loading'}|{status:'error'}|{status:'ready';page:HistoryPage};
type Props={projectId?:string;compact?:boolean;revision:number;activeId:string;onOpen:(detail:ConversationDetail)=>void;onNew:()=>void;beforeDelete?:()=>Promise<void>;children:ReactNode};
export function ConversationHistory({projectId,compact,revision,activeId,onOpen,onNew,beforeDelete,children}:Props){
 const [state,setState]=useState<HistoryState>({status:'loading'}),[attempt,setAttempt]=useState(0);
 const [mobile,setMobile]=useState(()=>window.matchMedia?.('(max-width: 760px)').matches??false);
 const [expanded,setExpanded]=useState(!compact&&!mobile),[confirm,setConfirm]=useState<string>(),[busy,setBusy]=useState(false),[actionError,setActionError]=useState('');
 const [retry,setRetry]=useState<(()=>void)>();
 const listGeneration=useRef(0);
 const action=useRef<AbortController>(),list=useRef<AbortController>();
 const trigger=useRef<HTMLButtonElement>(null),dialog=useRef<HTMLDialogElement>(null),panel=useRef<HTMLElement>(null);
 const id=useId(),overlay=!!compact||mobile;
 const scope:HistoryScope=projectId?{scope:'project',project_id:projectId}:{scope:'global'};
 useEffect(()=>{
  const media=window.matchMedia?.('(max-width: 760px)');if(!media)return;
  const change=()=>setMobile(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change);
 },[]);
 useEffect(()=>{
  ++listGeneration.current;list.current?.abort();const controller=new AbortController();list.current=controller;
  listConversations(scope,undefined,controller.signal).then(page=>{if(!controller.signal.aborted)setState({status:'ready',page})}).catch(()=>{if(!controller.signal.aborted)setState({status:'error'})});
  return()=>controller.abort();
 },[projectId,revision,attempt]);
 useEffect(()=>()=>action.current?.abort(),[]);
 useEffect(()=>{action.current?.abort();setBusy(false);setActionError('');setRetry(undefined)},[activeId]);
 const unavailable=state.status==='ready'&&!state.page.history_available;
 useEffect(()=>{
  if(!expanded||unavailable)return;
  if(overlay)dialog.current?.showModal();
  else panel.current?.querySelector<HTMLButtonElement>('button')?.focus();
  return()=>{dialog.current?.close();trigger.current?.focus()};
 },[expanded,overlay,unavailable]);
 const close=()=>{setExpanded(false);setConfirm(undefined)};
 const fresh=()=>{action.current?.abort();setBusy(false);setActionError('');setRetry(undefined);setConfirm(undefined);onNew();if(overlay)close()};
 const perform=useCallback(async(work:(signal:AbortSignal)=>Promise<void>,again:()=>void)=>{
  action.current?.abort();const controller=new AbortController();action.current=controller;setBusy(true);setActionError('');setRetry(undefined);
  try{await work(controller.signal)}catch{if(!controller.signal.aborted){setActionError('操作未完成，請重試。');setRetry(()=>again)}}finally{if(!controller.signal.aborted)setBusy(false)}
 },[]);
 const open=(conversationId:string)=>void perform(async signal=>{
  const detail=await openConversation(conversationId,signal);if(signal.aborted)return;
  if(detail.scope!==scope.scope||(projectId&&detail.project_id!==projectId))throw new Error('scope');
  onOpen(detail);setConfirm(undefined);if(overlay)close();
 },()=>open(conversationId));
 const remove=(conversationId:string)=>void perform(async signal=>{
  if(activeId===conversationId)await beforeDelete?.();
  if(signal.aborted)return;
  await deleteConversation(conversationId,signal);if(signal.aborted)return;
  setState(previous=>previous.status==='ready'?{status:'ready',page:{...previous.page,items:previous.page.items.filter(item=>item.id!==conversationId)}}:previous);
  setConfirm(undefined);if(activeId===conversationId)onNew();setAttempt(n=>n+1);
 },()=>remove(conversationId));
 const more=()=>{
  if(state.status!=='ready'||!state.page.next_cursor)return;
  const page=state.page,generation=listGeneration.current;
  void perform(async signal=>{const next=await listConversations(scope,page.next_cursor!,signal);if(signal.aborted||generation!==listGeneration.current)return;
   setState(previous=>previous.status!=='ready'?previous:{status:'ready',page:{...next,items:[...new Map([...previous.page.items,...next.items].map(item=>[item.id,item])).values()]}});
  },more);
 };
 const content=<>
  <div className="assistant-history-heading"><h2 id={`${id}-title`}>對話紀錄</h2><Button variant="plain" onClick={close} aria-label="關閉對話紀錄">關閉</Button></div>
  <Button onClick={fresh}>新對話</Button>
  {state.status==='loading'?<p role="status">正在載入對話…</p>:state.status==='error'?<p role="alert">無法載入對話紀錄。<Button onClick={()=>setAttempt(n=>n+1)}>重新載入紀錄</Button></p>:<>
   {state.page.items.length===0?<p>尚無對話紀錄</p>:<ul className="assistant-history-list">{state.page.items.map(item=><li key={item.id}>
    <div className="assistant-history-row"><Button variant="plain" className="assistant-history-open" disabled={busy} aria-current={activeId===item.id?'true':undefined} onClick={()=>open(item.id)}><span>{item.title||'未命名對話'}</span><time dateTime={item.updated_at} title={new Date(item.updated_at).toLocaleString('zh-TW')}>{relativeTime(item.updated_at)}</time></Button><Button variant="plain" disabled={busy} aria-label={`刪除對話：${item.title}`} onClick={()=>setConfirm(item.id)}>刪除</Button></div>
    {confirm===item.id&&<div className="assistant-history-confirm"><span>確定刪除此對話？</span><Button disabled={busy} variant="destructive" onClick={()=>remove(item.id)}>確定刪除</Button><Button disabled={busy} onClick={()=>setConfirm(undefined)}>取消</Button></div>}
   </li>)}</ul>}
   {state.page.next_cursor&&<Button disabled={busy} onClick={more}>載入更多</Button>}
  </>}
  {busy&&<p role="status">正在處理…</p>}
  {actionError&&<p role="alert">{actionError}<Button onClick={retry}>重試</Button></p>}
 </>;
 return <div className={`assistant-workspace${compact?' assistant-workspace-compact':''}${unavailable?' assistant-history-unavailable':''}`}>
  {!unavailable&&<>
   <button type="button" ref={trigger} data-variant="plain" className="ds-button assistant-history-toggle" aria-expanded={expanded} aria-controls={id} onClick={()=>setExpanded(value=>!value)}>對話紀錄</button>
   {overlay?<dialog role="dialog" aria-modal="true" ref={dialog} id={id} className="assistant-history-dialog" aria-labelledby={`${id}-title`} onKeyDown={event=>{
    if(event.key==='Escape')event.stopPropagation();
    if(event.key!=='Tab')return;
    const controls=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));
    const first=controls[0],last=controls.at(-1);
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
   }} onCancel={event=>{event.preventDefault();close()}}>{content}</dialog>:expanded&&<aside ref={panel} id={id} className="assistant-history-panel" aria-labelledby={`${id}-title`} onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();close()}}}>{content}</aside>}
  </>}
  <div className="assistant-history-thread">{children}</div>
 </div>;
}
