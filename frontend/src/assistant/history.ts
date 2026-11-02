import type {ThreadMessageLike} from '@assistant-ui/react';
import {api,ApiError,getSessionEpoch,onSessionEpochChange} from '../api';
// Scope versions fence late transport results as well as mounted React caches.
const scopeVersions=new Map<string,number>();
const scopeListeners=new Set<()=>void>();
export const assistantScopeVersion=(projectId?:string)=>`${getSessionEpoch()}:${scopeVersions.get(JSON.stringify(projectId??null))||0}`;
export function subscribeAssistantScope(listener:()=>void){
 scopeListeners.add(listener);const unsubscribe=onSessionEpochChange(listener);
 return()=>{scopeListeners.delete(listener);unsubscribe()};
}
export function denyAssistantScope(projectId?:string){
 const key=JSON.stringify(projectId??null);scopeVersions.set(key,(scopeVersions.get(key)||0)+1);
 for(const listener of scopeListeners)listener();
}
const stale=()=>new DOMException('Assistant scope changed','AbortError');
async function scopedRead<T>(url:string,projectId?:string,signal?:AbortSignal):Promise<T>{
 const version=assistantScopeVersion(projectId);
 try{
  const result=await api<T>(url,{signal,cache:'no-store'});
  if(version!==assistantScopeVersion(projectId)||signal?.aborted)throw stale();
  return result;
 }catch(error){
  if(version!==assistantScopeVersion(projectId)||signal?.aborted)throw stale();
  if(error instanceof ApiError&&error.status===403)denyAssistantScope(projectId);
  throw error;
 }
}
export type HistoryScope={scope:'global';project_id?:never}|{scope:'project';project_id:string};
export type ConversationSummary={id:string;title:string;scope:'global'|'project';project_id:string|null;updated_at:string;turns:number};
export type ConversationDetail=Omit<ConversationSummary,'updated_at'|'turns'>&{messages:{role:'user'|'assistant';content:string;at:string;usage_id:string|null}[]};
export type HistoryPage={history_available:boolean;items:ConversationSummary[];next_cursor:string|null};
export function listConversations(scope:HistoryScope,before?:string,signal?:AbortSignal){
 const query=new URLSearchParams({scope:scope.scope,limit:'30',...(scope.project_id?{project_id:scope.project_id}:{}),...(before?{before}:{})});
 return scopedRead<HistoryPage>(`/api/ai/conversations?${query}`,scope.project_id,signal).then(page=>{
  if(typeof page.history_available!=='boolean'||!Array.isArray(page.items)||!(page.next_cursor===null||typeof page.next_cursor==='string'))throw new Error('Invalid history response');
  return page;
 });
}
export function openConversation(id:string,signal?:AbortSignal,projectId?:string){return scopedRead<ConversationDetail>(`/api/ai/conversations/${encodeURIComponent(id)}`,projectId,signal)}
export async function deleteConversation(id:string,signal?:AbortSignal,projectId?:string){
 const epoch=getSessionEpoch(),version=assistantScopeVersion(projectId);
 const response=await fetch(`/api/ai/conversations/${encodeURIComponent(id)}`,{method:'DELETE',credentials:'same-origin',signal});
 if(version!==assistantScopeVersion(projectId)||signal?.aborted)throw stale();
 if(response.status===403)denyAssistantScope(projectId);
 if(response.status===401&&epoch===getSessionEpoch()&&!signal?.aborted)window.dispatchEvent(new Event('yx:session-expired'));
 if(!response.ok)throw new ApiError(response.status,'無法刪除對話，請重試。');
}
export function historyMessages(detail:ConversationDetail):ThreadMessageLike[]{
 return detail.messages.map((message,index)=>({id:`${detail.id}-${index}`,role:message.role,content:[{type:'text',text:message.content}],createdAt:new Date(message.at),...(message.role==='assistant'?{status:{type:'complete',reason:'stop'},metadata:{custom:{usage_id:message.usage_id}}}:{})}));
}
export function relativeTime(at:string,now=Date.now()){
 const minutes=Math.max(0,Math.floor((now-Date.parse(at))/60000));
 if(minutes<1)return '剛剛';
 if(minutes<60)return `${minutes} 分鐘前`;
 if(minutes<1440)return `${Math.floor(minutes/60)} 小時前`;
 return `${Math.floor(minutes/1440)} 天前`;
}
