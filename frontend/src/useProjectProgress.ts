import {refreshSources} from './refreshSources';
import {useCallback, useEffect, useRef, useState} from 'react';
import {ApiError,getSessionEpoch,onSessionEpochChange} from './api';
import {fetchProjectProgress, type ProjectProgress} from './projectProgressApi';
const fresh=(data:ProjectProgress)=>['ready','fresh','partial'].includes(data.sources.source_status??'') && !!data.sources.source_synced_at;
type State = {kind: 'loading'}|{kind: 'ready'; data: ProjectProgress}|{kind: 'error'; message: string; status?:number; lastGoodAt?:string|null};
let epoch = getSessionEpoch();
const cache = new Map<string, {data: ProjectProgress; at: number}>();
const pending = new Map<string, {request:Promise<ProjectProgress>;signal?:AbortSignal}>();
export function prefetchProjectProgress(id: string, force = false, signal?:AbortSignal) {
 if (epoch !== getSessionEpoch()) {cache.clear(); pending.clear(); epoch = getSessionEpoch()}
 const currentEpoch = epoch;
 const running=pending.get(id);
 if (!force && running && !running.signal?.aborted) return running.request;
 const stored = cache.get(id);
 if (!force && stored && Date.now() - stored.at < 60000) return Promise.resolve(stored.data);
 const request = fetchProjectProgress(id, () => currentEpoch === getSessionEpoch(),signal).then(data => {if (currentEpoch === getSessionEpoch() && pending.get(id)?.request === request) cache.set(id, {data, at: Date.now()}); return data}).finally(() => {if (pending.get(id)?.request === request) pending.delete(id)});
 pending.set(id, {request,signal});
 return request;
}
export function useProjectProgress(id: string, enabled = true) {
 const [state, setState] = useState<State>({kind: 'loading'});
 const [version, setVersion] = useState(0);
 const reading = useRef(false);
 const synchronize=useRef<string|null>(null);
 const canRefresh=state.kind==='ready'?state.data.sources.can_refresh_sources===true:cache.has(id)?cache.get(id)?.data.sources.can_refresh_sources===true:false;
 const canRetryRead=state.kind==='error' && state.status!==401 && state.status!==403;
 const retry = useCallback(() => {
  if (!enabled || (!canRefresh && !canRetryRead) || reading.current) return;
  reading.current = true;
  synchronize.current=canRefresh?id:null;
  setState({kind: 'loading'});
  setVersion(v => v + 1);
 }, [id,enabled,canRefresh,canRetryRead]);
 const reload=useCallback(()=>{
  if(!enabled || reading.current)return;
  reading.current=true;
  synchronize.current=null;
  setVersion(v=>v+1);
 },[enabled]);
 useEffect(() => {
  if (!enabled) return;
  let active = true;
  const controller=new AbortController();
  const abort=()=>controller.abort();
  const unsubscribe=onSessionEpochChange(abort);
  reading.current = true;
  const currentEpoch = getSessionEpoch();
  const sync=version>0 && synchronize.current===id;
  const timer=sync?setTimeout(()=>controller.abort(),90000):undefined;
  const lastGoodAt=cache.get(id)?.data.sources.source_synced_at;
  setState({kind: 'loading'});
  void (async()=>{if(sync && cache.get(id)?.data.sources.can_refresh_sources===true)await refreshSources('sources',undefined,controller.signal);if(!active || currentEpoch!==getSessionEpoch())return null;return prefetchProjectProgress(id,version>0,controller.signal)})().then(data => {
   if(!data || !active || currentEpoch!==getSessionEpoch())return;
   if(sync && !fresh(data))setState({kind:'error',message:'來源仍待更新，請重試',lastGoodAt:data.sources.source_synced_at || lastGoodAt});
   else setState({kind:'ready',data});
  }).catch(error => {if (active && currentEpoch === getSessionEpoch()) setState({kind: 'error', message: controller.signal.aborted ? '資料仍在更新，請稍後重試' : error instanceof Error ? error.message : '工程進度暫不可用。',lastGoodAt:lastGoodAt,...(error instanceof ApiError ? {status:error.status} : {})})}).finally(() => {clearTimeout(timer);if (active) reading.current = false});
  return () => {active = false; clearTimeout(timer);controller.abort();unsubscribe()};
 }, [id, enabled, version]);
 return {state, retry, reload, canRefresh, canRetryRead};
}
