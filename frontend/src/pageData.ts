import {useEffect,useMemo,useSyncExternalStore} from 'react';
import {api,type ApiRequestInit,getSessionEpoch,onSessionEpochChange} from './api';

export type ReasonOfFetch='initial_open'|'user_query_change'|'own_write_committed'|'own_write_outcome_unknown_recovery'|'explicit_refresh'|'app_restart';
export type FetchIntent={reason:'initial_open'|'user_query_change'}|{reason:Exclude<ReasonOfFetch,'initial_open'|'user_query_change'>;id:string};
export type PageScope=Readonly<{workspace:string;identityFingerprint:string;openId:string}>;
export type ResourceQuery=Readonly<Record<string,string|number|boolean|null|readonly (string|number|boolean|null)[]>>;
export type PageResource=Readonly<{endpoint:string;query?:ResourceQuery;tags?:readonly string[]}>;
export type PageValue<T>={data:T;snapshotId:string|null;fetchedAt:string|null;verifiedAt:string|null;changedAt:string|null;completeness:'complete'|'partial'|'unknown';localRevision:string|number|null;empty:boolean;stale:boolean};
export type PageDataState<T>=
 |{kind:'Loading'}
 |{kind:'Closed';error:ScopeClosedError}
 |{kind:'Ready'|'Empty'|'Stale'|'Partial';value:PageValue<T>}
 |{kind:'Error'|'Denied'|'Conflict';error:unknown;previous?:PageValue<T>}
 |{kind:'UnknownOutcome';requestId:string;previous?:PageValue<T>};
export type PageLoader<T>=(signal:AbortSignal,isCurrent:()=>boolean,intent:FetchIntent)=>Promise<PageValue<T>>;
type Entry={resource:PageResource;controller:AbortController;promise:Promise<PageValue<unknown>>;state:PageDataState<unknown>;token:string;pending:boolean;load:PageLoader<unknown>};
export type PageDependency=PageResource|{endpointPrefix:string}|{tag:string}|((resource:PageResource)=>boolean);
export class ScopeClosedError extends DOMException {constructor(){super('Page scope closed or session changed','AbortError')}}
const loading={kind:'Loading'} satisfies PageDataState<never>;
const abortError=()=>new ScopeClosedError();
type LiveOwner={epoch:number;scope:PageScope;invalidate:(id:string,dependencies:readonly PageDependency[])=>Promise<unknown[]>};
const liveOwners=new Set<LiveOwner>();
const retained=<T>(state?:PageDataState<T>):PageValue<T>|undefined=>state&&('value' in state?state.value:'previous' in state?state.previous:undefined);
const allowed:readonly string[]=['initial_open','user_query_change','own_write_committed','own_write_outcome_unknown_recovery','explicit_refresh','app_restart'];
export function normalizeQuery(query:ResourceQuery={}):string{
 return JSON.stringify(Object.keys(query).sort().map(key=>[key,query[key]]));
}
function revisionRegresses(before:string|number,next:string|number|null):boolean{
 if(next===null||typeof before!==typeof next)return true;
 if(typeof before==='string'&&typeof next==='string'&&/^\d+$/.test(before)&&/^\d+$/.test(next))return BigInt(next)<BigInt(before);
 return next<before;
}
export function createPageData(scope:PageScope){
 scope=Object.freeze({...scope});
 const epoch=getSessionEpoch();
 const namespace=JSON.stringify([epoch,scope.workspace,scope.identityFingerprint,scope.openId]);
 const entries=new Map<string,Entry>();
 let closed=false;
 const listeners=new Map<string,Set<()=>void>>();
 const notify=(ident:string)=>{for(const listener of listeners.get(ident)??[])listener()};
 const subscribe=(resource:PageResource,listener:()=>void)=>{if(active())activate();const ident=key(resource);let group=listeners.get(ident);if(!group){group=new Set();listeners.set(ident,group)}group.add(listener);return()=>{group.delete(listener);if(!group.size)listeners.delete(ident)}};
 const key=(resource:PageResource)=>JSON.stringify([namespace,resource.endpoint,normalizeQuery(resource.query)]);
 const active=()=>!closed&&epoch===getSessionEpoch();
 const closedState={kind:'Closed',error:abortError()} as const;
 let unsubscribe:(()=>void)|undefined;
 const activate=()=>{if(!active())throw abortError();if(!unsubscribe){unsubscribe=onSessionEpochChange(close);liveOwners.add(registration)}};
 const close=()=>{if(closed)return;closed=true;for(const entry of entries.values())entry.controller.abort();entries.clear();for(const ident of listeners.keys())notify(ident);listeners.clear();unsubscribe?.();unsubscribe=undefined;liveOwners.delete(registration)};
 const appliedWrites=new Map<string,Promise<unknown[]>>();
 function read<T>(resource:PageResource,intent:FetchIntent,load:PageLoader<T>):Promise<PageValue<T>>{
  if(!active())return Promise.reject(abortError());
  activate();
  if(!allowed.includes(intent.reason)||(!['initial_open','user_query_change'].includes(intent.reason)&&(!('id' in intent)||!intent.id)))return Promise.reject(new Error('Invalid fetch intent'));
  const ident=key(resource),previous=entries.get(ident);
  const token='id' in intent?JSON.stringify([intent.reason,intent.id]):'initial';
  if(previous&&(token==='initial'||previous.pending&&previous.token===token))return previous.promise as Promise<PageValue<T>>;
  const controller=new AbortController();
  const current=()=>active()&&!controller.signal.aborted&&entries.get(ident)===entry;
  let cancel:()=>void=()=>{};
  const cancelled=new Promise<never>((_resolve,reject)=>{cancel=()=>reject(abortError());controller.signal.addEventListener('abort',cancel,{once:true})});
  const work=Promise.resolve().then(()=>{if(!current())throw abortError();return load(controller.signal,current,intent)}).then(value=>{
   if(!current())throw abortError();
   entry.state=valueState(value);notify(ident);return value;
  });
  const promise=Promise.race([work,cancelled]).catch((error:unknown)=>{
   // Adopt the entire successor chain, including seeds. Ignore late old failures.
   const successor=entries.get(ident);
   if(active()&&successor&&successor!==entry)return successor.promise;
   if(current()){
    const status=error&&typeof error==='object'&&'status' in error?error.status:null;
    entry.state={kind:status===401||status===403?'Denied':status===409?'Conflict':'Error',error,previous:retained(entry.state)};notify(ident);
   }
   throw error;
  }).finally(()=>{entry.pending=false;controller.signal.removeEventListener('abort',cancel)});
  const before=retained(previous?.state);
  const entry:Entry={resource,controller,promise,state:before?valueState({...before,stale:true}):loading,token,pending:true,load};
  entries.set(ident,entry);previous?.controller.abort();notify(ident);
  return promise as Promise<PageValue<T>>;
 }
 function invalidateLocal(id:string,dependencies:readonly PageDependency[]):Promise<unknown[]>{
  const pending=appliedWrites.get(id);if(pending)return pending;
  const completion=Promise.all([...entries.values()].filter(entry=>dependencies.some(dependency=>
   typeof dependency==='function'?dependency(entry.resource):'endpointPrefix' in dependency?entry.resource.endpoint.startsWith(dependency.endpointPrefix):'tag' in dependency?entry.resource.tags?.includes(dependency.tag):key(dependency)===key(entry.resource)
  )).filter(entry=>entry.token!==JSON.stringify(['own_write_committed',id])).map(entry=>read(entry.resource,{reason:'own_write_committed',id},entry.load)));
  appliedWrites.set(id,completion);return completion;
 }
 function ownWriteCommitted(id:string,dependencies:readonly PageDependency[]):Promise<unknown[]>{
  activate();
  return Promise.all([...liveOwners].filter(other=>other.epoch===epoch&&other.scope.workspace===scope.workspace&&other.scope.identityFingerprint===scope.identityFingerprint).map(other=>other.invalidate(id,dependencies))).then(results=>results.flat());
 }
 function seed<T>(resource:PageResource,value:PageValue<T>,requestId:string,load:PageLoader<T>){
  activate();
  const state=valueState(value),ident=key(resource),previous=entries.get(ident),old=retained(previous?.state)?.localRevision;
  // Revisions must share an ordered representation (numbers, integer strings, ISO dates, or
  // lexically sortable strings). Refuse incomparable replacements.
  if(old!=null&&revisionRegresses(old,value.localRevision))return;
  entries.set(ident,{resource,controller:new AbortController(),promise:Promise.resolve(value),load,token:JSON.stringify(['own_write_committed',requestId]),pending:false,state});
  previous?.controller.abort();notify(ident);
 }
 function unknownOutcome(resource:PageResource,requestId:string){
  activate();
  const ident=key(resource),previous=entries.get(ident);
  const error=new Error(`Write outcome unknown: ${requestId}`);
  const promise=Promise.reject<PageValue<unknown>>(error);void promise.catch(()=>{});
  entries.set(ident,{resource,controller:new AbortController(),promise,state:{kind:'UnknownOutcome',requestId,previous:retained(previous?.state)},token:'unknown',pending:false,load:previous?.load??(()=>Promise.reject(error))});
  previous?.controller.abort();notify(ident);
 }
 function state<T>(resource:PageResource):PageDataState<T>{
  return active()?(entries.get(key(resource))?.state as PageDataState<T>|undefined)??loading:closedState;
 }
 const registration:LiveOwner={epoch,scope,invalidate:invalidateLocal};
 const owner={key,read,state,subscribe,seed,ownWriteCommitted,unknownOutcome,close,epoch,scope};
 return owner;
}
function valueState<T>(value:PageValue<T>):PageDataState<T>{
 if(value.empty&&value.completeness!=='complete')throw new Error('Empty requires a complete successful read');
 return {kind:value.stale?'Stale':value.completeness!=='complete'?'Partial':value.empty?'Empty':'Ready',value};
}
export type PageData=ReturnType<typeof createPageData>;

export function requestPageData<T>(owner:PageData,resource:PageResource,intent:FetchIntent,decode:(body:unknown)=>PageValue<T>,init:ApiRequestInit={}){
 return owner.read(resource,intent,async(signal,current,activeIntent)=>{
  const query=new URLSearchParams();
  for(const name of Object.keys(resource.query??{}).sort()){
   const value=resource.query?.[name];
   for(const item of Array.isArray(value)?value:[value])if(item!==null&&item!==undefined)query.append(name,String(item));
  }
  const headers=new Headers(init.headers);
  headers.set('Cache-Control','no-cache');
  headers.set('X-YX-Fetch-Intent',activeIntent.reason);
  headers.set('X-YX-Fetch-Generation','id' in activeIntent?activeIntent.id:owner.scope.openId);
  const body=await api<unknown>(resource.endpoint+(query.size?'?'+query:''),{...init,method:'GET',body:undefined,signal,headers,etag:true,cache:['initial_open','user_query_change'].includes(activeIntent.reason)?'no-cache':'reload',cacheScope:owner.key(resource)},current);
  return decode(body);
 });
}

/** One owner per mounted page/open generation. Scope values (including grants)
 * and the reactive session epoch isolate all data. No subscriptions during render.
 * StrictMode reuses the owner across its effect replay; real unmount closes it.
 */
export function usePageOwner(scope:PageScope):PageData{
 const epoch=useSyncExternalStore(onSessionEpochChange,getSessionEpoch,getSessionEpoch);
 const owner=useMemo(()=>createPageData(scope),[epoch,scope.workspace,scope.identityFingerprint,scope.openId]);
 useEffect(()=>{
  const lease={};ownerLeases.set(owner,lease);
  return()=>{queueMicrotask(()=>{if(ownerLeases.get(owner)===lease){ownerLeases.delete(owner);owner.close()}})};
 },[owner]);
 return owner;
}
const ownerLeases=new WeakMap<PageData,object>();
