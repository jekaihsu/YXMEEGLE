import {useCallback,useEffect,useRef,useSyncExternalStore} from 'react';
import {getSessionEpoch,onSessionEpochChange} from './api';
import {useViewData} from './viewData';
import {cachedDispatchBoard,readDispatchBoard} from './dispatchBoardCache';
import type {DispatchBoardData} from './dispatchBoardModel';

export type DispatchRead = {data?:DispatchBoardData;loading:boolean;error:string;stale?:boolean;reload:()=>void};

export function useDispatchBoardRead(from:string,reloadVersion=0):DispatchRead {
 const epoch=useSyncExternalStore(onSessionEpochChange,getSessionEpoch,getSessionEpoch);
 const key=`dispatch:${epoch}:${from}`;
 const fresh=useRef(false),version=useRef(reloadVersion);
 if(version.current!==reloadVersion){version.current=reloadVersion;fresh.current=true}
 const result=useViewData(key,(signal)=>{
  const force=fresh.current;fresh.current=false;
  return readDispatchBoard(from,signal,force);
 },[reloadVersion]);
 const reload=useCallback(()=>{fresh.current=true;result.reload()},[result.reload]);
 const data=result.data??cachedDispatchBoard(from);
 const read={...result,data,reload,stale:!!data&&result.loading};
 const refreshes=useRef({key,started:Date.now()});
 useEffect(()=>{
  if(refreshes.current.key!==key)refreshes.current={key,started:Date.now()};
  if(!read.data||read.loading||read.error||Date.now()-refreshes.current.started>=30000||read.data.source.quality.states.some(s=>s==='forbidden'||s==='read_failed'))return;
  const pending=(read.data.source.quality.states.includes('stale')&&read.data.source.quality.reason==='refreshing_last_good_snapshot')||Object.values(read.data.source.joins).some(s=>s==='unavailable');
  if(!pending)return;
  const epoch=getSessionEpoch();
  const timer=setTimeout(()=>{if(epoch===getSessionEpoch()&&Date.now()-refreshes.current.started<30000)read.reload()},1500);
  return()=>clearTimeout(timer);
 },[key,read.data,read.loading,read.error,read.reload]);
 return read;
}
