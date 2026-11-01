import {useEffect,useRef} from 'react';

export function useInputModality(){
 const root=useRef<HTMLDivElement>(null);
 useEffect(()=>{
  const keyboard=(event:KeyboardEvent)=>{
   if(root.current&&event.key==='Tab')root.current.dataset.input='keyboard';
  };
  const pointer=()=>{if(root.current)delete root.current.dataset.input};
  document.addEventListener('keydown',keyboard,true);
  document.addEventListener('pointerdown',pointer,true);
  return()=>{
   document.removeEventListener('keydown',keyboard,true);
   document.removeEventListener('pointerdown',pointer,true);
  };
 },[]);
 return root;
}
