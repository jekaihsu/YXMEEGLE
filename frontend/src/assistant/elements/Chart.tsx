// Ported from assistant-ui Chart, copyright (c) 2026 AgentbaseAI Inc. MIT, see LICENSE.assistant-ui.
import {useId,useState} from 'react';
import type {ChartDisplay} from './types';
export function Chart({kind,title,caption,truncated,note,unit='',headline,points}:ChartDisplay){
 const id=useId(),[active,setActive]=useState<number|null>(null);
 const width=600,height=160,pad=12;
 const max=Math.max(...points.map(p=>p.value),1),min=Math.min(...points.map(p=>p.value),0);
 const y=(value:number)=>height-pad-(value-min)/(max-min)*(height-pad*2);
 const labels=[...new Set(points.map(point=>point.label))];
 const seriesNames=[...new Set(points.map(point=>String(point.series??'資料')))];
 const series=seriesNames.map((name,index)=>({name,key:`${index+1}. ${name}`,points:points.filter(point=>String(point.series??'資料')===name)}));
 const grouped=series.length>1;
 const step=(width-pad*2)/Math.max(labels.length,1),baseline=y(0);
 const x=(label:string)=>pad+(labels.indexOf(label)+.5)*step;
 const color=(index:number)=>`hsl(${index*137.5} 45% 40%)`;
 const stat=kind==='stat'?points[0]:undefined;
 headline=stat?{label:stat.label||title,value:String(stat.value)}:headline;
 const total=points.reduce((sum,p)=>sum+p.value,0);
 let angle=-Math.PI/2;
 const headlineUnit=headline&&/^-?\d+(\.\d+)?$/.test(String(headline.value))?unit:'';
 const summary=`${title}${headline?`。${headline.label} ${headline.value}${headlineUnit}`:''}`;
 return <section data-slot="chart" className="assistant-chart" aria-labelledby={id}>
  <header className="assistant-element-heading"><h3 id={id}>{title}</h3>{caption&&<p>{caption}</p>}</header>
  {headline&&<div className="assistant-chart-headline"><span>{headline.label}</span><strong>{headline.value}<small>{headlineUnit}</small></strong></div>}
  {kind!=='stat'&&<svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={summary} preserveAspectRatio={kind==='pie'?'xMidYMid meet':'none'}>
   <line x1={pad} x2={width-pad} y1={baseline} y2={baseline} className="assistant-chart-axis"/>
   {kind==='line'?series.map((group,index)=><g key={group.name}>
    <polyline points={group.points.map(point=>`${x(point.label)},${y(point.value)}`).join(' ')} fill="none" stroke={color(index)} strokeWidth="3" strokeDasharray={index%2?'6 4':undefined}><title>{group.key}</title></polyline>
    {group.points.length===1&&<circle cx={x(group.points[0].label)} cy={y(group.points[0].value)} r="4" fill={color(index)}><title>{group.key} · {group.points[0].label} · {group.points[0].value}{unit}</title></circle>}
    {grouped&&<text x={x(group.points.at(-1)!.label)} y={Math.max(12,y(group.points.at(-1)!.value)-8)} textAnchor="middle" fill="currentColor" fontSize="12">{index+1}</text>}
   </g>):kind==='pie'?points.map((point,index)=>{
    const start=angle;angle+=total?point.value/total*Math.PI*2:0;
    const x=(a:number)=>300+65*Math.cos(a),cy=(a:number)=>80+65*Math.sin(a);
    return <g key={index}><path d={point.value===total&&total>0?'M 300 15 A 65 65 0 1 1 300 145 A 65 65 0 1 1 300 15':`M 300 80 L ${x(start)} ${cy(start)} A 65 65 0 ${angle-start>Math.PI?1:0} 1 ${x(angle)} ${cy(angle)} Z`} fill={`hsl(${index*137.5} 45% 48%)`} stroke="currentColor"><title>{point.label} · {point.value}{unit}</title></path><text x={300+48*Math.cos((start+angle)/2)} y={80+48*Math.sin((start+angle)/2)} textAnchor="middle" dominantBaseline="middle" fill="white" stroke="black" strokeWidth="2" paintOrder="stroke" fontSize="12">{index+1}</text></g>;
   }):points.map((point,index)=>{
    const seriesIndex=seriesNames.indexOf(String(point.series??'資料'));
    const barWidth=step/series.length;
    const barX=x(point.label)-step/2+seriesIndex*barWidth+barWidth*.18;
    return <g key={index}><rect x={barX} y={Math.min(y(point.value),baseline)} width={barWidth*.64} height={Math.max(1,Math.abs(baseline-y(point.value)))} rx="3" className="assistant-chart-bar" style={{fill:color(seriesIndex)}} data-active={active===index||undefined} onMouseEnter={()=>setActive(index)} onMouseLeave={()=>setActive(null)}><title>{series[seriesIndex].key} · {point.label} · {point.value}{unit}</title></rect>
     {grouped&&<text x={barX+barWidth*.32} y={Math.max(12,Math.min(y(point.value),baseline)-5)} textAnchor="middle" fill="currentColor" fontSize="12">{seriesIndex+1}</text>}
    </g>;
   }) }

  </svg>}
  {grouped&&kind!=='pie'&&<p className="assistant-chart-legend">{series.map(group=><span key={group.name}>{group.key}　</span>)}</p>}
  <div className="assistant-chart-labels" style={{gridTemplateColumns:`repeat(${Math.min(Math.max(points.length,1),6)},minmax(0,1fr))`}}>
   {points.map((point,index)=><div key={index} className="assistant-chart-point">
    <button type="button" aria-label={`查看${point.label}的圖表提示`} aria-describedby={active===index?`${id}-tooltip-${index}`:undefined} onClick={()=>setActive(index)} onFocus={()=>setActive(index)} onBlur={()=>setActive(null)} onMouseEnter={()=>setActive(index)} onMouseLeave={()=>setActive(null)} onKeyDown={event=>{if(event.key==='Escape')setActive(null)}}><span>{kind==='pie'&&`${index+1}. `}{point.label}{point.series!=null&&` · ${point.series}`}</span><strong>{point.value}{unit}</strong></button>
    {active===index&&<span role="tooltip" id={`${id}-tooltip-${index}`} className="assistant-chart-tooltip">{point.label} · {point.value}{unit}</span>}
   </div>)}
  </div>
  {!points.length&&<p role="status" className="assistant-element-note">沒有可繪製的資料。</p>}
  {(truncated||note)&&<footer className="assistant-element-note">{truncated&&<p>僅列出部分</p>}{note&&<p>{note}</p>}</footer>}
  <table className="assistant-sr-only"><caption>{title}，圖表資料{caption&&`，${caption}`}{truncated&&'，僅列出部分'}{note&&`，${note}`}</caption><thead><tr><th scope="col">項目</th><th scope="col">數值{unit&&`（${unit}）`}</th></tr></thead><tbody>{points.map((point,index)=><tr key={index}><th scope="row">{point.label}{point.series!=null&&` · ${point.series}`}</th><td>{point.value}</td></tr>)}</tbody></table>
 </section>;
}
