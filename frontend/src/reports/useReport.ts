import {useEffect,useRef,useState} from 'react';
import {ApiError,onSessionEpochChange} from '../api';
import {query} from './reportsView';
import {usePageOwner,type FetchIntent} from '../pageData';
import {usePageResource} from '../viewData';
import type {Query} from './types';
let reportSequence=0,reportGeneration=0;
const reportId=()=>`report:${++reportSequence}`;
export function useDebounce(value:string,onApply?:()=>void){const apply=useRef(onApply);apply.current=onApply;const [result,set]=useState(value);useEffect(()=>{if(value===result)return;const timer=setTimeout(()=>{set(value);apply.current?.()},250);return()=>clearTimeout(timer)},[value,result]);return result}
class ReportError extends ApiError {
 constructor(status:number,message:string,public warming:boolean){super(status,message)}
}
async function readReport<T>(url:string,signal:AbortSignal,current:()=>boolean,intent:FetchIntent):Promise<T>{
 const controller=new AbortController();const abort=()=>controller.abort();
 signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();
 const unsubscribe=onSessionEpochChange(abort);
 let timedOut=false;const deadline=setTimeout(()=>{timedOut=true;abort()},30000);
 try{
 const response=await fetch(url,{signal:controller.signal,cache:'no-store',credentials:'same-origin',headers:{'Content-Type':'application/json','X-YX-Fetch-Intent':intent.reason}});
 let data;
 try{data=await response.json()}catch{throw new ApiError(response.status,'服務回應格式不正確，請稍後再試。')}
 if(response.status===401&&current())window.dispatchEvent(new Event('yx:session-expired'));
 if(response.status===202)throw new ReportError(202,'報表更新結果尚未確認，請按重試查看結果。',true);
 if(!response.ok)throw new ReportError(response.status,typeof data?.detail==='string'?data.detail:'暫時無法讀取報表',response.status===503&&data?.warming===true);
 if(data===null||typeof data!=='object')throw new ApiError(response.status,'服務回應格式不正確，請稍後再試。');
 return data as T;
 }catch(error){if(timedOut)throw new Error('報表讀取逾時，請按重試。');throw error}
 finally{controller.abort();clearTimeout(deadline);signal.removeEventListener('abort',abort);unsubscribe()}
}
export function useReport<T>(endpoint:string,params:Query){
 const key=query(Object.fromEntries(Object.entries(params).sort(([a],[b])=>a.localeCompare(b))));
 const [openId]=useState(()=>reportId());
 const owner=usePageOwner({workspace:'reports',identityFingerprint:location.search,openId:`${openId}:${reportGeneration}`});
 const resource={endpoint:`/api/reports/${endpoint}`,query:{query:key}};
 const resourceKey=JSON.stringify([owner.epoch,endpoint,key]);
 const [refresh,setRefresh]=useState({key:'',id:''});
 const first=useRef({owner,key:resourceKey});
 if(first.current.owner!==owner)first.current={owner,key:resourceKey};
 const intent:FetchIntent=refresh.key===resourceKey?{reason:'explicit_refresh',id:refresh.id}:{reason:first.current.key===resourceKey?'initial_open':'user_query_change'};
 const state=usePageResource<T>(owner,resource,intent,async(signal,current,activeIntent)=>{
  const data=new URLSearchParams(location.search).get('mock')==='1'?(await import('./mock')).mockReport(endpoint,new URLSearchParams(key)) as T:await readReport<T>(`/api/reports/${endpoint}?${key}`,signal,current,activeIntent);
  return {data,snapshotId:null,fetchedAt:null,verifiedAt:null,changedAt:null,completeness:'complete',localRevision:null,empty:false,stale:false};
 });
 // A refresh belongs to this query only. Moving away consumes its intent.
 useEffect(()=>{if(refresh.key&&refresh.key!==resourceKey)setRefresh({key:'',id:''})},[resourceKey,refresh.key]);
 const value='value' in state?state.value:undefined;
 const previous='previous' in state?state.previous:undefined;
 const error='error' in state?state.error:undefined;
 // A cache generation clears query entries, but cannot erase this query's last successful snapshot.
 const retainedKey=JSON.stringify([owner.epoch,location.search,endpoint,key]);
 const lastSuccess=useRef<{key:string;data:T}>();
 if(lastSuccess.current?.key!==retainedKey||state.kind==='Denied')lastSuccess.current=undefined;
 const retained=value?.data??previous?.data??lastSuccess.current?.data;
 if(retained!==undefined&&state.kind!=='Denied')lastSuccess.current={key:retainedKey,data:retained};
 const reportData=error&&retained&&typeof retained==='object'&&'meta' in retained?{...retained,meta:{...(retained as {meta:object}).meta,stale:true,refresh_error:true}} as T:retained;
 return {denied:state.kind==='Denied',data:state.kind==='Denied'?undefined:reportData,previous:state.kind==='Denied'?undefined:previous?.data,loading:state.kind==='Loading'||state.kind==='Stale',error:error instanceof ReportError&&error.warming?'報表資料尚未就緒，請按重試查看結果。':error instanceof Error?error.message:undefined,warming:error instanceof ReportError&&error.warming,retry:()=>setRefresh({key:resourceKey,id:reportId()})};
}

export function useReportSearch(onApply:()=>void){
 const [state,setState]=useState({search:'',q:''});const apply=useRef(onApply);apply.current=onApply;
 useEffect(()=>{if(state.search===state.q)return;const timer=setTimeout(()=>{setState(s=>({...s,q:s.search}));apply.current()},250);return()=>clearTimeout(timer)},[state.search,state.q]);
 return {...state,setSearch:(search:string)=>setState(s=>({...s,search})),applySearch:(search:string)=>setState({search,q:search})};
}

export function clearReportCache(){reportGeneration++;}
