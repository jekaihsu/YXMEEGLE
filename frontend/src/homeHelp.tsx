import {useEffect,useRef,useState} from 'react';
import {Button} from './design';
import type {HomeViewId} from './homeLayout';
const HELP:Record<HomeViewId,string>={
 mine:'我的工作整理你的期限、待確認事項與今日人員動向，先看逾期與今天到期的工作。',
 assign:'分配工作整理管理組別的待審核事項、組員工作量與交辦進度。未指派節點尚待來源提供。',
 company:'全公司整理授權範圍的案件、各組工作量與需要留意的案件。統計不代表尚未同步的資料。',
};
export function HomeHelp({view}:{view:HomeViewId}){
 const [open,setOpen]=useState(false);
 const trigger=useRef<HTMLDivElement>(null),panel=useRef<HTMLDivElement>(null);
 const close=()=>{setOpen(false);trigger.current?.querySelector('button')?.focus()};
 useEffect(()=>{
  if(!open)return;
  panel.current?.focus();
  const key=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();setOpen(false);trigger.current?.querySelector('button')?.focus()}};
  document.addEventListener('keydown',key);
  return()=>document.removeEventListener('keydown',key);
 },[open]);
 return <div className="home-help-wrap" ref={trigger}><Button variant="plain" aria-label="使用說明" aria-expanded={open} aria-controls="home-help" onClick={()=>setOpen(value=>!value)}>?</Button>
  {open&&<div id="home-help" className="home-help glass--flat" ref={panel} tabIndex={-1} role="region" aria-label="今日工作台使用說明">
   <h2>使用說明</h2><p>{HELP[view]}</p>
   <p>我的工作提供所有人使用。分配工作提供已核實的組別主管，以及專案、業務與管理人員切換。全公司提供 PM、管理角色，以及部門名稱含專案、PM、業務或管理的人員；實際資料仍依來源權限顯示。</p>
   <p>自訂首頁可顯示、隱藏與排序卡片。設定依登入身分及視圖儲存在此瀏覽器。還原建議配置只影響目前視圖。</p>
   <p>重新讀取會更新工作區、工作清單、出勤與目前視圖的公司資料。工作來自飛書指派及本地 SOP，出勤來自人員與出勤，公司統計來自公司駕駛艙。來源未同步或只載入部分資料時會標示「資料尚未完整」；舊快照也會另行標示。</p>
   <Button onClick={close}>關閉說明</Button>
  </div>}
 </div>;
}
