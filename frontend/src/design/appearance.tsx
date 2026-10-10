import {createContext,useContext,useEffect,useMemo,useState,type ReactNode} from 'react';

export type ThemeMode='system'|'light'|'dark';
export type TextSize='s'|'m'|'l'|'xl';
export type Appearance={theme:ThemeMode;text:TextSize};
export const APPEARANCE_KEY='yx.appearance';
const DEFAULT:Appearance={theme:'system',text:'m'};

const read=():Appearance=>{
 try{const v=JSON.parse(localStorage.getItem(APPEARANCE_KEY)||'null');
  return {theme:['light','dark'].includes(v?.theme)?v.theme:'system',text:['s','l','xl'].includes(v?.text)?v.text:'m'};
 }catch{return DEFAULT}
};
// Mirrors the pre-paint script in index.html: "system"/"m" are expressed by leaving the attribute off.
const apply=({theme,text}:Appearance)=>{
 const root=document.documentElement;
 if(theme==='system')root.removeAttribute('data-theme');else root.setAttribute('data-theme',theme);
 if(text==='m')root.removeAttribute('data-text');else root.setAttribute('data-text',text);
};

const Ctx=createContext<Appearance&{set:(next:Partial<Appearance>)=>void}>({...DEFAULT,set:()=>{}});
export const useAppearance=()=>useContext(Ctx);

export function ThemeProvider({children}:{children:ReactNode}){
 const[value,setValue]=useState(read);
 useEffect(()=>{
  apply(value);
  try{localStorage.setItem(APPEARANCE_KEY,JSON.stringify(value))}catch{/* storage unavailable: appearance still applies for this visit */}
 },[value]);
 const ctx=useMemo(()=>({...value,set:(next:Partial<Appearance>)=>setValue(v=>({...v,...next}))}),[value]);
 return <Ctx.Provider value={ctx}>{children}</Ctx.Provider>;
}
