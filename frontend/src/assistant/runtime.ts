import type {ChatModelAdapter,ThreadAssistantMessagePart,ToolCallMessagePart} from '@assistant-ui/react';
import {getSessionEpoch} from '../api';
import {readEvents} from './stream';
export type ModelId='claude'|'gpt';
export const ERROR_TEXT:Record<string,string>={
 ai_unconfigured:'AI 助理尚未設定，請聯絡管理員。',
 ai_quota:'今天的使用額度已用完，請明天再試。',
 ai_busy:'目前使用人數較多，請稍後重試。',
 ai_upstream:'AI 服務暫時無法回應，請稍後重試。',
 ai_forbidden:'你沒有權限查詢這項資料。',
 ai_refused:'這個問題無法回答，請改問案件進度或出勤。',
 session_expired:'登入已失效，請重新登入。',
 network:'連線中斷，請檢查網路後重試。',
 message_limit:'問題或對話過長，請縮短問題或開始新對話。',
};
export const errorText=(code:string)=>ERROR_TEXT[code]||ERROR_TEXT.ai_upstream;
export function createChatAdapter(model:()=>ModelId,conversation:()=>string,onForbidden:()=>void=()=>{}):ChatModelAdapter {
 return {async *run({messages,abortSignal}){
  const epoch=getSessionEpoch();
  const content:ThreadAssistantMessagePart[]=[];
  try {
   const all=messages.filter(m=>m.role==='user'||(m.role==='assistant'&&m.status?.type!=='incomplete')).map(m=>({role:m.role,content:m.content.filter(p=>p.type==='text').map(p=>p.text).join('')})).filter(m=>m.content);
   if(all.at(-1)?.role==='user'&&all.at(-1)!.content.length>4000)throw new Error('message_limit');
   const history=all.filter((m,i)=>m.role!=='user'||m.content.length<=4000||i===all.length-1);
   while(history.at(-1)?.role==='assistant')history.pop();
   const recent=history.slice(-20).map(m=>({...m,content:m.role==='assistant'?m.content.slice(0,20000):m.content}));
   if(recent[0]?.role==='assistant')recent.shift();
   const response=await fetch('/api/ai/chat',{method:'POST',credentials:'same-origin',signal:abortSignal,headers:{'Content-Type':'application/json'},body:JSON.stringify({model:model(),conversation_id:conversation(),messages:recent})});
   if(response.status===401){if(epoch===getSessionEpoch()&&!abortSignal.aborted)window.dispatchEvent(new Event('yx:session-expired'));throw new Error('session_expired')}
   if(response.status===403)throw new Error('ai_forbidden');
   if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.code||'ai_upstream')}
   if(!response.body)throw new Error('network');
   for await(const event of readEvents(response.body,abortSignal)){
    if(event.type==='error')throw new Error(event.code);
    if(event.type==='done'){yield {content:[...content],status:{type:'complete',reason:'stop'}};return}
    if(event.type==='text'){
     const last=content.at(-1);
     if(last?.type==='text')content[content.length-1]={type:'text',text:last.text+event.delta};
     else content.push({type:'text',text:event.delta});
    }
    if(event.type==='tool'){
     const part:ToolCallMessagePart={type:'tool-call',toolCallId:event.id,toolName:event.name,args:{label:event.label},argsText:JSON.stringify({label:event.label}),...(event.status==='running'?{}:{result:event.status,isError:event.status==='error'})};
     const index=content.findIndex(p=>p.type==='tool-call'&&p.toolCallId===event.id);
     if(index<0)content.push(part);else content[index]=part;
    }
    yield {content:[...content]};
   }
   throw new Error('network');
  }catch(error){
   if(abortSignal.aborted)throw error;
   const code=error instanceof Error?error.message:'network';
   if(code==='ai_forbidden')onForbidden();
   yield {content:[...content],status:{type:'incomplete',reason:'error',error:errorText(code in ERROR_TEXT?code:error instanceof TypeError?'network':'ai_upstream')}};
  }
 }};
}
