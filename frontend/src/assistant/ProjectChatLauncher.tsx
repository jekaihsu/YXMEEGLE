import {useEffect,useId,useRef,useState,type ComponentType} from 'react';
import {createPortal} from 'react-dom';
import {MessageCircle,X} from 'lucide-react';
import {api} from '../api';
import {Button,DisabledActionReasons} from '../design';
import type {ModelCatalog} from './ModelSelector';
import type {AssistantChatProps} from './AssistantChat';
import './ProjectChatLauncher.css';

type Props={projectId:string;projectCode:string;projectName:string};
type ChatState={status:'idle'|'loading'|'unavailable'|'error'}|{status:'ready';Chat:ComponentType<AssistantChatProps>;catalog:ModelCatalog};
const focusable='button:not(:disabled),textarea:not(:disabled),input:not(:disabled),select:not(:disabled),a[href],[tabindex="0"]';

export function ProjectChatLauncher(props:Props){
 return <ProjectChat key={props.projectId} {...props}/>;
}
function ProjectChat({projectId,projectCode,projectName}:Props){
 const [open,setOpen]=useState(false),[state,setState]=useState<ChatState>({status:'idle'});
 const [mobile,setMobile]=useState(()=>window.matchMedia?.('(max-width: 640px)').matches??false);
 const launcher=useRef<HTMLButtonElement>(null),panel=useRef<HTMLElement>(null),portal=useRef<HTMLDivElement>(null);
 const request=useRef<AbortController>(),wasOpen=useRef(false);
 const id=useId(),label=`${projectCode} ${projectName}`;
 useEffect(()=>()=>request.current?.abort(),[]);
 useEffect(()=>{
  const media=window.matchMedia?.('(max-width: 640px)');
  if(!media)return;
  const change=()=>setMobile(media.matches);media.addEventListener('change',change);
  return()=>media.removeEventListener('change',change);
 },[]);
 const close=()=>setOpen(false);
 const load=async()=>{
  request.current?.abort();const controller=new AbortController();request.current=controller;setState({status:'loading'});
  try{
   const catalog=await api<ModelCatalog>('/api/ai/models',{signal:controller.signal});
   if(controller.signal.aborted)return;
   if(!catalog.models.some(model=>model.available)){setState({status:'unavailable'});return}
   const {AssistantChat}=await import('./AssistantChat');
   if(!controller.signal.aborted)setState({status:'ready',Chat:AssistantChat,catalog});
  }catch{if(!controller.signal.aborted)setState({status:'error'})}
 };
 useEffect(()=>{
  if(!open){if(wasOpen.current)launcher.current?.focus();wasOpen.current=false;return}
  wasOpen.current=true;
  if(!panel.current)return;
  const element=panel.current;
  element.focus();
  const focusComposer=()=>{const input=element.querySelector<HTMLTextAreaElement>('textarea:not(:disabled)');if(input){input.focus();return true}return false};
  const observer=new MutationObserver(()=>{if(focusComposer())observer.disconnect()});
  if(!focusComposer())observer.observe(element,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});
  const keydown=(event:KeyboardEvent)=>{
   if(event.defaultPrevented||event.isComposing||event.keyCode===229)return;
   const target=event.target;
   if(!(target instanceof Node)||(!element.contains(target)&&target!==launcher.current))return;
   if(target instanceof Element&&target.closest('[role=dialog]')!==element&&target!==launcher.current)return;
   if(event.key==='Escape'){event.preventDefault();setOpen(false)}
   if(!mobile||event.key!=='Tab')return;
   const items=Array.from(element.querySelectorAll<HTMLElement>(focusable)).filter(item=>!item.closest('[hidden]'));
   const first=items[0],last=items.at(-1);
   if(!first){event.preventDefault();element.focus();return}
   if(event.shiftKey&&(document.activeElement===first||document.activeElement===element)){event.preventDefault();last?.focus()}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  };
  document.addEventListener('keydown',keydown);
  return()=>{observer.disconnect();document.removeEventListener('keydown',keydown)};
 },[open,mobile]);
 useEffect(()=>{
  if(!open||!mobile)return;
  const siblings=Array.from(document.body.children).filter((item):item is HTMLElement=>item instanceof HTMLElement&&item!==portal.current);
  const inert=siblings.map(item=>item.inert),overflow=document.body.style.overflow;
  siblings.forEach(item=>{item.inert=true});document.body.style.overflow='hidden';
  const contain=(event:FocusEvent)=>{if(event.target instanceof Node&&!panel.current?.contains(event.target))panel.current?.focus()};
  document.addEventListener('focusin',contain);
  return()=>{siblings.forEach((item,index)=>{item.inert=inert[index]});document.body.style.overflow=overflow;document.removeEventListener('focusin',contain)};
 },[open,mobile]);
 return <>
  <button ref={launcher} type="button" className="project-chat-launcher" hidden={state.status==='unavailable'} data-open={open} aria-label="AI 助理，詢問這個案件" aria-expanded={open} aria-controls={id} title="AI 助理，詢問這個案件" onClick={()=>{if(open){close();return}setOpen(true);if(state.status==='idle')void load()}}><MessageCircle size={24} aria-hidden="true"/></button>
  {state.status!=='idle'&&createPortal(<DisabledActionReasons.Provider value={false}><div ref={portal} className="project-chat-portal" hidden={!open}>
   <section ref={panel} id={id} className="project-chat-panel" role="dialog" aria-modal={mobile} aria-labelledby={`${id}-title`} tabIndex={-1}>
    <header className="project-chat-header"><div><p>{projectCode}</p><h2 id={`${id}-title`}>{projectName}</h2></div><Button variant="plain" onClick={close} aria-label="關閉案件 AI 助理"><X size={20} aria-hidden="true"/></Button></header>
    <div className="project-chat-content">
     {state.status==='ready'?<state.Chat catalog={state.catalog} projectId={projectId} projectLabel={label} compact/>:state.status==='loading'?<p role="status">正在載入 AI 助理…</p>:state.status==='unavailable'?<p role="status">AI 助理尚未開放，請稍後再試。</p>:<p role="alert">無法載入 AI 助理。<Button onClick={()=>void load()}>重試</Button></p>}
    </div>
   </section>
  </div></DisabledActionReasons.Provider>,document.body)}
 </>;
}
