import {useCallback,useEffect,useRef} from 'react';
import type {Route} from './types';

export type DraftScope={projectId:string;nodeId:string;dirty:boolean};
export function useDraftNavigationGuard(){
 const current=useRef<DraftScope|null>(null);
 const registerDrafts=useCallback((scope:DraftScope|null)=>{current.current=scope},[]);
 const allowNavigation=useCallback((route:Route)=>{
  const scope=current.current;
  if(!scope?.dirty)return true;
  if(route.view==='project'&&route.project===scope.projectId&&route.node===scope.nodeId)return true;
  const leave=window.confirm('有尚未儲存的任務成果或跳過申請文字。離開此節點會捨棄這些文字，確定離開？');
  if(leave)current.current=null;
  return leave;
 },[]);
 useEffect(()=>{const prevent=(event:BeforeUnloadEvent)=>{if(!current.current?.dirty)return;event.preventDefault();event.returnValue=''};window.addEventListener('beforeunload',prevent);return()=>window.removeEventListener('beforeunload',prevent)},[]);
 return {registerDrafts,allowNavigation};
}
