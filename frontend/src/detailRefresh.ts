import {parseProjectProgress} from './projectProgressApi';
import {Fragment, createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {api, getPendingMutations, getSessionEpoch} from './api';
import {usePageOwner, type PageScope, type PageData, type FetchIntent, type PageDependency, type PageValue} from './pageData';
import {useReloadGuard} from './reloadGuard';

let generation = 0;
const resources=new WeakMap<PageData,Map<string,(batch:symbol)=>Promise<unknown>>>();
const CaseData = createContext<PageData | null>(null);
export function caseData(owner?: PageData | null) {
 if (!owner) throw new Error('Case reads require a mounted page owner');
 return owner;
}
export const useCaseData = () => caseData(useContext(CaseData));
export const caseKey = (owner: PageData | undefined, key: string) => caseData(owner).key({endpoint:key});
export type CaseSnapshot={snapshot_id?:string|null;as_of?:string|null;fetched_at?:string|null;verified_at?:string|null;changed_at?:string|null;local_revision?:string|number|null;completeness?:'complete'|'partial'|'unknown';stale?:boolean};
// Source evidence stays unknown when the endpoint has no snapshot; receiving a response is not source freshness.
export const caseValue = <T,>(data:T,meta?:CaseSnapshot):PageValue<T> => {
 const snapshot=meta??(data&&typeof data==='object'&&'snapshot' in data?data.snapshot as CaseSnapshot:undefined);
 return {data,snapshotId:snapshot?.snapshot_id??null,fetchedAt:snapshot?.fetched_at??snapshot?.as_of??null,verifiedAt:snapshot?.verified_at??null,changedAt:snapshot?.changed_at??null,completeness:snapshot?.completeness??'unknown',localRevision:snapshot?.local_revision??null,empty:false,stale:snapshot?.stale===true};
};
const batchReads=new Map<symbol,Map<string,Promise<unknown>>>();
export function readCase<T>(owner:PageData|undefined,key:string,force:boolean|symbol|FetchIntent,load:(current:()=>boolean,intent:FetchIntent,signal:AbortSignal)=>Promise<T>) {
 owner=caseData(owner);
 let loaded=resources.get(owner);if(!loaded){loaded=new Map();resources.set(owner,loaded)}
 loaded.set(key,batch=>readCase(owner,key,batch,load));
 const scoped=owner.key({endpoint:key});
 if(typeof force==='symbol'){const cached=batchReads.get(force)?.get(scoped);if(cached)return cached as Promise<T>}
 const intent:FetchIntent = typeof force==='symbol'?caseIntent(force):typeof force==='object'?force:force?{reason:'explicit_refresh',id:`read-${++generation}`}:{reason:'initial_open'};
 const request=owner.read({endpoint:key},intent,async(signal,current,activeIntent)=>{
  // The legacy progress adapter does not accept intent headers. Route its known
  // resource here until that adapter migrates to requestPageData.
  if(key.startsWith('progress:')){
   const id=key.slice(9);
   const data=parseProjectProgress(await api(`/api/projects/${encodeURIComponent(id)}/progress`,{signal,cache:'no-store',headers:{'X-YX-Fetch-Intent':activeIntent.reason,'X-YX-Fetch-Generation':'id' in activeIntent?activeIntent.id:owner.scope.openId}},current));
   if(data.project_id!==id)throw new Error('工程進度案件不符，請重新讀取。');
   return caseValue(data as unknown as T);
  }
  return caseValue(await load(current,activeIntent,signal));
 }).then(result=>result.data);
 if(typeof force==='symbol'){let reads=batchReads.get(force);if(!reads){reads=new Map();batchReads.set(force,reads)}reads.set(scoped,request)}
 return request;
}
const priorityResources=new WeakMap<PageData,Set<string>>();
export function trackCaseResource<T>(owner:PageData,key:string,load:(signal:AbortSignal,current:()=>boolean,intent:FetchIntent,batch?:symbol)=>Promise<PageValue<T>>,first=false) {
 const refresh=(batch:symbol):Promise<PageValue<T>>=>{
  const scoped=owner.key({endpoint:key}),cached=batchReads.get(batch)?.get(scoped);
  if(cached)return cached as Promise<PageValue<T>>;
  const request=owner.read({endpoint:key},caseIntent(batch),(signal,current,intent)=>load(signal,current,intent,batch));
  let reads=batchReads.get(batch);if(!reads){reads=new Map();batchReads.set(batch,reads)}reads.set(scoped,request);
  return request;
 };
 let loaded=resources.get(owner);if(!loaded){loaded=new Map();resources.set(owner,loaded)}loaded.set(key,refresh);
 if(first){let priority=priorityResources.get(owner);if(!priority){priority=new Set();priorityResources.set(owner,priority)}priority.add(key)}
 return refresh;
}
const batches=new Map<symbol,string>();
const batchReasons=new Map<symbol,'own_write_committed'|'explicit_refresh'>();
export const caseIntent=(batch:symbol):FetchIntent=>({reason:batchReasons.get(batch)??'explicit_refresh',id:batchId(batch)});
function batchId(batch:symbol){let id=batches.get(batch);if(!id){id=`batch-${++generation}`;batches.set(batch,id)}return id}
export function seedCase<T>(owner:PageData|undefined,key:string,data:T,load:(current:()=>boolean,intent:FetchIntent,signal:AbortSignal)=>Promise<T>,track=true,meta?:CaseSnapshot,batch?:symbol) {
 owner=caseData(owner);
 let loaded=resources.get(owner);if(!loaded){loaded=new Map();resources.set(owner,loaded)}
 if(track)loaded.set(key,batch=>readCase(owner,key,batch,load));
 const previous=owner.state<T>({endpoint:key});
 const before='value' in previous?previous.value:'previous' in previous?previous.previous:undefined;
 const seeded=caseValue(data,meta);
 if(!meta&&before){seeded.localRevision=before.localRevision;seeded.fetchedAt=before.fetchedAt;seeded.snapshotId=before.snapshotId;seeded.stale=before.stale}
 owner.seed({endpoint:key},seeded,batch&&batchReasons.get(batch)==='own_write_committed'?batchId(batch):`seed-${++generation}`,async(signal,current,activeIntent)=>caseValue(await load(current,activeIntent,signal)));
 if(batch){let reads=batchReads.get(batch);if(!reads){reads=new Map();batchReads.set(batch,reads)}reads.set(owner.key({endpoint:key}),Promise.resolve(data))}
}
type Reload = (batch: symbol) => void | Promise<unknown>;
type Coordinator = {register: (reload: Reload, first?:boolean) => () => void; refresh: (afterWrite?: boolean) => Promise<void>; commit: (dependencies:readonly PageDependency[])=>Promise<void>; report: (key: symbol, error: string, loading: boolean) => void};
const DetailRefresh = createContext<Coordinator | null>(null);

export function DetailRefreshProvider({children, revision, canRefresh, scope='case',identityFingerprint='standalone'}: {children: ReactNode; revision?: number; canRefresh?: () => boolean; scope?:string;identityFingerprint?:string}) {
 const [openId]=useState(()=>`case-${++generation}`);
 const owner=usePageOwner({workspace:scope,identityFingerprint,openId} satisfies PageScope);
 const [refreshing,setRefreshing]=useState(false);
 const [statuses,setStatuses]=useState(new Map<symbol,{error:string;loading:boolean}>());
 const report=useCallback((key:symbol,error:string,loading:boolean)=>{setStatuses(previous=>{const next=new Map(previous);if(error||loading)next.set(key,{error,loading});else next.delete(key);return next})},[]);
 const guard = useReloadGuard();
 const latest = useRef({canRefresh, blocked: guard.blocked}); latest.current = {canRefresh, blocked: guard.blocked};
 const readers = useRef(new Map<Reload,boolean>());
 const running = useRef<Promise<void> | null>(null);
 const deferred=useRef<{epoch:number;promise:Promise<void>;resolve:()=>void}|null>(null);
 const started=useRef(false),sequence=useRef(0);
 const register = useCallback((reload: Reload,first=false) => {readers.current.set(reload,first); return () => {readers.current.delete(reload)}}, []);
 const reconcileWrite = useCallback(async()=>{
  const batch=Symbol('write');batchId(batch);batchReasons.set(batch,'own_write_committed');
  try {
   // Reconcile hook state from the owner's settled entries, without rereading
   // unrelated resources or invoking aggregate first-screen loaders.
   const reads=new Map<string,Promise<unknown>>();batchReads.set(batch,reads);
   for(const key of resources.get(owner)?.keys()??[]){
    const state=owner.state({endpoint:key});
    if('value' in state)reads.set(owner.key({endpoint:key}),Promise.resolve(state.value.data));
    else if(state.kind==='Loading'){const pending=owner.read({endpoint:key},{reason:'initial_open'},()=>Promise.reject(new Error('Missing case read'))).then(value=>value.data);void pending.catch(()=>{});reads.set(owner.key({endpoint:key}),pending)}
    else if('error' in state){const failed=Promise.reject(state.error);void failed.catch(()=>{});reads.set(owner.key({endpoint:key}),failed)}
   }
   await Promise.allSettled([...readers.current].filter(([,first])=>!first).map(([reload])=>reload(batch)));
  }finally{batchReads.delete(batch);batches.delete(batch);batchReasons.delete(batch)}
 },[owner]);
 useEffect(()=>owner.subscribeWrites(reconcileWrite),[owner,reconcileWrite]);
 const commit=useCallback(async(dependencies:readonly PageDependency[])=>{await owner.ownWriteCommitted(`write-${++generation}`,dependencies).catch(()=>{})},[owner]);
 const refresh = useCallback((_afterWrite = false): Promise<void> => {
  const epoch = getSessionEpoch();
  if(getPendingMutations() || latest.current.blocked() || latest.current.canRefresh?.()===false){
   if(!deferred.current){let resolve=()=>{};const promise=new Promise<void>(done=>{resolve=done});deferred.current={epoch,promise,resolve}}
   return deferred.current.promise;
  }
  if(running.current)return running.current;
  const readSequence=++sequence.current;
  const request = Promise.resolve().then(async () => {
   if (epoch !== getSessionEpoch()) return;
   started.current=true;setRefreshing(true);
   const batch=Symbol(`batch-${++generation}`);batchReasons.set(batch,'explicit_refresh');
   // Aggregate reads seed their dependent resources before those readers join this batch.
   try {await Promise.allSettled([...readers.current].filter(([,first])=>first).map(([reload])=>reload(batch)));
   if(readSequence!==sequence.current)return running.current??undefined;
   await Promise.allSettled([...(priorityResources.get(owner)??[])].map(key=>resources.get(owner)?.get(key)?.(batch)));
   if(readSequence!==sequence.current)return running.current??undefined;
   if(epoch!==getSessionEpoch()||owner.state({endpoint:''}).kind==='Closed')return;
   const active=[...readers.current].filter(([,first])=>!first).map(([reload])=>reload(batch));
   await Promise.allSettled([...active,...[...(resources.get(owner)?.values()??[])].map(reload=>reload(batch))]);
   if(readSequence!==sequence.current)return running.current??undefined;
   } finally {batchReads.delete(batch);batches.delete(batch);batchReasons.delete(batch)}
  }).finally(() => {if (running.current === request) {running.current = null;started.current=false;setRefreshing(false);}});
  running.current = request;
  return request;
 }, [owner]);
 useEffect(()=>{const pending=deferred.current;if(pending&&!guard.blocked()&&canRefresh?.()!==false){deferred.current=null;if(pending.epoch!==getSessionEpoch())pending.resolve();else void refresh(false).then(pending.resolve)}});
 useEffect(()=>()=>{deferred.current?.resolve();deferred.current=null},[]);
 useEffect(()=>{sequence.current++;running.current=null;started.current=false;setRefreshing(false);deferred.current?.resolve();deferred.current=null},[owner]);
 const previousRevision = useRef({revision,owner});
 useEffect(()=>{const previous=previousRevision.current;previousRevision.current={revision,owner};if(previous.owner===owner&&previous.revision!==revision)void refresh(false)},[revision,owner,refresh]);
 const value = useMemo<Coordinator>(()=>({register,refresh,report,commit}),[register,refresh,report,commit]);
 return createElement(CaseData.Provider, {value:owner}, createElement(DetailRefresh.Provider, {value}, createElement(Fragment, null, (refreshing||[...statuses.values()].some(s=>s.loading))&&createElement('p',{role:'status'},'正在更新案件資料…'), [...statuses.values()].filter(s=>s.error).slice(0,1).map((s,i)=>createElement('div',{role:'alert',key:i},`工程進度更新失敗，顯示上次資料：${s.error}`,createElement('button',{onClick:()=>void refresh(false)},'重試工程進度'))), children)));
}

export function useDetailRefresh(reload: Reload, enabled = true, error = '', loading = false, first=false) {
 const coordinator = useContext(DetailRefresh);
 const statusKey=useRef(Symbol());
 useEffect(()=>{if(enabled)coordinator?.report(statusKey.current,error,loading);return()=>coordinator?.report(statusKey.current,'',false)},[coordinator,enabled,error,loading]);
 useEffect(() => enabled ? coordinator?.register(reload,first) : undefined, [coordinator, reload, enabled,first]);
 return coordinator?.refresh;
}

export function useCaseWrite(){const coordinator=useContext(DetailRefresh);if(!coordinator)throw new Error('Writes require a mounted page owner');return coordinator.commit}
