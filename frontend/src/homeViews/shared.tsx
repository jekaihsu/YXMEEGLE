import {Stat} from '../design';
import type {HomeItem,PanelRead} from '../useHomePanels';
import {Message,WorkPreview} from '../homeCards';
export const dayOffset=(day:string,offset:number)=>new Date(Date.parse(`${day}T00:00:00Z`)+offset*86400000).toISOString().slice(0,10);
export function panelCount(read:PanelRead,predicate:(item:HomeItem)=>boolean):number|null{
 return read.body?.complete&&!read.body.has_more&&read.body.readState!=='disabled'?read.body.items.filter(predicate).length:null;
}
export function PanelNote({read,also}:{read:PanelRead;also?:PanelRead}){
 const messages=[read,...(also?[also]:[])].flatMap(row=>[
  row.error?(row.error==='更新失敗'?'工作來源更新失敗，請重新讀取。':row.error)+(row.body?'保留上次資料。':''):'',
  row.body&&(!row.body.complete||row.body.has_more||row.body.readState==='disabled')?'資料尚未完整；目前僅顯示已載入的預覽。':'',
  row.body?.freshness.status==='stale'?'上次快照可能已過期，請重新讀取。':'',
 ]).filter(Boolean);
 return <>{[...new Set(messages)].map(message=><Message key={message}>{message}</Message>)}</>;
}
export function PanelRows({read,today,items=read.body?.items||[],also}:{read:PanelRead;today:string;items?:HomeItem[];also?:PanelRead}){
 return <>{items.slice(0,5).map(item=><WorkPreview key={item.id} item={item} today={today}/>)}
  {!items.length&&<Message>{read.pending?'讀取中…':read.body?.readState==='disabled'?'目前無法讀取這類工作。':read.body?.complete?'目前沒有符合條件的事項。':'清單尚待核對。'}</Message>}<PanelNote read={read} also={also}/></>;
}
export function Kpis({values}:{values:{label:string;value:number|null}[]}){
 return <div className="home-kpis">{values.map(({label,value})=><Stat key={label} label={label} value={value===null?'待核對':value}/>)}</div>;
}
