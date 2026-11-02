import {useCallback,useRef,useSyncExternalStore} from 'react';
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
 return read;
}
