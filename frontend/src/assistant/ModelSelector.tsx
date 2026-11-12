// Ported from assistant-ui model-selector.aui and model-selector (MIT). See elements/LICENSE.assistant-ui.
import {useEffect,useId,useRef,useState} from 'react';
import {useAui,useAuiState} from '@assistant-ui/react';
import {Check,ChevronDown} from 'lucide-react';
import type {ModelId} from './runtime';
export type ModelCatalog={default:ModelId;models:{id:ModelId;label:string;available:boolean}[]};
export function rememberedModel(catalog:ModelCatalog):ModelId {
 let saved:string|null=null;
 try{saved=localStorage.getItem('yx:ai-model')}catch{}
 return catalog.models.find(m=>m.id===saved&&m.available)?.id||catalog.models.find(m=>m.id===catalog.default&&m.available)?.id||catalog.models.find(m=>m.available)?.id||catalog.default;
}
export function ModelSelector({catalog}:{catalog:ModelCatalog}){
 const [value,setValue]=useState(()=>rememberedModel(catalog)),[open,setOpen]=useState(false);
 const api=useAui(),running=useAuiState(s=>s.thread.isRunning),id=useId();
 const root=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null);
 useEffect(()=>api.modelContext.register({getModelContext:()=>({config:{modelName:value}})}),[api,value]);
 useEffect(()=>{
  if(!open)return;
  root.current?.querySelector<HTMLButtonElement>('[role=option]:not(:disabled)')?.focus();
  const dismiss=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setOpen(false)};
  document.addEventListener('pointerdown',dismiss);return()=>document.removeEventListener('pointerdown',dismiss);
 },[open]);
 const close=()=>{setOpen(false);trigger.current?.focus()};
 return <div ref={root} data-slot="model-selector" className="assistant-model" onKeyDown={event=>{
  if(event.key==='Escape'){event.preventDefault();close()}
  if(event.key==='Tab')setOpen(false);
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){
   event.preventDefault();if(!open){setOpen(true);return}
   const options=Array.from(root.current!.querySelectorAll<HTMLButtonElement>('[role=option]:not(:disabled)'));
   options[(options.indexOf(document.activeElement as HTMLButtonElement)+(event.key==='ArrowDown'?1:options.length-1))%options.length]?.focus();
  }
 }}>
  <button type="button" className="ds-button" data-variant="plain" ref={trigger} data-slot="model-selector-trigger" role="combobox" aria-label="選擇 AI 助理" aria-haspopup="listbox" aria-expanded={open} aria-controls={open?id:undefined} disabled={running} onClick={()=>setOpen(v=>!v)}><span data-slot="model-selector-value">{value==='claude'?'Claude':'GPT'}</span><ChevronDown size={14}/></button>
  {open&&<div id={id} data-slot="model-selector-content" className="assistant-model-menu" role="listbox" aria-label="AI 助理模型">{(['claude','gpt'] as const).map(model=>{
   const available=catalog.models.some(m=>m.id===model&&m.available);
   return <button type="button" key={model} data-slot="model-selector-item" role="option" aria-selected={model===value} disabled={!available} aria-describedby={!available?`${id}-${model}`:undefined} onClick={()=>{setValue(model);try{localStorage.setItem('yx:ai-model',model)}catch{}close()}}><span>{model==='claude'?'Claude':'GPT'}{!available&&<small id={`${id}-${model}`}>尚未設定</small>}</span>{model===value&&<Check size={16}/>}</button>;
  })}</div>}
 </div>;
}
