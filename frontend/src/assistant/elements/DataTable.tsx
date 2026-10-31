// Ported from assistant-ui DataTable, copyright (c) 2026 AgentbaseAI Inc. MIT, see LICENSE.assistant-ui.
import {useId,useState} from 'react';
import type {Cell,TableDisplay} from './types';
const collator=new Intl.Collator('zh-TW',{numeric:true,sensitivity:'base'});
const value=(cell:Cell|undefined)=>cell==null?'未提供':typeof cell==='number'?cell.toLocaleString('zh-TW'):cell;
export function DataTable({title,caption,columns,rows,rowKey,truncated,note}:TableDisplay){
 const id=useId();
 const [sort,setSort]=useState<{key:string;direction:'asc'|'desc'}|null>(null);
 const [announcement,setAnnouncement]=useState('');
 const comparable=(key:string)=>{const values=rows.map(row=>row[key]).filter(v=>v!=null);return values.length>1&&values.every(v=>typeof v===typeof values[0])};
 const numeric=(key:string)=>rows.some(row=>typeof row[key]==='number')&&rows.every(row=>row[key]==null||typeof row[key]==='number');
 const ordered=rows.map((row,index)=>({row,index}));
 if(sort)ordered.sort((a,b)=>{
  const first=a.row[sort.key],second=b.row[sort.key];
  if(first==null)return second==null?a.index-b.index:1;
  if(second==null)return -1;
  const compared=typeof first==='number'&&typeof second==='number'?first-second:collator.compare(String(first),String(second));
  return (sort.direction==='asc'?compared:-compared)||a.index-b.index;
 });
 const changeSort=(key:string,label:string)=>{
  const next=sort?.key!==key?{key,direction:'asc' as const}:sort.direction==='asc'?{key,direction:'desc' as const}:null;
  setSort(next);setAnnouncement(next?`${label}，${next.direction==='asc'?'遞增':'遞減'}排序`:'已清除排序');
 };
 const primary=columns[0];
 const keyFor=(row:Record<string,Cell>,index:number)=>`${rowKey?row[rowKey]??index:index}-${index}`;
 return <section data-slot="data-table" className="assistant-data-table" aria-labelledby={id}>
  <header className="assistant-element-heading"><h3 id={id}>{title}</h3>{caption&&<p>{caption}</p>}</header>
  <div className="assistant-data-wide"><table>
   <caption className="assistant-sr-only">{title}{caption?`，${caption}`:''}</caption>
   <thead><tr>{columns.map(column=><th key={column.key} scope="col" data-numeric={numeric(column.key)||undefined} aria-sort={sort?.key===column.key?(sort.direction==='asc'?'ascending':'descending'):undefined}>
    {comparable(column.key)?<button type="button" onClick={()=>changeSort(column.key,column.label)} aria-label={`依${column.label}排序`}>{column.label}<span aria-hidden="true">{sort?.key===column.key?(sort.direction==='asc'?' ↑':' ↓'):' ↕'}</span></button>:column.label}
   </th>)}</tr></thead>
   <tbody>{ordered.map(({row,index})=><tr key={keyFor(row,index)}>{columns.map(column=><td key={column.key} data-numeric={numeric(column.key)||undefined}>{value(row[column.key])}</td>)}</tr>)}</tbody>
  </table></div>
  {columns.some(column=>comparable(column.key))&&<label className="assistant-data-sort">排序
   <select aria-label={`${title}排序`} value={sort?JSON.stringify(sort):''} onChange={event=>{
    const next=event.target.value?JSON.parse(event.target.value) as {key:string;direction:'asc'|'desc'}:null;
    setSort(next);setAnnouncement(next?`${columns.find(column=>column.key===next.key)?.label}，${next.direction==='asc'?'遞增':'遞減'}排序`:'已清除排序');
   }}><option value="">原始順序</option>{columns.filter(column=>comparable(column.key)).flatMap(column=>(['asc','desc'] as const).map(direction=><option key={`${column.key}-${direction}`} value={JSON.stringify({key:column.key,direction})}>{column.label} · {direction==='asc'?'遞增':'遞減'}</option>))}</select>
  </label>}
  <div className="assistant-data-cards" role="list" aria-label={title}>{ordered.map(({row,index})=><div role="listitem" key={keyFor(row,index)}>
   <strong>{primary.label} · {value(row[primary.key])}</strong><dl>{columns.slice(1).map(column=><div key={column.key}><dt>{column.label}</dt><dd data-numeric={numeric(column.key)||undefined}>{value(row[column.key])}</dd></div>)}</dl>
  </div>)}</div>
  {!rows.length&&<p className="assistant-element-note" role="status">沒有符合的資料。</p>}
  {(truncated||note)&&<footer className="assistant-element-note">{truncated&&<p>僅列出部分</p>}{note&&<p>{note}</p>}</footer>}
  <p aria-live="polite" className="assistant-sr-only">{announcement}</p>
 </section>;
}
