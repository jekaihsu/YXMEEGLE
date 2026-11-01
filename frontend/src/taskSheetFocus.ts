import {useEffect,useRef} from 'react';

const FIELDS='input:not([disabled]):not([type="hidden"]),textarea:not([disabled]),select:not([disabled]),button:not([disabled])';

/** Moves focus to the first enabled control (field, or the assignee picker button when it is the only one) once, when an editor that replaced the read-only view mounts. */
export function useFocusFirstField<T extends HTMLElement>(enabled:boolean){
 const ref=useRef<T>(null);
 useEffect(()=>{if(enabled)ref.current?.querySelector<HTMLElement>(FIELDS)?.focus()},[]);
 return ref;
}

/** Returns a ref for the 編輯 button; focus goes back to it when `editing` turns off (cancel or save). */
export function useRestoreEditFocus(editing:boolean){
 const ref=useRef<HTMLButtonElement>(null),was=useRef(editing);
 useEffect(()=>{if(was.current&&!editing)ref.current?.focus();was.current=editing},[editing]);
 return ref;
}
