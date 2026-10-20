import {createPortal} from 'react-dom';
import type {ReactNode} from 'react';
import {ChevronRight,X} from 'lucide-react';
import {useDialogFocus} from './useDialogFocus';
import './TaskDrawer.css';

export type DrawerFact={label:string;value:ReactNode};

export function TaskDrawer({kind,label,trail,eyebrow,title,status,tools,tabs,footer,onClose,children}:{kind:'legacy'|'sop'|'lark';label:string;trail:string[];eyebrow?:ReactNode;title:string;status?:ReactNode;tools?:ReactNode;tabs?:ReactNode;footer?:ReactNode;onClose:()=>void;children:ReactNode}){
 const ref=useDialogFocus(onClose);
 return createPortal(<div className="task-drawer-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}>
  <aside ref={ref} tabIndex={-1} className="task-drawer" data-kind={kind} role="dialog" aria-modal="true" aria-label={label}>
   <header className="task-drawer-bar">
    <nav className="task-drawer-trail" aria-label="任務位置">{trail.map((part,i)=><span key={i}>{i>0 && <ChevronRight size={13} aria-hidden="true"/>}{part}</span>)}</nav>
    <div className="task-drawer-tools">{tools}<button type="button" className="icon-button" onClick={onClose} aria-label="關閉"><X size={18}/></button></div>
   </header>
   <div className="task-drawer-head">
    {eyebrow && <span className="task-drawer-eyebrow">{eyebrow}</span>}
    <h2>{title}</h2>
    {status && <div className="task-drawer-status">{status}</div>}
    {tabs}
   </div>
   <div className="task-drawer-body">{children}</div>
   {footer && <footer className="task-drawer-footer">{footer}</footer>}
  </aside>
 </div>,document.body);
}

export function DrawerFacts({facts}:{facts:DrawerFact[]}){
 return <dl className="task-drawer-facts">{facts.map(f=><div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl>;
}
