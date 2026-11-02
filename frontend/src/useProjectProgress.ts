import {useCaseData, caseKey, readCase, seedCase, useDetailRefresh} from './detailRefresh';
import type {PageData} from './pageData';
import {refreshSources} from './refreshSources';
import {useCallback, useEffect, useRef, useState} from 'react';
import {ApiError,getSessionEpoch,onSessionEpochChange} from './api';
import {fetchProjectProgress, type ProjectProgress} from './projectProgressApi';
const fresh=(data:ProjectProgress)=>['ready','fresh','partial'].includes(data.sources.source_status??'') && !!data.sources.source_synced_at;
type State = {kind:'loading'}|{kind:'ready';data:ProjectProgress}|{kind:'error';message:string;status?:number;lastGoodAt?:string|null};
const cache=new Map<string,ProjectProgress>();
export function prefetchProjectProgress(id:string,force=false,signal?:AbortSignal,batch?:symbol,owner?:PageData){
 return readCase(owner,`progress:${id}`,batch||force,(current,_intent,ownedSignal)=>fetchProjectProgress(id,current,signal?AbortSignal.any([signal,ownedSignal]):ownedSignal)).then(data=>{cache.set(caseKey(owner,id),data);return data});
}
export function peekProjectProgress(id:string,owner?:PageData){return cache.get(caseKey(owner,id))}
export function seedProjectProgress(id:string,data:ProjectProgress,owner?:PageData){cache.set(caseKey(owner,id),data);seedCase(owner,`progress:${id}`,data,(current,_intent,signal)=>fetchProjectProgress(id,current,signal))}
export function useProjectProgress(id:string,enabled=true){
 const owner=useCaseData(),key=caseKey(owner,id);
 const [state,setState]=useState<State>({kind:'loading'});
 const [refreshError,setRefreshError]=useState(''),[refreshing,setRefreshing]=useState(false);
 const life=useRef({key,epoch:getSessionEpoch(),active:true,seq:0,controller:new AbortController()});
 const canRefresh=state.kind==='ready'&&state.data.sources.can_refresh_sources===true;
 const canRetryRead=state.kind==='error'&&state.status!==401&&state.status!==403;
 const load=useCallback(async(force=false,batch?:symbol,sync=false)=>{
  if(!enabled)return;
  const scope=life.current,seq=++scope.seq;
  const current=()=>scope===life.current&&scope.active&&scope.epoch===getSessionEpoch()&&scope.seq===seq;
  const lastGoodAt=cache.get(key)?.sources.source_synced_at;
  setRefreshing(true);setRefreshError('');
  const unsubscribe=onSessionEpochChange(()=>scope.controller.abort());
  try{
   if(sync)await refreshSources('sources',undefined,scope.controller.signal);
   if(!current())return;
   const data=await prefetchProjectProgress(id,force,undefined,batch,owner);
   if(!current())return;
   if(sync&&!fresh(data))setState({kind:'error',message:'來源仍待更新，請重試',lastGoodAt:data.sources.source_synced_at||lastGoodAt});
   else setState({kind:'ready',data});
  }catch(error){if(current()){
   const message=error instanceof Error?error.message:'工程進度暫不可用。';setRefreshError(message);
   setState(previous=>previous.kind==='ready'&&!(error instanceof ApiError&&[401,403,404].includes(error.status))?previous:{kind:'error',message,lastGoodAt,...(error instanceof ApiError?{status:error.status}:{})});
  }}finally{unsubscribe();if(current())setRefreshing(false)}
 },[id,key,enabled,owner]);
 useEffect(()=>{
  const scope={key,epoch:getSessionEpoch(),active:true,seq:0,controller:new AbortController()};life.current=scope;
  const stored=cache.get(key);setState(stored?{kind:'ready',data:stored}:{kind:'loading'});
  void load();return()=>{scope.active=false;scope.controller.abort()};
 },[key,load]);
 const reload=useCallback(()=>load(true),[load]);
 const reloadDetail=useCallback((batch:symbol)=>load(true,batch),[load]);
 useDetailRefresh(reloadDetail,enabled,state.kind==='ready'?refreshError:'',refreshing);
 const retrying=useRef<Promise<void>|null>(null);
 const retry=useCallback(()=>{if(retrying.current)return retrying.current;if(!enabled||!canRefresh&&!canRetryRead)return Promise.resolve();const request=load(true,undefined,canRefresh).finally(()=>{if(retrying.current===request)retrying.current=null});retrying.current=request;return request},[enabled,canRefresh,canRetryRead,load]);
 return {state:life.current.key===key&&life.current.epoch===getSessionEpoch()?state:{kind:'loading'} as State,refreshing,refreshError,retry,reload,canRefresh,canRetryRead};
}
