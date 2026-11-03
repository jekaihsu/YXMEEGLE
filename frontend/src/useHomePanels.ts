import {createContext,createElement,useContext,useEffect,useState,useCallback,useSyncExternalStore,type ReactNode} from 'react';
import {ApiError} from './api';
import {usePageOwner,requestPageData,type PageData,type PageValue,type PageResource,type FetchIntent} from './pageData';
import {useDebounce} from './reports/useReport';
import type {Ctx} from './appCommon';

export const HOME_PANELS = ['assigned', 'proxy', 'confirmation', 'delegated', 'completed', 'local'] as const;
export type HomePanel = typeof HOME_PANELS[number];
export const HOME_KINDS = ['node_assignment','task','local_workflow','local_confirmation','local_assignment','sop_task'] as const;
export type HomePerson = {id:string; name:string; avatar_url:string|null};
export type HomeTarget = {view:'project'; project:string; tab:'flow'; node?:string; task?:string; assignment_node?:string; assignment_task?:string; task_source?:'sop_local'; section?:string};
export type HomeItem = {
 id:string; kind:typeof HOME_KINDS[number]; origin:'lark'|'local_workflow'|'sop_local'; title:string; status:string; source_status:string|null;
 case:{id:string|null; code:string|null; name:string|null; relation_state:string};
 assignees:HomePerson[]; assigned_by:HomePerson|null; assignment_state:string;
 deadline:string|null; next_due:string|null; original_deadline:string|null; deadline_basis:string;
 children?:{id:string;title:string;deadline:string|null;status:string;assignee:HomePerson|null;detail:string}[];
 can_execute:boolean; blocked_reasons:string[]; target:HomeTarget|null; detail:string|null;
 overdue:boolean; due_today:boolean; assignment_method?:string|null;
 home_detail?:{proxy?:{principal_name:string; start_date:string; end_date:string; basis:string}; prerequisites?:{task_id:string; title:string|null; ready:boolean}[]};
};
export type HomeResponse = {
 panel:HomePanel; scope:'mine'|'team'; readState:string; snapshot_version:string; as_of:string|null;
 freshness:{status:string; last_success_at:string|null; refreshing:boolean};
 counts:{node_assignments:number|null; tasks:number|null; local_workflow:number|null; sop_tasks?:number|null; complete:boolean};
 items:HomeItem[]; next_cursor:string|null; has_more:boolean; complete:boolean; total_count:number|null;
 manager_view_available:boolean|null;
};
export type PanelRead = {body:HomeResponse|null; pending:boolean; error:string|null;denied?:boolean;retry?:()=>void};
export type HomeQuery = {panel:HomePanel; scope?:'mine'|'team'; deadline?:string; q?:string; cursor?:string; kinds?:string; limit?:number};
const object = (v:unknown):v is Record<string,unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const nullableText = (v:unknown):v is string|null => v === null || typeof v === 'string';
const count = (v:unknown):v is number|null => v === null || (typeof v === 'number' && Number.isInteger(v) && v >= 0);
const person = (v:unknown):v is HomePerson => object(v) && typeof v.id === 'string' && typeof v.name === 'string' && nullableText(v.avatar_url);
function target(v:unknown):v is HomeTarget {
 return object(v) && v.view === 'project' && typeof v.project === 'string' && v.tab === 'flow' &&
  ['node','task','assignment_node','assignment_task','section'].every(key => v[key] === undefined || typeof v[key] === 'string') && (v.task_source === undefined || v.task_source === 'sop_local');
}
function children(v:unknown):boolean {
 return v === undefined || (Array.isArray(v) && v.every(child=>object(child) && ['id','title','status','detail'].every(key=>typeof child[key]==='string') && nullableText(child.deadline) && (child.assignee===null || person(child.assignee))));
}
function homeDetail(v:unknown):boolean {
 if (v === undefined) return true;
 if (!object(v)) return false;
 const proxy=v.proxy;
 return !proxy || (object(proxy) && ['principal_name','start_date','end_date','basis'].every(key=>typeof proxy[key]==='string'));
}
function item(v:unknown):v is HomeItem {
 return object(v) && ['id','kind','title','status','assignment_state','deadline_basis'].every(key => typeof v[key] === 'string') &&
  HOME_KINDS.some(kind=>kind===v.kind) && (v.origin === 'lark' || v.origin === 'local_workflow' || v.origin === 'sop_local') && nullableText(v.source_status) &&
  object(v.case) && nullableText(v.case.id) && nullableText(v.case.code) && nullableText(v.case.name) && typeof v.case.relation_state === 'string' &&
  Array.isArray(v.assignees) && v.assignees.every(person) && (v.assigned_by === null || person(v.assigned_by)) &&
  nullableText(v.deadline) && nullableText(v.next_due) && nullableText(v.original_deadline) &&
  typeof v.can_execute === 'boolean' && typeof v.overdue === 'boolean' && typeof v.due_today === 'boolean' &&
  Array.isArray(v.blocked_reasons) && v.blocked_reasons.every(r => typeof r === 'string') && nullableText(v.detail) &&
  (v.target === null || target(v.target)) &&
  (v.kind !== 'sop_task' || v.origin === 'sop_local' && target(v.target) && v.target.task_source === 'sop_local' && typeof v.target.task === 'string') && homeDetail(v.home_detail) && children(v.children);
}
export function parseHomeResponse(v:unknown):HomeResponse {
 const panel=object(v) ? HOME_PANELS.find(p=>p===v.panel) : undefined;
 if (!object(v) || !panel || (v.scope !== 'mine' && v.scope !== 'team') ||
  typeof v.readState !== 'string' || typeof v.snapshot_version !== 'string' || !nullableText(v.as_of) || (v.as_of!==null && !Number.isFinite(Date.parse(v.as_of))) ||
  !object(v.freshness) || typeof v.freshness.status !== 'string' || !nullableText(v.freshness.last_success_at) || typeof v.freshness.refreshing !== 'boolean' ||
  !object(v.counts) || !count(v.counts.node_assignments) || !count(v.counts.tasks) || !count(v.counts.local_workflow) || (v.counts.sop_tasks !== undefined && !count(v.counts.sop_tasks)) || typeof v.counts.complete !== 'boolean' ||
  !Array.isArray(v.items) || !v.items.every(item) || !nullableText(v.next_cursor) || typeof v.has_more !== 'boolean' ||
  typeof v.complete !== 'boolean' || !count(v.total_count) || (v.manager_view_available !== null && typeof v.manager_view_available !== 'boolean')) {
  throw new Error('工作資料格式待核對');
 }
 return {...v, panel, scope:v.scope, readState:v.readState, snapshot_version:v.snapshot_version, as_of:v.as_of,
  freshness:{status:v.freshness.status,last_success_at:v.freshness.last_success_at,refreshing:v.freshness.refreshing},
  counts:{node_assignments:v.counts.node_assignments,tasks:v.counts.tasks,local_workflow:v.counts.local_workflow,sop_tasks:v.counts.sop_tasks??null,complete:v.counts.complete},
  items:v.items,next_cursor:v.next_cursor,has_more:v.has_more,complete:v.complete,total_count:v.total_count,manager_view_available:v.manager_view_available};
}
export function homePanelUrl(query:HomeQuery, full=false) {
 const params = new URLSearchParams({sort:'urgency',limit:String(query.limit ?? (full ? 50 : 25))});
 for (const [key,value] of Object.entries(query)) if (value !== undefined && value !== '') params.set(key,String(value));
 if (full && query.panel==='assigned') params.set('kinds',query.kinds ?? 'node_assignment,task,sop_task');
 return `${full ? '/api/my-work' : '/api/home-panels'}?${params}`;
}
// Lazy Home views and normalized Work queries share the mounted page owner.
const generations=new WeakMap<PageData,Map<string,{revision:number;retries:Set<string>}>>();
export const HomeDataContext=createContext<PageData|null>(null);
function useHomeOwner(c:Ctx){
 const shared=useContext(HomeDataContext);
 const [openId]=useState(()=>crypto.randomUUID());
 const user=c.s.user;
 const identityFingerprint=JSON.stringify([c.s.mode,c.s.environment,c.s.access_mode,user?.id,user?.name,user?.role,user?.department,user?.default_workspace,user?.active,user?.authz_version,user?.can_business_override,user?.can_mention,[...(user?.capabilities??[])].sort(),Object.entries(c.s.features??{}).sort(([a],[b])=>a.localeCompare(b))]);
 const owner=usePageOwner({workspace:c.s.workspace_id||c.w?.workspace_id||'',identityFingerprint,openId});
 return shared??owner;
}
export function HomeDataProvider({c,children}:{c:Ctx;children:ReactNode}){
 const owner=useHomeOwner(c);
 return createElement(HomeDataContext.Provider,{value:owner},children);
}
export function homeValue<T>(data:T,complete=true,asOf:string|null=null):PageValue<T>{
 return {data,snapshotId:null,fetchedAt:asOf,verifiedAt:asOf,changedAt:null,completeness:complete?'complete':'partial',localRevision:null,empty:false,stale:false};
}
export function useHomeResource<T>(c:Ctx,resource:PageResource,decode:(raw:unknown)=>PageValue<T>,enabled=true){
 const owner=useHomeOwner(c),[retryId,setRetryId]=useState('');
 const revision=c.reloadVersion??c.w?.version??0;
 const key=owner.key(resource),generation=JSON.stringify([revision,retryId]);
 const subscribe=useCallback((notify:()=>void)=>owner.subscribe(resource,notify),[owner,key]);
 const snapshot=useCallback(()=>owner.state<T>(resource),[owner,key]);
 const state=useSyncExternalStore(subscribe,snapshot,snapshot);
 useEffect(()=>{
  if(!enabled)return;
  let seen=generations.get(owner);if(!seen){seen=new Map();generations.set(owner,seen)}
  const previous=seen.get(key);
  const retry=!!retryId&&!previous?.retries.has(retryId);
  const intent:FetchIntent=previous===undefined?{reason:'initial_open'}:previous.revision===revision&&!retry?{reason:'user_query_change'}:{reason:'explicit_refresh',id:retry?retryId:`workspace:${revision}`};
  const retries=previous?.retries??new Set<string>();if(retryId)retries.add(retryId);
  seen.set(key,{revision,retries});
  void requestPageData(owner,resource,intent,decode,{timeoutMs:35000}).catch(()=>{});
 },[owner,key,generation,enabled]);
 const value='value' in state?state.value:'previous' in state?state.previous:undefined;
 const visible=enabled&&state.kind!=='Closed'&&state.kind!=='Denied';
 return {data:visible?value?.data:undefined,dataTime:visible?value?.fetchedAt??null:null,loading:enabled&&(state.kind==='Loading'||state.kind==='Stale'),error:enabled&&'error' in state?state.error:null,retry:()=>setRetryId(crypto.randomUUID()),owner};
}
export function useHomePanels(c:Ctx,query:HomeQuery,enabled=true,full=false):PanelRead{
 const search=useDebounce(query.q??'');
 const url=new URL(homePanelUrl({...query,q:search},full||c.s.access_mode==='tenant-read'),'http://home');
 const resource={endpoint:url.pathname,query:Object.fromEntries(url.searchParams)};
 const read=useHomeResource(c,resource,raw=>{const body=parseHomeResponse(raw);return homeValue(body,body.complete,body.as_of)},enabled);
 const denied=read.error instanceof ApiError&&(read.error.status===401||read.error.status===403);
 return {denied,body:enabled&&!denied?read.data??null:null,pending:query.q!==undefined&&query.q!==search||read.loading,error:read.error?read.error instanceof ApiError&&read.error.status===403?'無法核實工作讀取權限，請切換視圖或洽管理員。':read.error instanceof ApiError&&read.error.status===409?'清單已更新，請回第一頁':`更新失敗${read.data?`；保留上次資料。資料時間：${read.dataTime??'未提供'}`:''}`:null,retry:read.retry};
}
