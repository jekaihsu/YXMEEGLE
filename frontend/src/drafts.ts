import {useState,type Dispatch,type SetStateAction} from 'react';
import type {Session,Workspace} from './types';

const PREFIX='yx:draft:v1:';
export function draftKey(s:Session,w:Workspace,scope:string){
 return `${PREFIX}${s.user?.id}:${w.workspace_id||s.workspace_id||`${s.mode}:${w.environment||s.environment}`}:${scope}`;
}
export function clearDrafts(){
 try{Object.keys(sessionStorage).filter(k=>k.startsWith(PREFIX)).forEach(k=>sessionStorage.removeItem(k))}catch{/* Storage can be disabled. */}
}
export function useDraft<T>(key:string,initial:T):[T,Dispatch<SetStateAction<T>>]{
 const[value,setValue]=useState<T>(()=>{try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved&&Date.now()-saved.at<24*3600*1000)return saved.value}catch{}return initial});
 const update:Dispatch<SetStateAction<T>>=next=>setValue(previous=>{
  const result=typeof next==='function'?(next as (p:T)=>T)(previous):next;
  try{sessionStorage.setItem(key,JSON.stringify({value:result,at:Date.now()}))}catch{}
  return result;
 });
 return [value,update];
}
