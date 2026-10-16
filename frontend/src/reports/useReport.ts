import {useEffect,useRef,useState} from 'react';
import {ApiError,getSessionEpoch} from '../api';
import {query} from './reportsView';
import type {Query} from './types';
const cache=new Map<string,{at:number;data:unknown}>();
export function useDebounce(value:string,onApply?:()=>void){const apply=useRef(onApply);apply.current=onApply;const [result,set]=useState(value);useEffect(()=>{if(value===result)return;const timer=setTimeout(()=>{set(value);apply.current?.()},250);return()=>clearTimeout(timer)},[value,result]);return result}
class ReportError extends ApiError {
 constructor(status:number,message:string,public warming:boolean,public retryAfter:number){super(status,message)}
}
async function readReport<T>(url:string,signal:AbortSignal,current:()=>boolean):Promise<T>{
 const response=await fetch(url,{signal,cache:'no-store',credentials:'same-origin',headers:{'Content-Type':'application/json'}});
 let data;
 try{data=await response.json()}catch{throw new ApiError(response.status,'服務回應格式不正確，請稍後再試。')}
 if(response.status===401&&current())window.dispatchEvent(new Event('yx:session-expired'));
 if(!response.ok)throw new ReportError(response.status,typeof data?.detail==='string'?data.detail:'暫時無法讀取報表',response.status===503&&data?.warming===true,typeof data?.retry_after==='number'&&Number.isFinite(data.retry_after)&&data.retry_after>0?data.retry_after:5);
 if(data===null||typeof data!=='object')throw new ApiError(response.status,'服務回應格式不正確，請稍後再試。');
 return data as T;
}
export function useReport<T>(endpoint:string,params:Query){
 const key=query(Object.fromEntries(Object.entries(params).sort(([a],[b])=>a.localeCompare(b))));const sequence=useRef(0);const [reload,setReload]=useState(0);
 const [state,setState]=useState<{key:string; data?:T; error?:string; warming?:boolean; loading:boolean}>({key:'',loading:true});
 useEffect(()=>{const controller=new AbortController();const seq=++sequence.current;const epoch=getSessionEpoch();const cacheKey=`${epoch}:${location.search}:${endpoint}?${key}`;const cached=cache.get(cacheKey);if(cached&&Date.now()-cached.at<60000&&reload===0){setState({key,data:cached.data as T,loading:false});return()=>controller.abort()} const current=()=>!controller.signal.aborted&&seq===sequence.current&&epoch===getSessionEpoch();setState({key,loading:true});
 const load=async()=>{if(new URLSearchParams(location.search).get('mock')==='1'){const {mockReport}=await import('./mock');return mockReport(endpoint,new URLSearchParams(key)) as T}return readReport<T>(`/api/reports/${endpoint}?${key}`,controller.signal,current)};
 let timer:ReturnType<typeof setTimeout>|undefined;let attempts=0;
 const attempt=async()=>{
  if(!current())return;
  attempts++;
  try{
   const data=await load();
   if(current()){if(cache.size>=256)cache.clear();cache.set(cacheKey,{at:Date.now(),data});setState({key,data,loading:false})}
  }catch(e){
   if(!current())return;
   if(e instanceof ReportError&&e.warming&&attempts<12){
    setState({key,loading:true,warming:true});
    timer=setTimeout(()=>{timer=undefined;void attempt()},e.retryAfter*1000);
   }else setState({key,error:e instanceof Error?e.message:'暫時無法讀取報表',loading:false});
  }
 };
 void attempt();
 return()=>{controller.abort();if(timer!==undefined)clearTimeout(timer)};

 },[endpoint,key,reload]);
 return {...(state.key===key?state:{key,loading:true}),retry:()=>setReload(v=>v+1)};
}

export function useReportSearch(onApply:()=>void){
 const [state,setState]=useState({search:'',q:''});const apply=useRef(onApply);apply.current=onApply;
 useEffect(()=>{if(state.search===state.q)return;const timer=setTimeout(()=>{setState(s=>({...s,q:s.search}));apply.current()},250);return()=>clearTimeout(timer)},[state.search,state.q]);
 return {...state,setSearch:(search:string)=>setState(s=>({...s,search})),applySearch:(search:string)=>setState({search,q:search})};
}
