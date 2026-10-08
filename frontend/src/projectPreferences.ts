import {useEffect,useState} from 'react';

export const PROJECT_PREFERENCES_KEY='yx.caseOverview';
export const PROJECT_COLUMNS=[
 {id:'name',label:'案件名稱',width:17},
 {id:'manager',label:'專案經理',width:6},
 {id:'stage',label:'目前作業',width:6.5},
 {id:'workflow',label:'狀態',width:10},
 {id:'deadline',label:'有效期限',width:7.5},
 {id:'contract',label:'合約金額',width:8.5},
 {id:'verification',label:'資料驗證',width:4.5},
 {id:'progress',label:'任務進度',width:7},
 {id:'admission',label:'執行歸屬',width:10},
] as const;
export type ProjectColumn=typeof PROJECT_COLUMNS[number]['id'];
type Preferences={version:2;density:'compact'|'comfortable';hiddenColumns:ProjectColumn[]};
const defaults:Preferences={version:2,density:'comfortable',hiddenColumns:['verification','progress','admission']};
const read=():Preferences=>{
 try{
  const value=JSON.parse(localStorage.getItem(PROJECT_PREFERENCES_KEY)||'null');
  if(!value||typeof value!=='object'||!Array.isArray(value.hiddenColumns))return defaults;
  // The v1 default adopts the quieter layout; custom choices survive.
  // Merged status stays visible if either legacy workflow or attention was visible.
  if(value.version!==2&&value.density==='compact'&&value.hiddenColumns.length===2&&['admission','contract'].every(id=>value.hiddenColumns.includes(id)))return defaults;
  return {version:2,density:value.density==='compact'?'compact':'comfortable',hiddenColumns:PROJECT_COLUMNS.filter(c=>c.id!=='name'&&value.hiddenColumns.includes(c.id)&&(c.id!=='workflow'||value.version===2||value.hiddenColumns.includes('attention'))).map(c=>c.id)};
 }catch{return defaults}
};
export function useProjectPreferences(){
 const [value,set]=useState(read);
 useEffect(()=>{try{localStorage.setItem(PROJECT_PREFERENCES_KEY,JSON.stringify(value))}catch{/* Preferences still apply for this visit when storage is unavailable. */}},[value]);
 return [value,set] as const;
}
