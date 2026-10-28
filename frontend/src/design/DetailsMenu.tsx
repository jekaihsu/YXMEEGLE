import {useRef,useState,type ReactNode} from 'react';
import {PickerPopover} from './PickerPopover';
export function DetailsMenu({label,ariaLabel,className,children}:{label:ReactNode;ariaLabel?:string;className:string;children:ReactNode}){
 const root=useRef<HTMLDetailsElement>(null),[open,setOpen]=useState(false);
 const close=()=>{if(root.current)root.current.open=false;setOpen(false)};
 return <details ref={root} className={className} onToggle={e=>setOpen(e.currentTarget.open)}><summary aria-label={ariaLabel}>{label}</summary>{open&&<PickerPopover anchor={root} onClose={close}>{children}</PickerPopover>}</details>;
}
