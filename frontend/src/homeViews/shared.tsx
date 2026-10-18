import {Stat} from '../design';
import type {HomeItem,PanelRead} from '../useHomePanels';
import {Message,WorkPreview} from '../homeCards';
export const dayOffset=(day:string,offset:number)=>new Date(Date.parse(`${day}T00:00:00Z`)+offset*86400000).toISOString().slice(0,10);
export function panelCount(read:PanelRead,predicate:(item:HomeItem)=>boolean):number|null{
 return read.body?.complete&&!read.body.has_more&&read.body.readState!=='disabled'?read.body.items.filter(predicate).length:null;
}
export function PanelNote({read}:{read:PanelRead}){
 return <>{read.error&&<Message>工作來源更新失敗，請重新讀取。{read.body?'保留上次資料。':''}</Message>}
  {read.body&&(!read.body.complete||read.body.has_more||read.body.readState==='disabled')&&<Message>資料尚未完整；目前僅顯示已載入的預覽。</Message>}
  {read.body?.freshness.status==='stale'&&<Message>上次快照可能已過期，請重新讀取。</Message>}</>;
}
export function PanelRows({read,today,items=read.body?.items||[]}:{read:PanelRead;today:string;items?:HomeItem[]}){
 return <>{items.slice(0,5).map(item=><WorkPreview key={item.id} item={item} today={today}/>)}
  {!items.length&&<Message>{read.pending?'讀取中…':read.body?.complete?'目前沒有符合條件的事項。':'清單尚待核對。'}</Message>}<PanelNote read={read}/></>;
}
export function Kpis({values}:{values:{label:string;value:number|null}[]}){
 return <div className="home-kpis">{values.map(({label,value})=><Stat key={label} label={label} value={value===null?'待核對':value}/>)}</div>;
}
