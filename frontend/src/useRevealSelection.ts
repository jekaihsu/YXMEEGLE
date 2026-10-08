import {useEffect,useRef} from 'react';

/** Keep the selected destination visible in a locally scrolling strip. */
export function useRevealSelection<T extends HTMLElement>(selector:string,key:string){
 const ref=useRef<T>(null);
 useEffect(()=>{ref.current?.querySelector<HTMLElement>(selector)?.scrollIntoView?.({inline:'center',block:'nearest'})},[selector,key]);
 return ref;
}
