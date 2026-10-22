import {useState} from 'react';
import type {SopSignals} from './sopTaskApi';
export interface SopWorkItem {id:string;task_id:string;project_id:string;title:string;signal:keyof SopSignals|null;completion_policy:string;state:string;review_status:string|null;return_reason:string|null}
export interface SopWorkProjection {signals:SopSignals;items:SopWorkItem[];reviewer_items?:SopWorkItem[]}
const LABELS = {routine_completed:'一般任務已完成',important_submitted:'重要任務已提交',important_returned:'重要任務已退回'} satisfies Record<keyof SopSignals,string>;
export const sopTaskHref=(item:SopWorkItem)=>`#view=project&project=${encodeURIComponent(item.project_id)}&tab=flow&task_source=sop_local&task=${encodeURIComponent(item.task_id)}`;
export function SopWorkSummary({signals,items}:{signals?:SopSignals;items?:SopWorkItem[]}) {
 const [selected,setSelected]=useState<keyof SopSignals|null>(null);
 if(!signals||!items)return null;
 return <section className="sop-tasks" aria-label="SOP 作業統計"><div className="pf-actions">{(Object.keys(LABELS) as (keyof SopSignals)[]).map(key=><button type="button" className="button" key={key} aria-expanded={selected===key} onClick={()=>setSelected(selected===key?null:key)}>{LABELS[key]} {signals[key]}</button>)}</div>
  {selected&&<ul>{items.filter(t=>t.signal===selected).map(t=><li key={t.id}><a href={sopTaskHref(t)}>{t.title}</a>{t.review_status==='returned'&&t.return_reason&&<p>退回原因：{t.return_reason}。請修正後重新提交。</p>}</li>)}{signals[selected]===0&&<li>目前沒有符合條件的任務</li>}</ul>}
 </section>;
}
const record=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
const signal=(value:unknown):value is keyof SopSignals=>typeof value==='string'&&Object.hasOwn(LABELS,value);
const count=(value:unknown):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;
function parseItems(values:unknown):SopWorkItem[]|null {
 if(!Array.isArray(values))return null;
 const result:SopWorkItem[]=[];
 for(const item of values){
  if(!record(item))return null;
  const {id,task_id,project_id,title,signal:status,completion_policy,state,review_status,return_reason}=item;
  if(typeof id!=='string'||typeof task_id!=='string'||typeof project_id!=='string'||typeof title!=='string'||typeof completion_policy!=='string'||typeof state!=='string'||!(status===null||signal(status))||!(review_status===null||typeof review_status==='string')||!(return_reason===null||typeof return_reason==='string'))return null;
  result.push({id,task_id,project_id,title,signal:status,completion_policy,state,review_status,return_reason});
 }
 return new Set(result.map(t=>t.id)).size===result.length?result:null;
}
export function parseSopWork(value:unknown):SopWorkProjection|null {
 if(!record(value)||!record(value.signals))return null;
 const {routine_completed,important_submitted,important_returned}=value.signals;
 if(!count(routine_completed)||!count(important_submitted)||!count(important_returned))return null;
 const items=parseItems(value.items),reviewers=value.reviewer_items===undefined?[]:parseItems(value.reviewer_items);
 if(!items||!reviewers)return null;
 const signals={routine_completed,important_submitted,important_returned};
 for(const key of Object.keys(LABELS))if(signal(key)&&signals[key]!==items.filter(t=>t.signal===key).length)return null;
 return {signals,items,reviewer_items:reviewers};
}
