import {api,type ApiRequestInit,getSessionEpoch,onSessionEpochChange} from './api';

export type ReasonOfFetch='initial_open'|'user_query_change'|'own_write_committed'|'own_write_outcome_unknown_recovery'|'explicit_refresh'|'app_restart';
export type FetchIntent={reason:'initial_open'|'user_query_change'}|{reason:Exclude<ReasonOfFetch,'initial_open'|'user_query_change'>;id:string};
export type PageScope=Readonly<{workspace:string;identityFingerprint:string;openId:string}>;
export type ResourceQuery=Readonly<Record<string,string|number|boolean|null|readonly (string|number|boolean|null)[]>>;
export type PageResource=Readonly<{endpoint:string;query?:ResourceQuery}>;
export type PageValue<T>={data:T;snapshotId:string|null;fetchedAt:string|null;verifiedAt:string|null;changedAt:string|null;completeness:'complete'|'partial'|'unknown';localRevision:string|number|null;empty:boolean;stale:boolean};
export type PageDataState<T>=
 |{kind:'Loading'}
 |{kind:'Ready'|'Empty'|'Stale'|'Partial';value:PageValue<T>}
 |{kind:'Error'|'Denied'|'Conflict';error:unknown}
 |{kind:'UnknownOutcome';requestId:string};
export type PageLoader<T>=(signal:AbortSignal,isCurrent:()=>boolean,intent:FetchIntent)=>Promise<PageValue<T>>;
type Entry={controller:AbortController;promise:Promise<PageValue<unknown>>;state:PageDataState<unknown>;intents:Set<string>;load:PageLoader<unknown>};
const loading={kind:'Loading'} satisfies PageDataState<never>;
const abortError=()=>new DOMException('Page scope closed or read superseded','AbortError');
const allowed:readonly string[]=['initial_open','user_query_change','own_write_committed','own_write_outcome_unknown_recovery','explicit_refresh','app_restart'];
export function normalizeQuery(query:ResourceQuery={}):string{
 return JSON.stringify(Object.keys(query).sort().map(key=>[key,query[key]]));
}
export function createPageData(scope:PageScope){
 const epoch=getSessionEpoch();
 const namespace=JSON.stringify([epoch,scope.workspace,scope.identityFingerprint,scope.openId]);
 const entries=new Map<string,Entry>();
 let closed=false;
 const listeners=new Map<string,Set<()=>void>>();
 const notify=(ident:string)=>{for(const listener of listeners.get(ident)??[])listener()};
 const subscribe=(resource:PageResource,listener:()=>void)=>{const ident=key(resource);let group=listeners.get(ident);if(!group){group=new Set();listeners.set(ident,group)}group.add(listener);return()=>{group.delete(listener);if(!group.size)listeners.delete(ident)}};
 const key=(resource:PageResource)=>JSON.stringify([namespace,resource.endpoint,normalizeQuery(resource.query)]);
 const active=()=>!closed&&epoch===getSessionEpoch();
 const close=()=>{if(closed)return;closed=true;for(const entry of entries.values())entry.controller.abort();entries.clear();for(const ident of listeners.keys())notify(ident);listeners.clear();unsubscribe()};
 const unsubscribe=onSessionEpochChange(close);
 function read<T>(resource:PageResource,intent:FetchIntent,load:PageLoader<T>):Promise<PageValue<T>>{
  if(!active())return Promise.reject(abortError());
  if(!allowed.includes(intent.reason)||(!['initial_open','user_query_change'].includes(intent.reason)&&(!('id' in intent)||!intent.id)))return Promise.reject(new Error('Invalid fetch intent'));
  const ident=key(resource),previous=entries.get(ident);
  const token='id' in intent?JSON.stringify([intent.reason,intent.id]):'initial';
  if(previous&&(token==='initial'||previous.intents.has(token)))return previous.promise as Promise<PageValue<T>>;
  previous?.controller.abort();
  const controller=new AbortController();
  const current=()=>active()&&!controller.signal.aborted&&entries.get(ident)===entry;
  let cancel:()=>void=()=>{};
  const cancelled=new Promise<never>((_resolve,reject)=>{cancel=()=>reject(abortError());controller.signal.addEventListener('abort',cancel,{once:true})});
  const work=Promise.resolve().then(()=>{if(!current())throw abortError();return load(controller.signal,current,intent)}).then(value=>{
   if(!current())throw abortError();
   entry.state=valueState(value);notify(ident);
   return value;
  });
  const promise=Promise.race([work,cancelled]).catch((error:unknown)=>{
   if(current()){
    const status=error&&typeof error==='object'&&'status' in error?error.status:null;
    entry.state={kind:status===401||status===403?'Denied':status===409?'Conflict':'Error',error};notify(ident);
   }
   throw error;
  }).finally(()=>controller.signal.removeEventListener('abort',cancel));
  const entry:Entry={controller,promise,state:loading,intents:new Set(previous?.intents),load};
  entry.intents.add(token);entries.set(ident,entry);notify(ident);
  return promise as Promise<PageValue<T>>;
 }
 function ownWriteCommitted(id:string,dependencies:readonly PageResource[]):Promise<unknown[]>{
  const unique=new Map(dependencies.map(resource=>[key(resource),resource]));
  return Promise.all([...unique].flatMap(([ident,resource])=>{
   const entry=entries.get(ident);
   return entry?[read(resource,{reason:'own_write_committed',id},entry.load)]:[];
  }));
 }
 function seed<T>(resource:PageResource,value:PageValue<T>,requestId:string,load:PageLoader<T>){
  if(!active())throw abortError();
  const state=valueState(value),ident=key(resource),previous=entries.get(ident);
  if(previous&&'value' in previous.state&&typeof previous.state.value.localRevision==='number'&&typeof value.localRevision==='number'&&value.localRevision<previous.state.value.localRevision)return;
  previous?.controller.abort();
  entries.set(ident,{controller:new AbortController(),promise:Promise.resolve(value),load,intents:new Set([...(previous?.intents??[]),JSON.stringify(['own_write_committed',requestId])]),state});notify(ident);
 }
 function unknownOutcome(resource:PageResource,requestId:string){
  if(!active())throw abortError();
  const ident=key(resource),previous=entries.get(ident);
  previous?.controller.abort();
  const error=new Error(`Write outcome unknown: ${requestId}`);
  const promise=Promise.reject<PageValue<unknown>>(error);
  void promise.catch(()=>{});
  entries.set(ident,{controller:new AbortController(),promise,state:{kind:'UnknownOutcome',requestId},intents:new Set(previous?.intents),load:previous?.load??(()=>Promise.reject(error))});
  notify(ident);
 }
 function state<T>(resource:PageResource):PageDataState<T>{
  return ((active()?entries.get(key(resource))?.state:undefined) as PageDataState<T>|undefined)??loading;
 }
 return {key,read,state,subscribe,seed,ownWriteCommitted,unknownOutcome,close,epoch,scope:Object.freeze({...scope})};
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
  const body=await api<unknown>(resource.endpoint+(query.size?'?'+query:''),{...init,method:'GET',body:undefined,signal,headers,cache:'reload',cacheScope:owner.key(resource)},current);
  return decode(body);
 });
}
