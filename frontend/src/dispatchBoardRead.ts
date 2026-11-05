import {useCallback,useContext,useEffect,useState,useSyncExternalStore} from 'react';
import {ApiError} from './api';
import {HomeDataContext} from './useHomePanels';
import {requestPageData,usePageOwner,type PageData} from './pageData';
import {addDays,parseDispatchBoard,type DispatchBoardData} from './dispatchBoardModel';

export type DispatchRead = {data?:DispatchBoardData;loading:boolean;error:string;stale?:boolean;reload:()=>void};
const generations=new WeakMap<PageData,Map<string,number>>();
export function useDispatchBoardRead(from:string,reloadVersion=0,provided?:PageData):DispatchRead {
 const shared=useContext(HomeDataContext);
 const [openId]=useState(()=>crypto.randomUUID());
 const local=usePageOwner({workspace:'dispatch',identityFingerprint:'session',openId});
 const owner=provided??shared??local;
 const resource={endpoint:'/api/v2/dispatch/board',query:{from,to:addDays(from,6)}};
 const key=owner.key(resource);
 const subscribe=useCallback((notify:()=>void)=>owner.subscribe(resource,notify),[owner,key]);
 const snapshot=useCallback(()=>owner.state<DispatchBoardData>(resource),[owner,key]);
 const state=useSyncExternalStore(subscribe,snapshot,snapshot);
 const read=useCallback((refresh=false)=>{
  let seen=generations.get(owner);if(!seen){seen=new Map();generations.set(owner,seen)}
  const prior=seen.get(key);seen.set(key,reloadVersion);
  const intent=refresh||prior!==undefined&&prior!==reloadVersion?{reason:'explicit_refresh' as const,id:`dispatch:${reloadVersion}:${crypto.randomUUID()}`}:{reason:prior===undefined?'initial_open' as const:'user_query_change' as const};
  void requestPageData(owner,resource,intent,raw=>{
   const data=parseDispatchBoard(raw);
   if(data.window.from!==from||data.window.to!==addDays(from,6))throw new Error('回應週次與目前查詢不符，請重試。');
   return {data,snapshotId:null,fetchedAt:data.source.fetched_at,verifiedAt:null,changedAt:null,completeness:'complete',localRevision:null,empty:false,stale:false};
  },{timeoutMs:30000}).catch(()=>{});
 },[owner,key,reloadVersion]);
 useEffect(()=>read(),[read]);
 const value='value' in state?state.value:'previous' in state?state.previous:undefined;
 const error='error' in state?state.error:null;
 const denied=error instanceof ApiError&&[401,403].includes(error.status);
 const data=denied?parseDispatchBoard({schema_version:1,window:{from,to:addDays(from,6),tz:'Asia/Taipei'},source:{quality:{states:['forbidden']}},slots:[]}):state.kind==='Closed'?undefined:value?.data;
 return {data,loading:state.kind==='Loading'||state.kind==='Stale',error:denied?'':error instanceof Error?error.message:'',stale:state.kind==='Stale',reload:()=>read(true)};
}
