import {parseInstant, taipeiDate} from './taipeiTime';
import {api, ApiError, getSessionEpoch} from './api';
import type {PortfolioPage} from './projectsListModel';
import type {ProjectPage} from './appCommon';
import type {CompanyDashboard} from './companyDashboardTypes';

const snapshots=new Map<string,CompanyDashboard>();
const savedAt=new Map<string,number>();
let namespace=-1;
function key(version:number,params:string){
 const epoch=getSessionEpoch();
 if(epoch!==namespace){snapshots.clear();savedAt.clear();namespace=epoch}
 return JSON.stringify([version,params]);
}
export function cachedDashboard(version:number,params:string){
 return snapshots.get(key(version,params));
}
export function rememberDashboard(epoch:number,version:number,params:string,data:CompanyDashboard){
 if(epoch!==getSessionEpoch())return;
 snapshots.set(key(version,params),data);savedAt.set(key(version,params),Date.now());
 if(snapshots.size>32){const oldest=snapshots.keys().next();if(!oldest.done){snapshots.delete(oldest.value);savedAt.delete(oldest.value)}}
}

type PendingRead<T>={promise:Promise<T>;controller:AbortController;readers:Set<AbortSignal>};
function panelReader<T>(){
 const panels=new Map<string,T>();
 const pending=new Map<string,PendingRead<T>>();
 const latest=new Map<string,AbortController>();
 let epoch=-1;
 function key(url:string,scope:string){
  const current=getSessionEpoch();
  if(current!==epoch){for(const read of pending.values())read.controller.abort();pending.clear();panels.clear();latest.clear();epoch=current}
  return JSON.stringify([current,scope,url]);
 }
 const cached=(url:string,scope='')=>panels.get(key(url,scope));
 const read=(url:string,signal:AbortSignal,scope='',{timeoutMs=15000,reloadVersion=0}:{timeoutMs?:number;reloadVersion?:unknown}={}):Promise<T>=>{
  const ident=key(url,scope),flight=JSON.stringify([ident,reloadVersion]),started=getSessionEpoch();
  let entry=pending.get(flight);
  if(!entry){
   const controller=new AbortController();latest.set(ident,controller);
   const promise=api<T>(url,{signal:controller.signal,cache:'no-store',timeoutMs},()=>started===getSessionEpoch())
    .then(body=>{if(!controller.signal.aborted&&started===getSessionEpoch()&&latest.get(ident)===controller){
     panels.set(ident,body);
     if(panels.size>32){const oldest=panels.keys().next();if(!oldest.done)panels.delete(oldest.value)}
    }return body})
    .catch(error=>{if(latest.get(ident)===controller&&error instanceof ApiError&&(error.status===401||error.status===403))panels.delete(ident);throw error})
    .finally(()=>{if(pending.get(flight)?.controller===controller)pending.delete(flight)});
   entry={promise,controller,readers:new Set()};pending.set(flight,entry);
  }
  const shared=entry;
  shared.readers.add(signal);
  const release=()=>{
   shared.readers.delete(signal);
   if(!shared.readers.size&&pending.get(flight)===shared){pending.delete(flight);shared.controller.abort()}
  };
  signal.addEventListener('abort',release,{once:true});
  if(signal.aborted)release();
  return shared.promise.finally(()=>{signal.removeEventListener('abort',release);shared.readers.delete(signal)});
 };
 return {cached,read};
}
const panels=panelReader<unknown>();
export const cachedPanel=panels.cached;
export const readPanel=panels.read;
const portfolios=panelReader<PortfolioPage>();
export const cachedPortfolio=portfolios.cached;
export const readPortfolio=portfolios.read;
const projects=panelReader<ProjectPage>();
export const cachedProjects=projects.cached;
export const readProjects=projects.read;
const dashboards=panelReader<CompanyDashboard>();
export const readDashboard=dashboards.read;

export function dashboardIsFresh(version:number,params:string){return Date.now()-(savedAt.get(key(version,params))??0)<60000}

export type TableValueKind = 'text' | 'number' | 'date';
export function tableNumber(value: unknown): number | null {
 if (typeof value === 'number') return Number.isFinite(value) ? value : null;
 if (typeof value !== 'string' || !value.trim()) return null;
 const text = value.trim().replaceAll(',', '');
 if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return null;
 const number = Number(text);
 return Number.isFinite(number) ? number : null;
}
export function tableDate(value: unknown): number | null {
 if (typeof value === 'number') return Number.isFinite(value) ? value : null;
 if (typeof value !== 'string' || !value.trim()) return null;
 if (/^\d{13}$/.test(value.trim())) return Number(value);
 const stamp = parseInstant(value);
 return Number.isFinite(stamp) ? stamp : null;
}
export function compareTableValues(a: unknown, b: unknown, kind: TableValueKind, direction: 'asc' | 'desc' = 'asc'): number {
 const normalize = (v: unknown) => kind === 'number' ? tableNumber(v) : kind === 'date' ? tableDate(v) : typeof v === 'string' && v.trim() ? v.trim() : null;
 const left = normalize(a), right = normalize(b);
 if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
 const result = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right), 'zh-Hant', {numeric: true});
 return direction === 'desc' ? -result : result;
}
export function tableCalendarDay(value: unknown): string | null {
 const stamp = tableDate(value);
 return stamp === null ? null : taipeiDate(new Date(stamp).toISOString(), '').replaceAll('/', '-');
}
export function populationLabel(matching: number | null | undefined, loaded: number, complete: boolean): string {
 return `符合條件 ${matching == null ? '未知' : matching} 筆 · 本頁已載入 ${loaded} 筆 · ${complete ? '已授權範圍' : '部分資料，總數未知'}`;
}
