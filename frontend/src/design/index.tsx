import {createContext,useContext,useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import type {ButtonHTMLAttributes,CSSProperties,KeyboardEvent,ReactNode} from 'react';
import {Check,ChevronDown} from 'lucide-react';
import {useDialogFocus} from '../useDialogFocus';
import './primitives.css';
import {PickerPopover} from './PickerPopover';
export {Select} from './Select';

export {ThemeProvider,useAppearance} from './appearance';

/** Small uppercase accent label above a big semibold title. */
export function Eyebrow({children}:{children:ReactNode}){return <p className="ds-eyebrow">{children}</p>}

export function Page({title,eyebrow,subtitle,actions,children}:{title:string;eyebrow?:string;subtitle?:string;actions?:ReactNode;children:ReactNode}){
 return <div className="ds-page"><header className="ds-page-head"><div>{eyebrow&&<Eyebrow>{eyebrow}</Eyebrow>}<h1>{title}</h1>{subtitle&&<p>{subtitle}</p>}</div>{actions&&<div className="ds-actions">{actions}</div>}</header>{children}</div>;
}

/** Inset grouped list: rows separated by hairlines, no card border. */
export function Section({title,footer,children}:{title?:string;footer?:string;children:ReactNode}){
 return <section className="ds-section">{title&&<h2>{title}</h2>}<div className="ds-group glass--flat">{children}</div>{footer&&<p className="ds-footer">{footer}</p>}</section>;
}

export function Row({label,detail,value,icon,onClick,href}:{label:ReactNode;detail?:ReactNode;value?:ReactNode;icon?:ReactNode;onClick?:()=>void;href?:string}){
 const body=<>{icon&&<span className="ds-row-icon" aria-hidden="true">{icon}</span>}<span className="ds-row-main"><span>{label}</span>{detail&&<small>{detail}</small>}</span>{value!=null&&<span className="ds-row-value">{value}</span>}</>;
 if(href)return <a className="ds-row" href={href}>{body}</a>;
 if(onClick)return <button type="button" className="ds-row" onClick={onClick}>{body}</button>;
 return <div className="ds-row">{body}</div>;
}

export function Stat({label,value,tone}:{label:string;value:ReactNode;tone?:'warning'|'critical'|'positive'}){
 return <div className="ds-stat" data-tone={tone}><strong>{value}</strong><span>{label}</span></div>;
}

/** Status is always text (plus optional icon), never colour alone. */
export function Badge({children,tone,icon}:{children:ReactNode;tone?:'positive'|'warning'|'critical'|'accent';icon?:ReactNode}){
 return <span className="ds-badge" data-tone={tone}>{icon}{children}</span>;
}

// Project detail opts in; other routes retain their existing button layout.
export const DisabledActionReasons=createContext(false);
export function DisabledAction({disabled,reason,children}:{disabled?:boolean;reason?:string;children:(descriptionId?:string)=>ReactNode}){
 const scoped=useContext(DisabledActionReasons);const id=useId();
 if(!scoped||!disabled)return <>{children()}</>;
 return <span className="disabled-action">{children(id)}<span id={id} className="disabled-action-reason" title={reason||'目前無法操作'}>{reason||'目前無法操作'}</span></span>;
}
export function Button({variant='secondary',disabledReason,...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'primary'|'secondary'|'plain'|'destructive';disabledReason?:string}){
 return <DisabledAction disabled={variant==='primary'&&props.disabled} reason={disabledReason}>{id=><button type="button" {...props} aria-describedby={[props['aria-describedby'],id].filter(Boolean).join(' ')||undefined} className={`ds-button ${props.className||''}`} data-variant={variant}/>}</DisabledAction>;
}

export function Segmented<T extends string>({label,options,value,onChange}:{label:string;options:[T,ReactNode][];value:T;onChange:(v:T)=>void}){
 return <div className="ds-segmented glass--flat" role="radiogroup" aria-label={label}>{options.map(([k,text])=><button key={k} type="button" role="radio" aria-checked={value===k} onClick={()=>onChange(k)}>{text}</button>)}</div>;
}

/** Modal sheet with focus trap, Escape and focus return. */
export function Sheet({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}){
 const ref=useDialogFocus(onClose);
 return <div className="ds-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><section ref={ref} tabIndex={-1} className="ds-sheet glass" role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><Button variant="plain" onClick={onClose} aria-label="關閉">✕</Button></header>{children}</section></div>;
}

/** Placeholder shaped like the content it stands in for; reuses the .skeleton classes viewData consumers already render. */
export function Skeleton({lines=1,width,height}:{lines?:number;width?:CSSProperties['width'];height?:CSSProperties['height']}){
 return <div aria-hidden="true">{Array.from({length:lines},(_,i)=><div key={i} className="skeleton skeleton-row" style={{width,height}}/>)}</div>;
}

export function Progress({value,max=100,label}:{value:number;max?:number;label:string}){
 return <progress className="ds-progress" value={value} max={max} aria-label={label}/>;
}

/** Dropdown for toolbar filters. Draws its own list instead of the native <select> popup,
 *  which some embedded browsers (e.g. app preview panes) never display. Keyboard: arrows, Home/End, Enter, Escape. */
export function Picker<T extends string>({label,options,value,onChange,className='',disabled=false,disabledOptions=[],searchable=false}:{label:string;options:[T,string][];value:T;onChange:(v:T)=>void;className?:string;disabled?:boolean;disabledOptions?:T[];searchable?:boolean}){
 const[open,setOpen]=useState(false);
 const[active,setActive]=useState(0);
 const[query,setQuery]=useState('');
 const visible=options.map((option,index)=>({option,index})).filter(({option})=>!query||option[1].toLocaleLowerCase().includes(query.toLocaleLowerCase()));
 const root=useRef<HTMLDivElement>(null);
 const button=useRef<HTMLButtonElement>(null);
 const list=useRef<HTMLUListElement>(null);
 const id=useId();
 const current=options.find(([k])=>k===value)?.[1]??options[0]?.[1]??'';
 useEffect(()=>{if(!open)return;
  const away=(e:PointerEvent)=>{if(!root.current?.contains(e.target as Node))setOpen(false)};
  document.addEventListener('pointerdown',away);return()=>document.removeEventListener('pointerdown',away)},[open]);
 useEffect(()=>{if(open)list.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({block:'nearest'})},[open,active]);
 useLayoutEffect(()=>{if(open)list.current?.focus()},[open]);
 const show=()=>{if(disabled)return;setQuery('');setActive(Math.max(0,options.findIndex(([k])=>k===value)));setOpen(true)};
 const pick=(i:number)=>{const o=options[i];if(!o||disabledOptions.includes(o[0]))return;onChange(o[0]);setOpen(false);button.current?.focus()};
 const onButtonKey=(e:KeyboardEvent)=>{if(['ArrowDown','ArrowUp','Enter',' '].includes(e.key)){e.preventDefault();show()}};
 const onListKey=(e:KeyboardEvent)=>{
  const available=visible.filter(({option})=>!disabledOptions.includes(option[0])).map(({index})=>index);
  const last=available.at(-1)??0;
  const move=(delta:number)=>setActive(i=>available[Math.max(0,Math.min(available.length-1,available.indexOf(i)+delta))]??0);
  if(e.key==='ArrowDown'){e.preventDefault();move(1)}
  else if(e.key==='ArrowUp'){e.preventDefault();move(-1)}
  else if(e.key==='Home'){e.preventDefault();setActive(available[0]??0)}
  else if(e.key==='End'){e.preventDefault();setActive(last)}
  else if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(active)}
  else if(e.key==='Escape'||e.key==='Tab'){if(e.key==='Escape')e.preventDefault();setOpen(false);if(e.key==='Escape')button.current?.focus()}};
 return <div ref={root} className={`ds-picker ${open?'open':''} ${className}`}>
  <button ref={button} disabled={disabled} type="button" aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-list`} aria-label={`${label}：${current}`} onClick={()=>open?setOpen(false):show()} onKeyDown={onButtonKey}>
   <span>{current}</span><ChevronDown size={14} aria-hidden="true"/>
  </button>
  {open&&!disabled&&<PickerPopover anchor={root} onClose={()=>setOpen(false)}>{searchable&&<input className="ds-picker-search" aria-label={`搜尋${label}`} placeholder="輸入關鍵字搜尋" value={query} onChange={e=>{setQuery(e.target.value);setActive(0)}} onKeyDown={e=>{if(e.key==='ArrowDown'){e.preventDefault();setActive(visible[0]?.index??0);list.current?.focus()}else if(e.key==='Enter'){e.preventDefault();const first=visible.find(({option})=>!disabledOptions.includes(option[0]));if(first)pick(first.index)}}}/>}<ul ref={list} id={`${id}-list`} role="listbox" tabIndex={-1} aria-label={label} aria-activedescendant={`${id}-${active}`} onKeyDown={onListKey}>
   {visible.map(({option:[k,text],index:i})=><li key={k} id={`${id}-${i}`} data-index={i} role="option" aria-selected={k===value} aria-disabled={disabledOptions.includes(k)||undefined} className={i===active?'active':''} onMouseEnter={()=>setActive(i)} onMouseDown={e=>e.preventDefault()} onClick={()=>pick(i)}>
    <span>{text}</span>{k===value&&<Check size={14} aria-hidden="true"/>}
   </li>)}
  </ul>{!visible.length&&<p className="ds-picker-empty" role="status">沒有符合的選項</p>}</PickerPopover>}
 </div>;
}
