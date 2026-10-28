import {Fragment, createContext, createElement, useCallback, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {getPendingMutations, getSessionEpoch} from './api';
import {useReloadGuard} from './reloadGuard';

export const DETAIL_RETURN_REFRESH_MS = 60000;
type Reload = (batch: symbol) => void | Promise<unknown>;
type Coordinator = {register: (reload: Reload) => () => void; refresh: (afterWrite?: boolean) => Promise<void>; report: (key: symbol, error: string, loading: boolean) => void};
const DetailRefresh = createContext<Coordinator | null>(null);

export function DetailRefreshProvider({children, revision, canRefresh}: {children: ReactNode; revision?: number; canRefresh?: () => boolean}) {
 const [statuses,setStatuses]=useState(new Map<symbol,{error:string;loading:boolean}>());
 const report=useCallback((key:symbol,error:string,loading:boolean)=>{setStatuses(previous=>{const next=new Map(previous);if(error||loading)next.set(key,{error,loading});else next.delete(key);return next})},[]);
 const guard = useReloadGuard();
 const latest = useRef({canRefresh, blocked: guard.blocked}); latest.current = {canRefresh, blocked: guard.blocked};
 const readers = useRef(new Set<Reload>());
 const running = useRef<Promise<void> | null>(null), deferred = useRef(false);
 const started=useRef(false);
 const away = useRef<number | null>(document.visibilityState==='hidden'?Date.now():null);
 const register = useCallback((reload: Reload) => {readers.current.add(reload); return () => {readers.current.delete(reload)}}, []);
 const refresh = useCallback((afterWrite = true): Promise<void> => {
  if (running.current) return afterWrite&&started.current ? running.current.then(()=>refresh()) : running.current;
  const epoch = getSessionEpoch();
  const request = Promise.resolve().then(async () => {
   if (epoch !== getSessionEpoch()) return;
   if (getPendingMutations() || latest.current.blocked() || latest.current.canRefresh?.() === false) {deferred.current = true; return}
   deferred.current = false; started.current=true;
   const batch=Symbol();
   await Promise.allSettled([...readers.current].map(reload => reload(batch)));
  }).finally(() => {if (running.current === request) {running.current = null;started.current=false;}});
  running.current = request;
  return request;
 }, []);
 useEffect(()=>{if(deferred.current&&!guard.blocked()&&canRefresh?.()!==false)void refresh()});
 const previousRevision = useRef(revision);
 useEffect(() => {if (previousRevision.current !== revision) {previousRevision.current = revision; void refresh()}}, [revision, refresh]);
 useEffect(() => {
  const leave = () => {away.current ??= Date.now()};
  const back = () => {
   if (document.visibilityState === 'hidden') return;
   const since = away.current; away.current = null;
   if (since !== null && Date.now() - since >= DETAIL_RETURN_REFRESH_MS) void refresh(false);
  };
  const visibility = () => {if (document.visibilityState === 'hidden') leave(); else back()};
  const resume = () => {if (deferred.current) void refresh()};
  document.addEventListener('visibilitychange', visibility);
  window.addEventListener('blur', leave); window.addEventListener('focus', back);
  window.addEventListener('yx:mutation-state', resume);
  document.addEventListener('focusout', resume); document.addEventListener('reset', resume);
  return () => {
   document.removeEventListener('visibilitychange', visibility);
   window.removeEventListener('blur', leave); window.removeEventListener('focus', back);
   window.removeEventListener('yx:mutation-state', resume);
   document.removeEventListener('focusout', resume); document.removeEventListener('reset', resume);
  };
 }, [refresh]);
 const value = useRef<Coordinator>({register, refresh, report});
 return createElement(DetailRefresh.Provider, {value: value.current}, createElement(Fragment, null, [...statuses.values()].some(s=>s.loading)&&createElement('p',{role:'status'},'正在更新案件資料…'), [...statuses.values()].filter(s=>s.error).slice(0,1).map((s,i)=>createElement('div',{role:'alert',key:i},`工程進度更新失敗，顯示上次資料：${s.error}`,createElement('button',{onClick:()=>void refresh()},'重試工程進度'))), children));
}

export function useDetailRefresh(reload: Reload, enabled = true, error = '', loading = false) {
 const coordinator = useContext(DetailRefresh);
 const statusKey=useRef(Symbol());
 useEffect(()=>{if(enabled)coordinator?.report(statusKey.current,error,loading);return()=>coordinator?.report(statusKey.current,'',false)},[coordinator,enabled,error,loading]);
 useEffect(() => enabled ? coordinator?.register(reload) : undefined, [coordinator, reload, enabled]);
 return coordinator?.refresh;
}
