import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {ApiError,getSessionEpoch,onSessionEpochChange} from '../api';
import {query} from './reportsView';
import type {FetchIntent} from '../pageData';
import type {Query} from './types';
const cache=new Map<string,{at:number;data:unknown}>();
type PendingReport={controller:AbortController;promise:Promise<unknown>;readers:Set<()=>boolean>};
const pendingReports=new Map<string,PendingReport>();
function shareReport(key:string,load:(signal:AbortSignal,current:()=>boolean)=>Promise<unknown>,current:()=>boolean){
 let pending=pendingReports.get(key);
 if(!pending){
  const controller=new AbortController();const readers=new Set([current]);
  const promise=load(controller.signal,()=>[...readers].some(reader=>reader()));
  const created={controller,readers,promise};pending=created;pendingReports.set(key,created);
  const settled=()=>{if(pendingReports.get(key)===created)pendingReports.delete(key)};
  void promise.then(settled,settled);
 }else pending.readers.add(current);
 const shared=pending;
 return {promise:shared.promise,release:()=>{
  shared.readers.delete(current);
  if(shared.readers.size===0){
   if(pendingReports.get(key)===shared)pendingReports.delete(key);
   shared.controller.abort();
  }
 }};
}
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
 const key=query(Object.fromEntries(Object.entries(params).sort(([a],[b])=>a.localeCompare(b))));const sequence=useRef(0);const [reload,setReload]=useState(0);
 const epoch=useSyncExternalStore(onSessionEpochChange,getSessionEpoch,getSessionEpoch);
 const resourceKey=`${epoch}:${location.search}:${endpoint}?${key}`;
 const [state,setState]=useState<{key:string; data?:T; previous?:T; error?:string; warming?:boolean; loading:boolean}>({key:'',loading:true});
 useEffect(()=>{const controller=new AbortController();const seq=++sequence.current;const cacheKey=resourceKey;const cached=cache.get(cacheKey);if(cached&&Date.now()-cached.at<60000&&reload===0){setState({key:resourceKey,data:cached.data as T,loading:false});return()=>controller.abort()} const current=()=>!controller.signal.aborted&&seq===sequence.current&&epoch===getSessionEpoch();setState(previous=>({key:resourceKey,data:previous.key===resourceKey?(previous.data??previous.previous):undefined,loading:true}));
 const load=async(signal:AbortSignal,active:()=>boolean)=>{if(new URLSearchParams(location.search).get('mock')==='1'){const {mockReport}=await import('./mock');return mockReport(endpoint,new URLSearchParams(key))}return readReport<T>(`/api/reports/${endpoint}?${key}`,signal,active,reload?{reason:'explicit_refresh',id:String(reload)}:{reason:'initial_open'})};
 let release:(()=>void)|undefined;
 const attempt=async()=>{
  if(!current())return;
  try{
   const shared=shareReport(cacheKey,load,current);release=shared.release;
   const data=await shared.promise as T;
   if(current()){if(cache.size>=256)cache.clear();cache.set(cacheKey,{at:Date.now(),data});setState({key:resourceKey,data,loading:false})}
  }catch(e){
   if(!current())return;
   setState(previous=>({key:resourceKey,previous:previous.key===resourceKey?(previous.data??previous.previous):undefined,error:e instanceof ReportError&&e.warming?'報表資料尚未就緒，請按重試查看結果。':e instanceof Error?e.message:'暫時無法讀取報表',loading:false}));
  }finally{release?.();release=undefined}
 };
 void attempt();
 return()=>{controller.abort();release?.()};

 },[endpoint,key,reload,resourceKey,epoch]);
 return {...(state.key===resourceKey?state:{key:resourceKey,loading:true}),retry:()=>setReload(v=>v+1)};
}

export function useReportSearch(onApply:()=>void){
 const [state,setState]=useState({search:'',q:''});const apply=useRef(onApply);apply.current=onApply;
 useEffect(()=>{if(state.search===state.q)return;const timer=setTimeout(()=>{setState(s=>({...s,q:s.search}));apply.current()},250);return()=>clearTimeout(timer)},[state.search,state.q]);
 return {...state,setSearch:(search:string)=>setState(s=>({...s,search})),applySearch:(search:string)=>setState({search,q:search})};
}

export function clearReportCache(){cache.clear()}
