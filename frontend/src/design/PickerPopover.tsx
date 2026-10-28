import {useLayoutEffect,useRef,type ReactNode, type RefObject} from 'react';
import './picker.css';
export function PickerPopover({anchor,children,className='',onClose}:{anchor:RefObject<HTMLElement>;children:ReactNode;className?:string;onClose:()=>void}){
 const popup=useRef<HTMLDivElement>(null),close=useRef(onClose);close.current=onClose;
 useLayoutEffect(()=>{
  const panel=popup.current,trigger=anchor.current;if(!panel||!trigger)return;
  panel.setAttribute('popover','manual');panel.showPopover?.();
  const position=()=>{
   const r=trigger.getBoundingClientRect(),gap=6,edge=8;
   const width=Math.min(Math.max(r.width,260),window.innerWidth-edge*2);
   const below=window.innerHeight-r.bottom-gap-edge,above=r.top-gap-edge;
   const height=Math.max(80,Math.min(360,Math.max(below,above)));
   panel.style.width=`${width}px`;panel.style.maxHeight=`${height}px`;
   panel.style.left=`${Math.max(edge,Math.min(r.right-width,window.innerWidth-width-edge))}px`;
   panel.style.top=`${below>=Math.min(panel.scrollHeight,360)||below>=above?r.bottom+gap:Math.max(edge,r.top-Math.min(panel.scrollHeight,height)-gap)}px`;
  };
  position();const observer=typeof ResizeObserver==='undefined'?undefined:new ResizeObserver(position);observer?.observe(panel);observer?.observe(trigger);
  const away=(e:PointerEvent)=>{if(e.target instanceof Node&&!panel.contains(e.target)&&!trigger.contains(e.target))close.current()};
  document.addEventListener('pointerdown',away,true);window.addEventListener('resize',position);window.addEventListener('scroll',position,true);
  return()=>{observer?.disconnect();document.removeEventListener('pointerdown',away,true);window.removeEventListener('resize',position);window.removeEventListener('scroll',position,true);panel.hidePopover?.()};
 },[anchor]);
 return <div ref={popup} style={{position:'fixed',margin:0}} data-local-escape className={`ds-picker-popup ${className}`} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();onClose();anchor.current?.querySelector<HTMLElement>('summary,button,input')?.focus()}}}>{children}</div>;
}
