import {useEffect,useRef,useState} from 'react';
import {api,getSessionEpoch} from '../api';
import {query} from './reportsView';
import type {Query} from './types';
const cache=new Map<string,{at:number;data:unknown}>();
export function useDebounce(value:string,onApply?:()=>void){const apply=useRef(onApply);apply.current=onApply;const [result,set]=useState(value);useEffect(()=>{if(value===result)return;const timer=setTimeout(()=>{set(value);apply.current?.()},250);return()=>clearTimeout(timer)},[value,result]);return result}
export function useReport<T>(endpoint:string,params:Query){
 const key=query(Object.fromEntries(Object.entries(params).sort(([a],[b])=>a.localeCompare(b))));const sequence=useRef(0);const [reload,setReload]=useState(0);
 const [state,setState]=useState<{key:string; data?:T; error?:string; loading:boolean}>({key:'',loading:true});
 useEffect(()=>{const controller=new AbortController();const seq=++sequence.current;const epoch=getSessionEpoch();const cacheKey=`${epoch}:${location.search}:${endpoint}?${key}`;const cached=cache.get(cacheKey);if(cached&&Date.now()-cached.at<60000&&reload===0){setState({key,data:cached.data as T,loading:false});return()=>controller.abort()} const current=()=>!controller.signal.aborted&&seq===sequence.current&&epoch===getSessionEpoch();setState({key,loading:true});
 const load=async()=>{if(new URLSearchParams(location.search).get('mock')==='1'){const {mockReport}=await import('./mock');return mockReport(endpoint,new URLSearchParams(key)) as T}return api<T>(`/api/reports/${endpoint}?${key}`,{signal:controller.signal,cache:'no-store'},current)};
 load().then(data=>{if(current()){if(cache.size>=256)cache.clear();cache.set(cacheKey,{at:Date.now(),data});setState({key,data,loading:false})}}).catch(e=>{if(current())setState({key,error:e instanceof Error?e.message:'暫時無法讀取報表',loading:false})});return()=>controller.abort();
 },[endpoint,key,reload]);
 return {...(state.key===key?state:{key,loading:true}),retry:()=>setReload(v=>v+1)};
}
