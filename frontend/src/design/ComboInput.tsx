import {useId,useRef,useState} from 'react';
import {PickerPopover} from './PickerPopover';
export function ComboInput({label,value,options,onChange,disabled=false}:{label:string;value:string;options?:string[];onChange:(value:string)=>void;disabled?:boolean}){
 const root=useRef<HTMLDivElement>(null),input=useRef<HTMLInputElement>(null),id=useId();
 const [open,setOpen]=useState(false),[active,setActive]=useState(0);
 const matches=options?.filter(option=>option.toLocaleLowerCase().includes(value.toLocaleLowerCase()))||[];
 const pick=(index:number)=>{const option=matches[index];if(option){onChange(option);setOpen(false);input.current?.focus()}};
 return <div ref={root} className="ds-combo"><input ref={input} role="combobox" aria-label={label} aria-controls={id} aria-expanded={open} aria-autocomplete="list" aria-activedescendant={open&&matches[active]?`${id}-${active}`:undefined} disabled={disabled} value={value} onFocus={()=>setOpen(true)} onChange={e=>{onChange(e.target.value);setOpen(true);setActive(0)}} onKeyDown={e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setOpen(true);setActive(index=>Math.max(0,Math.min(matches.length-1,index+(e.key==='ArrowDown'?1:-1))))}else if(e.key==='Enter'&&open){e.preventDefault();pick(active)}else if(e.key==='Tab')setOpen(false)}}/>
 {open&&!disabled&&<PickerPopover anchor={root} onClose={()=>setOpen(false)}><ul id={id} role="listbox" aria-label={label}>{matches.map((option,index)=><li id={`${id}-${index}`} key={option} role="option" aria-selected={value===option} data-active={active===index} onMouseDown={e=>e.preventDefault()} onClick={()=>pick(index)}>{option}</li>)}</ul>{!matches.length&&<p role="status">{options?'無符合建議，可直接輸入組別':'組別載入中，可直接輸入'}</p>}</PickerPopover>}
 </div>;
}
