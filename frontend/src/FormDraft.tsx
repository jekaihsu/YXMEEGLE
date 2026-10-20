import {Button} from './design';
import {createContext,useContext,useLayoutEffect,useRef,useState,type FormEvent,type ReactNode} from 'react';

export const DraftNamespace=createContext('');
type Saved=Record<string,string[]>;
type Concurrency=Record<string,string>;
type SavedDraft={value:Saved;at:number;concurrency?:Concurrency;initial?:Saved};
type DraftFormProps={title:string;draftId:string;onSubmit:(values:Record<string,FormDataEntryValue>,e:FormEvent<HTMLFormElement>)=>void|Promise<unknown>;children:ReactNode;busy:boolean;concurrency?:Concurrency};
function fields(form:HTMLFormElement){
 return Array.from(form.elements).filter((element):element is HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement=>(element instanceof HTMLInputElement||element instanceof HTMLTextAreaElement||element instanceof HTMLSelectElement)&&!!element.name&&!['password','file','hidden'].includes(element.type));
}
function snapshot(form:HTMLFormElement):Saved{
 const values:Saved={};
 for(const element of fields(form)){
  values[element.name]??=[];
  if(element instanceof HTMLInputElement&&['checkbox','radio'].includes(element.type)){if(element.checked)values[element.name].push(element.value)}
  else values[element.name].push(element.value);
 }
 return values;
}
function apply(form:HTMLFormElement,values:Saved){
 for(const element of fields(form)){
  if(!(element.name in values))continue;
  if(element instanceof HTMLInputElement&&['checkbox','radio'].includes(element.type))Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'checked')?.set?.call(element,values[element.name].includes(element.value));
  else{
   const prototype=element instanceof HTMLInputElement?HTMLInputElement.prototype:element instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLSelectElement.prototype;
   Object.getOwnPropertyDescriptor(prototype,'value')?.set?.call(element,values[element.name][0]||'');
  }
  element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));
 }
}
const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
export function DraftForm(props:DraftFormProps){
 const {title,draftId}=props;const[savedTick,setSavedTick]=useState(0);
 const namespace=useContext(DraftNamespace);const params=new URLSearchParams(location.hash.slice(1));
 const key=`yx:draft:v2:${namespace}:form:${params.get('project')||''}:${params.get('node')||''}:${encodeURIComponent(title)}:${encodeURIComponent(draftId)}`;
 const activeKey=useRef(key);activeKey.current=key;
 // Field defaults and their revision must advance together.
 return <ScopedDraftForm key={`${key}:${savedTick}`} {...props} storageKey={key} namespace={namespace} onSaved={()=>{if(activeKey.current===key)setSavedTick(t=>t+1)}}/>;
}
function ScopedDraftForm({title,draftId,onSubmit,children,busy,concurrency,storageKey:key,namespace,onSaved}:DraftFormProps&{storageKey:string;namespace:string;onSaved:()=>void}){
 const ref=useRef<HTMLFormElement>(null);
 const[stored,setStored]=useState<SavedDraft|null>(()=>{try{const entry=JSON.parse(sessionStorage.getItem(key)||'null');return entry&&Date.now()-entry.at<86400000?entry:null}catch{return null}});
 const[notice,setNotice]=useState(stored?'有未送出的暫存文字，可核對後恢復。':'');
 const[conflict,setConflict]=useState(false);const[fieldTick,setFieldTick]=useState(0);
 const baseline=useRef(concurrency);const initial=useRef<Saved>({});const pending=useRef<SavedDraft|null>(null);
 const persist=(draft:SavedDraft)=>{if(!namespace||!draftId)return;try{sessionStorage.setItem(key,JSON.stringify(draft));setStored(draft)}catch{setNotice('瀏覽器無法暫存，請勿關閉此頁。')}};
 useLayoutEffect(()=>{
  if(!ref.current)return;
  const fresh=snapshot(ref.current);initial.current=fresh;
  if(!pending.current)return;
  const draft=pending.current;pending.current=null;
  const edits=Object.fromEntries(Object.entries(draft.value).filter(([name,value])=>!draft.initial||!same(value,draft.initial[name])));
  const changed=Object.keys(fresh).filter(name=>draft.initial&&!same(fresh[name],draft.initial[name]));
  apply(ref.current,edits);
  persist({value:snapshot(ref.current),initial:fresh,concurrency:baseline.current,at:Date.now()});
  const controls=fields(ref.current);
  const titles=changed.map(name=>{
   const element=controls.find(field=>field.name===name);const label=element?.closest('label');
   return element?.closest('fieldset')?.querySelector('legend')?.textContent||label?.firstChild?.textContent||label?.textContent||name;
  });
  setNotice(titles.length?`已更新：${titles.join('、')}`:'已套用，請核對後儲存。');
 },[fieldTick]);
 const capture=()=>{if(ref.current)persist({value:snapshot(ref.current),initial:initial.current,at:Date.now(),concurrency:baseline.current})};
 const restore=()=>{
  if(!ref.current||!stored)return;
  baseline.current=concurrency?stored.concurrency||Object.fromEntries(Object.keys(concurrency).map(k=>[k,'unknown'])):undefined;
  initial.current=stored.initial||{};apply(ref.current,stored.value);
  setConflict(!!concurrency&&!same(baseline.current,concurrency));
  setNotice('已恢復文字，請核對後儲存。');
 };
 const rebase=()=>{
  if(!stored)return;
  pending.current=stored;baseline.current=concurrency;setConflict(false);setFieldTick(t=>t+1);
 };
 return <details className="ops-form"><summary>{title}</summary>{stored&&<div className="draft-recovery"><p>{notice||'文字已暫存於本分頁，尚未送出。'}</p>{conflict?<button className="button" type="button" disabled={busy} onClick={rebase}>以最新資料重新套用</button>:<button className="button" type="button" onClick={restore}>恢復暫存文字</button>}<button className="text-button" type="button" onClick={()=>{sessionStorage.removeItem(key);setStored(null);setNotice('');setConflict(false);baseline.current=concurrency;setFieldTick(t=>t+1)}}>捨棄暫存</button></div>}<form key={fieldTick} ref={ref} onChange={capture} onSubmit={e=>{
  e.preventDefault();if(conflict)return;capture();const submittedKey=key;
  const values=Object.fromEntries(new FormData(e.currentTarget).entries());if(baseline.current)values._entity_versions=JSON.stringify(baseline.current);
  const result=onSubmit(values,e);
  if(result&&typeof (result as Promise<unknown>).then==='function')void Promise.resolve(result).then(saved=>{
   if(!saved)return;try{sessionStorage.removeItem(submittedKey)}catch{}onSaved();
  }).catch(error=>{if(error&&typeof error==='object'&&'status' in error&&error.status===409)setConflict(true)});
 }}><div className="ops-fields">{children}</div><Button variant="primary" className="button primary" disabled={busy||conflict} type="submit">儲存</Button></form></details>;
}
