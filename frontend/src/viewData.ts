import {useCallback,useEffect,useRef,useState,type DependencyList} from 'react';
import {getSessionEpoch} from './api';
import './skeleton.css';

export type ViewDataFetcher<T>=(signal:AbortSignal,isCurrent:()=>boolean)=>Promise<T>;
type ViewState<T>={key:string;epoch:number;data?:T;loading:boolean;error:string};

// Include c.reloadVersion ?? c.w.version in deps. For conditional requests use:
// useViewData(key, (signal, current) => api(url, {signal, etag:true}, current), deps).
// Consumers render a .skeleton while loading && !data; refreshes retain data.
export function useViewData<T>(key:string,fetcher:ViewDataFetcher<T>,deps:DependencyList=[]){
 const epoch=getSessionEpoch();
 const [tick,setTick]=useState(0);
 const [state,setState]=useState<ViewState<T>>({key,epoch,loading:true,error:''});
 const latest=useRef(fetcher);latest.current=fetcher;
 const identity=useRef({key,epoch,tick,deps,revision:0});
 const before=identity.current;
 if(before.key!==key||before.epoch!==epoch||before.tick!==tick||before.deps.length!==deps.length||deps.some((value,i)=>!Object.is(value,before.deps[i]))){
  identity.current={key,epoch,tick,deps,revision:before.revision+1};
 }
 const revision=identity.current.revision;
 const reload=useCallback(()=>setTick(value=>value+1),[]);
 useEffect(()=>{
  const controller=new AbortController();
  const current=()=>!controller.signal.aborted&&epoch===getSessionEpoch()&&identity.current.revision===revision;
  setState(previous=>({key,epoch,data:previous.key===key&&previous.epoch===epoch?previous.data:undefined,loading:true,error:''}));
  async function load(){
   try{
    const data=await latest.current(controller.signal,current);
    if(current())setState({key,epoch,data,loading:false,error:''});
   }catch(error){
    if(current())setState(previous=>({...previous,loading:false,error:error instanceof Error?error.message:String(error)}));
   }
  }
  void load();
  return()=>controller.abort();
 },[key,epoch,revision]);
 const visible=state.key===key&&state.epoch===epoch?state:{data:undefined,loading:true,error:''};
 return {data:visible.data,loading:visible.loading,error:visible.error,reload};
}
