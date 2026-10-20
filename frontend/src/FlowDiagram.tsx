import {useRef, type KeyboardEvent} from 'react';
import {ArrowRight, Check, Circle, CircleDot, Clock3, Minus, TriangleAlert} from 'lucide-react';
import {Avatar} from './Avatar';
import {isProductionNode,NODE_ASSIGNMENT_ORDER} from './nodeAssignmentApi';
import {Skeleton} from './design';
import type {FlowNode, FlowProgress} from './flowModel';
const stateIcons: Record<string, typeof Check> = {'未開始':Circle,'待處理':Clock3,'進行中':CircleDot,'待審核':TriangleAlert,'已完成':Check,'略過':Minus};
export function FlowDiagram({nodes,overall,selected,loading,onSelect}:{nodes:FlowNode[];overall:FlowProgress;selected:string;loading:boolean;onSelect:(key:string,keyboard?:boolean)=>void}) {
 const buttons = useRef(new Map<string,HTMLButtonElement>());
 const navigate = (event:KeyboardEvent, index:number) => {
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? nodes.length-1 : ['ArrowRight','ArrowDown'].includes(event.key) ? (index+1)%nodes.length : ['ArrowLeft','ArrowUp'].includes(event.key) ? (index+nodes.length-1)%nodes.length : -1;
  if(next<0)return;event.preventDefault();const node=nodes[next];onSelect(node.key,true);buttons.current.get(node.key)?.focus({preventScroll:true});
 };
 return <section className="pf-diagram glass--card" aria-label="SOP 流程圖" aria-busy={loading}>
  <header><div><span className="pf-eyebrow">案件流程</span><h2>從接案到結算</h2></div><div className="pf-overall">{loading ? <Skeleton width="7rem" height="2rem"/> : <><strong>{overall.percent === null ? '未知' : `${overall.percent}%`}</strong><span>{overall.label}</span></>}</div></header>
  <ol className="pf-chain">{nodes.map((node,index) => {const Icon=stateIcons[node.state] || Circle;return <li key={node.key}>
   <button ref={element=>{if(element)buttons.current.set(node.key,element);else buttons.current.delete(node.key)}} className="pf-node" data-state={node.state} data-production={isProductionNode(node.key) || undefined} aria-current={selected === node.key ? 'step' : undefined} aria-label={`${node.label}節點，${loading ? '讀取中' : node.state}，${node.tasks.done}/${node.tasks.total} 項任務，${node.progress.label}${node.progress.percent === null ? '' : `${node.progress.percent}%`}${node.overdue ? '，逾期' : ''}`} tabIndex={selected===node.key || !selected && index===0 ? 0 : -1} disabled={loading} onKeyDown={e=>navigate(e,index)} onClick={()=>onSelect(node.key)}>
    <span className="pf-node-title"><span className="pf-step-index">{String(index+1).padStart(2,'0')}</span><strong>{node.label}</strong></span>
    {loading ? <><Skeleton height="1.4rem"/><Skeleton lines={2}/><Skeleton height=".4rem"/></> : <>
     <span className="pf-state"><Icon size={14} aria-hidden="true"/>{node.state}</span>
     <span className="pf-owner">{node.owners[0] && <Avatar small user={node.owners[0]}/>}<span>{node.owners.map(p=>p.name).join('、') || '尚未指派'}</span></span>
     <span className="pf-task-count">{node.tasks.done}/{node.tasks.total} 項任務</span>
     {node.progress.percent === null ? <span className="pf-progress-unknown">{node.progress.label}</span> : <><progress value={node.progress.percent} max={100} aria-label={`${node.label}${node.progress.label}`}/><small>{node.progress.percent}% · {node.progress.basis === 'tasks' ? '任務' : '節點'}</small></>}
     {isProductionNode(node.key) && <span className="pf-quantity"><span>計畫 {node.quantity.planned ?? '未知'}</span><span>{node.quantity.actual === null ? '實際完成量來源未連結' : `實際 ${node.quantity.actual}${node.quantity.unit ? ` ${node.quantity.unit}` : '（單位待核對）'}`}</span></span>}
     {node.assignment?.can_submit_hint && <strong className="pf-submit-hint">可送審</strong>}<span className="pf-due">{node.overdue && <TriangleAlert size={13} aria-hidden="true"/>}{node.overdue ? '逾期 · ' : '期限 · '}{node.deadline?.slice(0,10) || '未排定'}</span>
    </>}
   </button>{index<nodes.length-1 && <ArrowRight size={14} className="pf-chain-arrow" aria-hidden="true"/>}
  </li>})}</ol>
 </section>;
}
export function FlowPanelSkeleton(){return <section className="pf-panel glass--card" aria-label="節點明細載入中" aria-busy="true"><Skeleton width="40%" height="2rem"/><div className="pf-facts"><Skeleton lines={2}/><Skeleton lines={2}/><Skeleton lines={2}/></div><Skeleton height="10rem"/><Skeleton height="3rem" lines={3}/></section>}

export function FlowWorkspaceSkeleton(){return <div className="project-flow" aria-label="案件流程載入中" aria-busy="true"><section className="pf-diagram glass--card"><header><Skeleton height="2rem" width="12rem"/><Skeleton width="8rem"/></header><ol className="pf-chain">{NODE_ASSIGNMENT_ORDER.map(key=><li key={key}><div className="pf-node" data-production={isProductionNode(key) || undefined}><Skeleton width="70%"/><Skeleton height="1.4rem"/><Skeleton lines={3}/></div></li>)}</ol></section><FlowPanelSkeleton/></div>}
