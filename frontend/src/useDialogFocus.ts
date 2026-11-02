import {useEffect, useRef} from 'react';

/** Keep keyboard navigation inside the foremost modal and return to its trigger. */
export function useDialogFocus(onClose:()=>void, enabled=true){
 const ref=useRef<HTMLElement>(null);
 // Render precedes descendant autoFocus during commit. Also recapture on enable.
 const returnTarget=useRef<HTMLElement|null>(null);
 const wasEnabled=useRef(false);
 if(enabled&&!wasEnabled.current&&typeof document!=='undefined')returnTarget.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
 wasEnabled.current=enabled;
 const close=useRef(onClose); close.current=onClose;
 useEffect(()=>{
  const panel=ref.current;if(!enabled||!panel)return;
  const trigger=returnTarget.current;
  const previousOverflow=document.body.style.overflow;
  document.body.style.overflow='hidden';
  const controls=()=>Array.from(panel.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex="0"]')).filter(e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden');
  const foremost=()=>Array.from(document.querySelectorAll('[role="dialog"]')).at(-1)===panel;
  (controls()[0]||panel).focus();
  const key=(e:KeyboardEvent)=>{
   if(!foremost())return;
   if(e.key==='Escape'){if(e.target instanceof Element&&e.target.closest('[data-local-escape]'))return;e.preventDefault();e.stopPropagation();close.current();return;}
   if(e.key!=='Tab')return;
   const items=controls(),first=items[0],last=items.at(-1);
   if(!first){e.preventDefault();panel.focus();return;}
   if(e.shiftKey&&(document.activeElement===first||!panel.contains(document.activeElement))){e.preventDefault();last?.focus();}
   else if(!e.shiftKey&&(document.activeElement===last||!panel.contains(document.activeElement))){e.preventDefault();first.focus();}
  };
  const focus=(e:FocusEvent)=>{if(foremost()&&!panel.contains(e.target as globalThis.Node))(controls()[0]||panel).focus();};
  document.addEventListener('keydown',key,true);document.addEventListener('focusin',focus);
  return()=>{document.removeEventListener('keydown',key,true);document.removeEventListener('focusin',focus);document.body.style.overflow=previousOverflow;if(trigger?.isConnected)trigger.focus();};
 },[enabled]);
 return ref;
}
