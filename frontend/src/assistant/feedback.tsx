import {createContext,useContext,useState} from 'react';
import {ActionBarPrimitive,useAuiState,type AssistantRuntime,type FeedbackAdapter,type ThreadMessage} from '@assistant-ui/react';
import {ThumbsUp,ThumbsDown} from 'lucide-react';
import {api} from '../api';
import {Button} from '../design';
export type Rating='up'|'down'|'none';
export type Reason='wrong'|'incomplete'|'slow'|'other';
const reasons:[Reason,string][]=[['wrong','答錯'],['incomplete','不完整'],['slow','太慢'],['other','其他']];
type Submitted={type:'positive'|'negative';comment?:string}|undefined;
export type FeedbackController={adapter:FeedbackAdapter;send:(message:ThreadMessage,rating:Rating,reason?:Reason)=>void;activate:()=>void;dispose:()=>void};
export function createFeedbackController(getRuntime:()=>AssistantRuntime):FeedbackController {
 let abort=new AbortController();
 const pending=new Set<string>();
 const waiting=new Set<()=>void>();
 function patch(id:string,submitted:Submitted,custom:Record<string,unknown>){
  if(abort.signal.aborted)return;
  const thread=getRuntime().thread;
  const apply=()=>{
   if(thread.getState().isRunning)return false;
   const repo=thread.export();
   thread.import({...repo,messages:repo.messages.map(item=>item.message.id===id&&item.message.role==='assistant'?{...item,message:{...item.message,metadata:{...item.message.metadata,submittedFeedback:submitted,custom:{...item.message.metadata.custom,...custom}}}}:item)});
   return true;
  };
  // The pinned API has no metadata setter or feedback cancellation. Import only when idle so a pending reply keeps ownership of its stream.
  if(!apply()){
   const unsubscribe=thread.subscribe(()=>{if(thread.getState().isRunning)return;unsubscribe();waiting.delete(unsubscribe);apply()});
   waiting.add(unsubscribe);
  }
 }
 function send(message:ThreadMessage,rating:Rating,reason?:Reason){
  const usageId=message.metadata.custom.usage_id;
  if(message.role!=='assistant'||message.status.type!=='complete'||typeof usageId!=='string'||pending.has(message.id))return;
  pending.add(message.id);
  const signal=abort.signal;
  const before=message.metadata.submittedFeedback;
  const submitted:Submitted=rating==='none'?undefined:{type:rating==='up'?'positive':'negative',...(reason?{comment:reason}:{})};
  queueMicrotask(()=>{if(!signal.aborted)patch(message.id,submitted,{feedbackPending:true,feedbackError:undefined})});
  void api('/api/ai/feedback',{method:'POST',signal,body:JSON.stringify({usage_id:usageId,rating,...(rating==='down'&&reason?{reason}:{})})}).then(()=>{
   if(signal.aborted)return;
   patch(message.id,submitted,{feedbackPending:false,feedbackError:undefined});
  }).catch(()=>{
   if(signal.aborted)return;
   patch(message.id,before,{feedbackPending:false,feedbackError:'評分未儲存，請再試一次。'});
  }).finally(()=>pending.delete(message.id));
 }
 return {adapter:{submit:({message,type,comment})=>{
  const active=message.metadata.submittedFeedback?.type===type&&!comment;
  send(message,active?'none':type==='positive'?'up':'down',reasons.find(([reason])=>reason===comment)?.[0]);
 }},send,activate:()=>{if(abort.signal.aborted)abort=new AbortController()},dispose:()=>{abort.abort();pending.clear();for(const unsubscribe of waiting)unsubscribe();waiting.clear()}};
}
export const FeedbackContext=createContext<FeedbackController|null>(null);
export function FeedbackActions(){
 const controller=useContext(FeedbackContext);
 const message=useAuiState(s=>s.message);
 const running=useAuiState(s=>s.thread.isRunning);
 const [dismissed,setDismissed]=useState(false);
 const submitted=message.metadata.submittedFeedback;
 const negative=submitted?.type==='negative';
 const pending=message.metadata.custom.feedbackPending===true;
 const error=message.metadata.custom.feedbackError;
 const eligible=message.role==='assistant'&&message.status.type==='complete'&&typeof message.metadata.custom.usage_id==='string';

 if(!eligible||!controller)return null;
 return <div className="assistant-feedback">
  <div className="assistant-feedback-buttons" aria-label="回覆評分" role="group">
   <ActionBarPrimitive.FeedbackPositive asChild disabled={pending||running} onClick={()=>setDismissed(false)}><Button variant="plain" aria-label="這則回答有幫助"><ThumbsUp size={16} aria-hidden="true"/>有幫助</Button></ActionBarPrimitive.FeedbackPositive>
   <ActionBarPrimitive.FeedbackNegative asChild disabled={pending||running} onClick={()=>setDismissed(false)}><Button variant="plain" aria-label="這則回答沒有幫助"><ThumbsDown size={16} aria-hidden="true"/>沒幫助</Button></ActionBarPrimitive.FeedbackNegative>
  </div>
  {negative&&!dismissed&&<div className="assistant-feedback-reasons" role="group" aria-label="哪裡需要改進？">
   <span>哪裡需要改進？</span>{reasons.map(([reason,label])=><Button key={reason} variant="plain" disabled={pending||running} aria-pressed={submitted.comment===reason} onClick={()=>controller.send(message,'down',reason)}>{label}</Button>)}
   <Button variant="plain" aria-label="略過評分原因" onClick={()=>setDismissed(true)}>略過</Button>
  </div>}
  {pending&&<span className="assistant-sr-only" role="status">正在儲存評分</span>}
  {typeof error==='string'&&<p role="alert" className="assistant-error">{error}</p>}
 </div>;
}
