import {useEffect,type CSSProperties} from 'react';
import {Check,Flag,X} from 'lucide-react';
import type {Workspace} from './types';
import './celebration.css';

export interface CompletionMoment {id:string;nodes:{id:string;name:string;project:string}[]}

/** Only a successful mutation response may create a completion moment. */
export function newlyCompletedNodes(before:Workspace,after:Workspace){
 const previous=new Map(before.projects.flatMap(p=>p.nodes.map(n=>[`${p.id}/${n.id}`,n.status] as const)));
 return after.projects.flatMap(p=>p.nodes.filter(n=>{const old=previous.get(`${p.id}/${n.id}`);return old!==undefined&&old!=='completed'&&n.status==='completed'}).map(n=>({id:n.id,name:n.name,project:p.code})));
}

export function CompletionCelebration({moment,onClose}:{moment:CompletionMoment;onClose:()=>void}){
 useEffect(()=>{const timer=window.setTimeout(onClose,9000);return()=>window.clearTimeout(timer)},[moment.id,onClose]);
 return <aside className="completion-celebration" aria-label="節點完成回饋"><div className="completion-confetti" aria-hidden="true">{Array.from({length:18},(_,i)=><i key={i} style={{'--piece':i,'--shift':`${((i*47)%330)-165}px`,'--delay':`${(i%5)*45}ms`,'--hue':i%3===0?'#0c5494':i%3===1?'#6ab8d4':'#b5cbdc'} as CSSProperties}/>)}</div><span className="celebration-check" aria-hidden="true"><Check size={29} strokeWidth={3}/></span><div className="celebration-copy" role="status" aria-live="polite"><span>完成一個重要階段</span><strong>{moment.nodes.length===1?`${moment.nodes[0].name}，完成！`:`${moment.nodes.length} 個節點已完成`}</strong><p>{moment.nodes.length===1?`${moment.nodes[0].project} · 指定確認已通過`:'指定確認已通過，成果與紀錄已保存。'}</p></div><Flag className="celebration-flag" size={24} aria-hidden="true"/><button className="icon-button" aria-label="關閉完成回饋" onClick={onClose}><X size={18}/></button></aside>
}
