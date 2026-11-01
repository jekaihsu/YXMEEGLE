import {useRef,useState,type ReactNode} from 'react';
import {PickerPopover} from './PickerPopover';
export function DetailsMenu({label,ariaLabel,className,children}:{label:ReactNode;ariaLabel?:string;className:string;children:ReactNode|((close:()=>void)=>ReactNode)}){
 const root=useRef<HTMLDetailsElement>(null),[open,setOpen]=useState(false);
 const close=()=>{if(root.current)root.current.open=false;setOpen(false)};
 return <details ref={root} className={className} data-local-escape={open||undefined} onKeyDown={e=>{if(open&&e.key==='Escape'){e.preventDefault();close()}}} onToggle={e=>setOpen(e.currentTarget.open)}><summary aria-label={ariaLabel}>{label}</summary>{open&&<PickerPopover anchor={root} onClose={close}>{typeof children==='function'?children(close):children}</PickerPopover>}</details>;
}
