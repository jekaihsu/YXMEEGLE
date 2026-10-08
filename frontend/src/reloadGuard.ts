import {useCallback,useEffect,useRef,useState} from 'react';
import {getPendingMutations,getSessionEpoch} from './api';

type Editable=HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement;
const editable=(target:EventTarget|null):target is Editable=>target instanceof window.HTMLElement&&!target.closest('[data-reload-safe]')&&target.matches('input:not([type=hidden]):not([type=button]):not([type=submit]),textarea,select');
export function useReloadGuard(){
 const dirty=useRef(new Map<Editable,string>());
 const baseline=useRef(new WeakMap<Editable,string>());
 const [,update]=useState(0);
 const epoch=getSessionEpoch();
 useEffect(()=>{dirty.current.clear();baseline.current=new WeakMap()},[epoch]);
 const blocked=useCallback(()=>{
  for(const [element,initial] of dirty.current)if(!element.isConnected||element.value===initial)dirty.current.delete(element);
  return getPendingMutations()>0||dirty.current.size>0||!!document.querySelector('details.ops-form[open] form,[role=dialog] input,[role=dialog] textarea,[contenteditable=true]')||editable(document.activeElement);
 },[]);
 useEffect(()=>{
  const notify=()=>update(value=>value+1);
  const changed=(event:Event)=>{if(editable(event.target)){
   const element=event.target;
   if(event.type==='focusin'){if(!baseline.current.has(element))baseline.current.set(element,element.value)}
   else if(event.type==='input'||event.type==='change')dirty.current.set(element,baseline.current.get(element)??(element instanceof window.HTMLSelectElement?'':element.defaultValue));
  }
   // Capture dirty values immediately, but let React process controlled input
   // changes before a parent render can restore the previous value.
   if(event.type!=='input'&&event.type!=='change')notify();
  };
  for(const name of ['input','change','focusin','focusout','toggle','reset'])document.addEventListener(name,changed,true);
  for(const name of ['input','change'])document.addEventListener(name,notify);
  window.addEventListener('yx:mutation-state',changed);
  return()=>{for(const name of ['input','change','focusin','focusout','toggle','reset'])document.removeEventListener(name,changed,true);for(const name of ['input','change'])document.removeEventListener(name,notify);window.removeEventListener('yx:mutation-state',changed)};
 },[]);
 return {blocked,active:blocked()};
}
