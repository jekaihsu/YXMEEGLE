import {useState,type Dispatch,type SetStateAction} from 'react';
import type {Session,Workspace} from './types';

const PREFIX='yx:draft:v1:';
export function draftKey(s:Session,w:Workspace,scope:string){
 return `${PREFIX}${s.user?.id}:${w.workspace_id||s.workspace_id||`${s.mode}:${w.environment||s.environment}`}:${scope}`;
}
export function clearDrafts(){
 try{Object.keys(sessionStorage).filter(k=>k.startsWith(PREFIX)).forEach(k=>sessionStorage.removeItem(k))}catch{/* Storage can be disabled. */}
}
function readDraft<T>(key:string,initial:T):T{
 try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved&&Date.now()-saved.at<24*3600*1000)return saved.value}catch{}
 return initial;
}
// State is tagged with the key it was loaded for, so a key change reloads that scope and never writes old values into it.
export function useDraft<T>(key:string,initial:T):[T,Dispatch<SetStateAction<T>>]{
 const[state,setState]=useState<{key:string;value:T}>(()=>({key,value:readDraft(key,initial)}));
 const current=state.key===key?state:{key,value:readDraft(key,initial)};
 if(state.key!==key)setState(current);
 const update:Dispatch<SetStateAction<T>>=next=>setState(previous=>{
  const base=previous.key===key?previous.value:readDraft(key,initial);
  const result=typeof next==='function'?(next as (p:T)=>T)(base):next;
  try{sessionStorage.setItem(key,JSON.stringify({value:result,at:Date.now()}))}catch{}
  return {key,value:result};
 });
 return [current.value,update];
}
