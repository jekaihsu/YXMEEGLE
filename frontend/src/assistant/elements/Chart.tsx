// Ported from assistant-ui Chart, copyright (c) 2026 AgentbaseAI Inc. MIT, see LICENSE.assistant-ui.
import {useId,useState} from 'react';
import type {ChartDisplay} from './types';
export function Chart({title,unit='',headline,points}:ChartDisplay){
 const id=useId(),[active,setActive]=useState<number|null>(null);
 const width=600,height=160,pad=12;
 const max=Math.max(...points.map(p=>p.value),1),min=Math.min(...points.map(p=>p.value),0);
 const y=(value:number)=>height-pad-(value-min)/(max-min)*(height-pad*2);
 const step=(width-pad*2)/Math.max(points.length,1),baseline=y(0);
 const summary=`${title}。${points.map(p=>`${p.label} ${p.value}${unit}`).join('，')}`;
 return <section data-slot="chart" className="assistant-chart" aria-labelledby={id}>
  <header className="assistant-element-heading"><h3 id={id}>{title}</h3></header>
  {headline&&<div className="assistant-chart-headline"><span>{headline.label}</span><strong>{headline.value}<small>{unit}</small></strong></div>}
  <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary} preserveAspectRatio="none">
   <line x1={pad} x2={width-pad} y1={baseline} y2={baseline} className="assistant-chart-axis"/>
   {points.map((point,index)=><rect key={index} x={pad+index*step+step*.18} y={Math.min(y(point.value),baseline)} width={step*.64} height={Math.max(1,Math.abs(baseline-y(point.value)))} rx="3" className="assistant-chart-bar" data-active={active===index||undefined}/>) }
  </svg>
  <div className="assistant-chart-labels" style={{gridTemplateColumns:`repeat(${Math.max(points.length,1)},minmax(0,1fr))`}}>
   {points.map((point,index)=><div key={index} className="assistant-chart-point">
    <button type="button" aria-label={`${point.label} ${point.value}${unit}`} aria-describedby={active===index?`${id}-tooltip-${index}`:undefined} onFocus={()=>setActive(index)} onBlur={()=>setActive(null)} onMouseEnter={()=>setActive(index)} onMouseLeave={()=>setActive(null)} onKeyDown={event=>{if(event.key==='Escape')setActive(null)}}><span>{point.label}</span><strong>{point.value}{unit}</strong></button>
    {active===index&&<span role="tooltip" id={`${id}-tooltip-${index}`} className="assistant-chart-tooltip">{point.label} · {point.value}{unit}</span>}
   </div>)}
  </div>
  {!points.length&&<p role="status" className="assistant-element-note">沒有可繪製的資料。</p>}
  <table className="assistant-sr-only"><caption>{title}，圖表資料</caption><thead><tr><th scope="col">項目</th><th scope="col">數值{unit&&`（${unit}）`}</th></tr></thead><tbody>{points.map((point,index)=><tr key={index}><th scope="row">{point.label}</th><td>{point.value}</td></tr>)}</tbody></table>
 </section>;
}
