import {useEffect,useState} from 'react';

export const PROJECT_PREFERENCES_KEY='yx.caseOverview';
export const PROJECT_COLUMNS=[
 {id:'name',label:'案件名稱',width:16},
 {id:'workflow',label:'工作狀態',width:5.5},
 {id:'verification',label:'資料驗證',width:5.5},
 {id:'attention',label:'需要關注',width:7.5},
 {id:'admission',label:'執行歸屬',width:10},
 {id:'manager',label:'專案經理',width:7},
 {id:'stage',label:'目前作業',width:7},
 {id:'progress',label:'任務進度',width:6.5},
 {id:'deadline',label:'有效期限',width:7.5},
 {id:'contract',label:'合約金額',width:7.5},
] as const;
export type ProjectColumn=typeof PROJECT_COLUMNS[number]['id'];
type Preferences={density:'compact'|'comfortable';hiddenColumns:ProjectColumn[]};
const defaults:Preferences={density:'compact',hiddenColumns:[]};
const read=():Preferences=>{
 try{
  const value=JSON.parse(localStorage.getItem(PROJECT_PREFERENCES_KEY)||'null');
  return {density:value?.density==='comfortable'?'comfortable':'compact',hiddenColumns:PROJECT_COLUMNS.filter(c=>c.id!=='name'&&Array.isArray(value?.hiddenColumns)&&value.hiddenColumns.includes(c.id)).map(c=>c.id)};
 }catch{return defaults}
};
export function useProjectPreferences(){
 const [value,set]=useState(read);
 useEffect(()=>{try{localStorage.setItem(PROJECT_PREFERENCES_KEY,JSON.stringify(value))}catch{/* Preferences still apply for this visit when storage is unavailable. */}},[value]);
 return [value,set] as const;
}
