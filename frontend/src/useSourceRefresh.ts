import {useCallback,useEffect,useRef} from 'react';
import {refreshSources} from './refreshSources';
import type {LiveDataset} from './types';

export function useSourceRefresh(scope?:string) {
 const current=useRef<AbortController|null>(null);
 useEffect(()=>()=>{current.current?.abort()},[scope]);
 return useCallback(async(dataset:LiveDataset='sources',legacy?:{url:string;body?:string})=>{
  current.current?.abort();
  const controller=new AbortController();
  current.current=controller;
  try{return await refreshSources(dataset,legacy,controller.signal)}
  finally{if(current.current===controller)current.current=null}
 },[scope]);
}
