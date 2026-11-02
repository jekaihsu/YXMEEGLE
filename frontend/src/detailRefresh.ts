import {Fragment, createContext, createElement, useCallback, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {getPendingMutations, getSessionEpoch} from './api';
import {createPageData, type PageData, type FetchIntent, type PageValue} from './pageData';
import {useReloadGuard} from './reloadGuard';

let generation = 0;
const resources=new WeakMap<PageData,Map<string,(batch:symbol)=>Promise<unknown>>>();
const CaseData = createContext<PageData | null>(null);
let fallback: PageData | undefined;
export function caseData(owner?: PageData | null) {
 if (owner) return owner;
 if (!fallback || fallback.epoch !== getSessionEpoch()) fallback = createPageData({workspace:'standalone',identityFingerprint:String(getSessionEpoch()),openId:`standalone-${++generation}`});
 return fallback;
}
export const useCaseData = () => caseData(useContext(CaseData));
export const caseKey = (owner: PageData | undefined, key: string) => caseData(owner).key({endpoint:key});
const value = <T,>(data:T):PageValue<T> => ({data,snapshotId:null,fetchedAt:new Date().toISOString(),verifiedAt:null,changedAt:null,completeness:'unknown',localRevision:null,empty:false,stale:false});
export function readCase<T>(owner:PageData|undefined,key:string,force:boolean|symbol,load:(current:()=>boolean,intent:FetchIntent)=>Promise<T>) {
 owner=caseData(owner);
 let loaded=resources.get(owner);if(!loaded){loaded=new Map();resources.set(owner,loaded)}
 loaded.set(key,batch=>readCase(owner,key,batch,load));
 const intent:FetchIntent = force ? {reason:typeof force==='symbol'?batchReasons.get(force)??'explicit_refresh':'explicit_refresh',id:typeof force==='symbol'?batchId(force):`read-${++generation}`} : {reason:'initial_open'};
 return caseData(owner).read({endpoint:key},intent,async(_signal,current,activeIntent)=>value(await load(current,activeIntent))).then(result=>result.data);
}
const batches=new Map<symbol,string>();
const batchReasons=new Map<symbol,'own_write_committed'|'explicit_refresh'>();
function batchId(batch:symbol){let id=batches.get(batch);if(!id){id=`batch-${++generation}`;batches.set(batch,id)}return id}
export function seedCase<T>(owner:PageData|undefined,key:string,data:T,load:(current:()=>boolean,intent:FetchIntent)=>Promise<T>,track=true) {
 owner=caseData(owner);
 let loaded=resources.get(owner);if(!loaded){loaded=new Map();resources.set(owner,loaded)}
 if(track)loaded.set(key,batch=>readCase(owner,key,batch,load));
 owner.seed({endpoint:key},value(data),`seed-${++generation}`,async(_signal,current,activeIntent)=>value(await load(current,activeIntent)));
}
type Reload = (batch: symbol) => void | Promise<unknown>;
type Coordinator = {register: (reload: Reload) => () => void; refresh: (afterWrite?: boolean) => Promise<void>; report: (key: symbol, error: string, loading: boolean) => void};
const DetailRefresh = createContext<Coordinator | null>(null);

function useCaseOwner(scope:string){
 const [owner]=useState(()=>createPageData({workspace:scope,identityFingerprint:String(getSessionEpoch()),openId:`case-${++generation}`}));
 const mounted=useRef(false);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;queueMicrotask(()=>{if(!mounted.current)owner.close()})}},[owner]);
 return owner;
}
export function DetailRefreshProvider({children, revision, canRefresh, scope='case'}: {children: ReactNode; revision?: number; canRefresh?: () => boolean; scope?:string}) {
 const owner=useCaseOwner(scope);
 const [statuses,setStatuses]=useState(new Map<symbol,{error:string;loading:boolean}>());
 const report=useCallback((key:symbol,error:string,loading:boolean)=>{setStatuses(previous=>{const next=new Map(previous);if(error||loading)next.set(key,{error,loading});else next.delete(key);return next})},[]);
 const guard = useReloadGuard();
 const latest = useRef({canRefresh, blocked: guard.blocked}); latest.current = {canRefresh, blocked: guard.blocked};
 const readers = useRef(new Set<Reload>());
 const running = useRef<Promise<void> | null>(null);
 const deferred=useRef<{epoch:number;afterWrite:boolean;promise:Promise<void>;resolve:()=>void}|null>(null);
 const started=useRef(false);
 const register = useCallback((reload: Reload) => {readers.current.add(reload); return () => {readers.current.delete(reload)}}, []);
 const refresh = useCallback((afterWrite = true): Promise<void> => {
  const epoch = getSessionEpoch();
  if(getPendingMutations() || latest.current.blocked() || latest.current.canRefresh?.()===false){
   if(!deferred.current){let resolve=()=>{};const promise=new Promise<void>(done=>{resolve=done});deferred.current={epoch,afterWrite,promise,resolve}}
   else deferred.current.afterWrite ||= afterWrite;
   return deferred.current.promise;
  }
  if (running.current) return afterWrite&&started.current ? running.current.then(()=>refresh(afterWrite)) : running.current;
  const request = Promise.resolve().then(async () => {
   if (epoch !== getSessionEpoch()) return;
   started.current=true;
   const batch=Symbol();batchReasons.set(batch,afterWrite?'own_write_committed':'explicit_refresh');
   const active=[...readers.current].map(reload=>reload(batch));
   await Promise.allSettled([...active,...[...(resources.get(owner)?.values()??[])].map(reload=>reload(batch))]);
  }).finally(() => {if (running.current === request) {running.current = null;started.current=false;}});
  running.current = request;
  return request;
 }, [owner]);
 useEffect(()=>{const pending=deferred.current;if(pending&&!guard.blocked()&&canRefresh?.()!==false){deferred.current=null;if(pending.epoch!==getSessionEpoch())pending.resolve();else void refresh(pending.afterWrite).then(pending.resolve)}});
 useEffect(()=>()=>{deferred.current?.resolve();deferred.current=null},[]);
 const previousRevision = useRef(revision);
 useEffect(() => {if (previousRevision.current !== revision) {previousRevision.current = revision; void refresh()}}, [revision, refresh]);
 const value = useRef<Coordinator>({register, refresh, report});
 return createElement(CaseData.Provider, {value:owner}, createElement(DetailRefresh.Provider, {value: value.current}, createElement(Fragment, null, [...statuses.values()].some(s=>s.loading)&&createElement('p',{role:'status'},'正在更新案件資料…'), [...statuses.values()].filter(s=>s.error).slice(0,1).map((s,i)=>createElement('div',{role:'alert',key:i},`工程進度更新失敗，顯示上次資料：${s.error}`,createElement('button',{onClick:()=>void refresh(false)},'重試工程進度'))), children)));
}

export function useDetailRefresh(reload: Reload, enabled = true, error = '', loading = false) {
 const coordinator = useContext(DetailRefresh);
 const statusKey=useRef(Symbol());
 useEffect(()=>{if(enabled)coordinator?.report(statusKey.current,error,loading);return()=>coordinator?.report(statusKey.current,'',false)},[coordinator,enabled,error,loading]);
 useEffect(() => enabled ? coordinator?.register(reload) : undefined, [coordinator, reload, enabled]);
 return coordinator?.refresh;
}
