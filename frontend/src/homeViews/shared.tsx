import {Stat} from '../design';
import type {HomeItem,PanelRead} from '../useHomePanels';
import {Message,WorkPreview} from '../homeCards';
import {panelSource,sourceCount,type CountItem} from '../homeWorkSource';
export const dayOffset=(day:string,offset:number)=>new Date(Date.parse(`${day}T00:00:00Z`)+offset*86400000).toISOString().slice(0,10);
export const panelCount=(read:PanelRead,predicate:(item:CountItem)=>boolean)=>sourceCount(panelSource(read),predicate);
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
export function Kpis({values,note}:{values:{label:string;value:number|string|null;href:string}[];note?:string}){
 const known=values.filter(row=>row.value!==null);
 if(!known.length)return null;
 const partial=known.some(row=>typeof row.value==='string'&&row.value.endsWith('+'));
 const sourceNote=[partial?'+ 表示已載入預覽的至少筆數。':'',note].filter(Boolean).join(' ');
 return <section className="home-kpi-strip" data-home-card="kpi" aria-label="工作摘要"><div className="home-kpis">{known.map(({label,value,href})=><a key={label} href={href}><Stat label={label} value={value}/></a>)}</div>{sourceNote&&<p className="home-source-note">{sourceNote}</p>}</section>;
}
