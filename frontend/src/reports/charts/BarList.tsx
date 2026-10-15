import {useMemo} from 'react';
import {number} from '../reportsView';
export type BarDatum={label:string; value:number|null; display?:string; detail?:string; selectable?:boolean};
export default function BarList({data,label,onSelect}:{data:BarDatum[];label:string;onSelect?:(label:string)=>void}){
 const max=useMemo(()=>Math.max(1,...data.map(d=>d.value??0)),[data]);
 if(!data.length)return <p className="reports-empty">此範圍沒有資料</p>;
 return <div className="reports-bars" aria-label={label}>{data.map(d=>{const selectable=onSelect&&d.selectable!==false;const Row=selectable?'button':'div';return <Row key={d.label} className="reports-bar-row" onClick={selectable?()=>onSelect?.(d.label):undefined} aria-label={`${d.label}，${d.display??number(d.value)}${selectable?'，套用篩選':''}`}><span className="reports-bar-label"><span>{d.label}</span><strong>{d.display??number(d.value)}</strong></span><svg role="img" aria-label={`${label} · ${d.label} ${d.display??number(d.value)}${d.detail?` · ${d.detail}`:''}`} viewBox="0 0 600 8" preserveAspectRatio="none"><rect width="600" height="8" rx="4" className="reports-track"/><rect width={d.value==null?0:Math.max(2,d.value/max*600)} height="8" rx="4" className="reports-bar"/></svg></Row>})}</div>;
}
