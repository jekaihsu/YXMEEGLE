import {useSyncExternalStore} from 'react';
import type {HomeViewId} from './homeLayout';

export const HOME_PREVIEWS={
 member:{label:'一般組員',detail:'只看我的工作',views:['mine']},
 lead:{label:'外業經理',detail:'分配工作與我的工作',views:['assign','mine']},
 company:{label:'PM / 業務 / 管理',detail:'全公司、分配工作與我的工作',views:['company','assign','mine']},
} as const satisfies Record<string,{label:string;detail:string;views:readonly HomeViewId[]}>;
export type HomePreview=keyof typeof HOME_PREVIEWS;
const KEY='yx.home.preview';
const listeners=new Set<()=>void>();
export function readHomePreview():HomePreview|null{
 try{const value=localStorage.getItem(KEY);return value&&value in HOME_PREVIEWS?value as HomePreview:null}catch{return null}
}
export function setHomePreview(next:HomePreview|null){
 try{next?localStorage.setItem(KEY,next):localStorage.removeItem(KEY)}catch{}
 listeners.forEach(listener=>listener());
}
const subscribe=(listener:()=>void)=>{listeners.add(listener);return()=>{listeners.delete(listener)}};
export const useHomePreview=()=>useSyncExternalStore(subscribe,readHomePreview,()=>null);
export function HomePreviewPicker(){
 const preview=useHomePreview();
 const options:[HomePreview|null,string,string][]=[[null,'依登入身分','自動判斷'],...(Object.entries(HOME_PREVIEWS) as [HomePreview,typeof HOME_PREVIEWS[HomePreview]][]).map(([id,o])=>[id,o.label,o.detail] as [HomePreview,string,string])];
 return <div className="modal-body home-preview-picker" role="radiogroup" aria-label="預覽首頁角色">
  <strong>預覽首頁角色</strong>
  <p>只改變「今日工作台」的版面，方便測試；不會改變你的權限，沒有權限的資料仍會顯示無法讀取。</p>
  {options.map(([id,label,detail])=><label key={label} className={`role-option ${preview===id?'selected':''}`}><input type="radio" name="home-preview" checked={preview===id} onChange={()=>setHomePreview(id)}/><span><strong>{label}</strong><small>{detail}</small></span></label>)}
 </div>;
}
