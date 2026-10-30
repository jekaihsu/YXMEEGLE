import {useEffect,useRef, type KeyboardEvent} from 'react';
import {Check, Circle, CircleDot, Clock3, Minus, TriangleAlert} from 'lucide-react';
import {isProductionNode,NODE_ASSIGNMENT_ORDER} from './nodeAssignmentApi';
import {Skeleton} from './design';
import type {FlowNode, FlowProgress} from './flowModel';
const stateIcons: Record<string, typeof Check> = {'未開始':Circle,'待處理':Clock3,'進行中':CircleDot,'待審核':TriangleAlert,'已完成':Check,'略過':Minus};
export function FlowDiagram({nodes,overall,selected,loading,onSelect,compact=false,selectionFollowsFocus=false,stageNavigation=false,currentIds=[]}:{nodes:FlowNode[];overall:FlowProgress;selected:string;loading:boolean;onSelect:(key:string,keyboard?:boolean)=>void;compact?:boolean;selectionFollowsFocus?:boolean;stageNavigation?:boolean;currentIds?:string[]}) {
 const buttons = useRef(new Map<string,HTMLButtonElement>());
 const chain=useRef<HTMLOListElement>(null);
 useEffect(()=>{
  if(!stageNavigation||!chain.current)return;
  const button=buttons.current.get(selected)?.getBoundingClientRect(),viewport=chain.current.getBoundingClientRect();
  if(button&&(button.left<viewport.left||button.right>viewport.right))chain.current.scrollLeft+=button.left-viewport.left;
 },[stageNavigation,selected]);
 const navigate = (event:KeyboardEvent, index:number) => {
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? nodes.length-1 : ['ArrowRight','ArrowDown'].includes(event.key) ? (index+1)%nodes.length : ['ArrowLeft','ArrowUp'].includes(event.key) ? (index+nodes.length-1)%nodes.length : -1;
  if(next<0)return;event.preventDefault();const node=nodes[next];if(!compact || selectionFollowsFocus)onSelect(node.key,true);buttons.current.get(node.key)?.focus({preventScroll:true});if(compact && chain.current){const button=buttons.current.get(node.key)?.getBoundingClientRect(),viewport=chain.current.getBoundingClientRect();if(button && button.left<viewport.left)chain.current.scrollLeft-=viewport.left-button.left;else if(button && button.right>viewport.right)chain.current.scrollLeft+=button.right-viewport.right;}
 };
 return <section className={`pf-diagram${compact ? ' pf-diagram-compact' : ' glass--card'}${stageNavigation?' pf-stage-nav':''}`} aria-label="SOP 流程圖" aria-busy={loading}>
  {compact ? null : <header><div><span className="pf-eyebrow">案件流程</span><h2>從接案到結算</h2></div><div className="pf-overall">{loading ? <Skeleton width="7rem" height="2rem"/> : <><strong>{overall.percent === null ? '未知' : `${overall.percent}%`}</strong><span>{overall.label}</span></>}</div></header>}
  {stageNavigation&&<p className="pf-stage-context">目前階段：{nodes.filter(n=>currentIds.includes(n.key)).map(n=>n.label).join('、')||'待確認'}<br/>已選取：{nodes.find(n=>n.key===selected)?.label}</p>}
  <ol ref={chain} className="pf-chain">{nodes.map((node,index) => {const Icon=stateIcons[node.state] || Circle;return <li key={node.key}>
   <button ref={element=>{if(element)buttons.current.set(node.key,element);else buttons.current.delete(node.key)}} className="pf-node" data-state={node.state} data-production={isProductionNode(node.key) || undefined} aria-current={selected === node.key ? 'step' : undefined} aria-label={compact && !selectionFollowsFocus ? `${node.label}節點，${loading ? '讀取中' : node.state}，負責人 ${node.owners.map(p=>p.name).join('、') || '尚未指派'}` : `${node.label}節點，${loading ? '讀取中' : node.state}，${node.tasks.done}/${node.tasks.total} 項任務，${node.progress.label}${node.progress.percent === null ? '' : `${node.progress.percent}%`}${node.overdue ? '，逾期' : ''}，負責人 ${node.owners.map(p=>p.name).join('、') || '尚未指派'}，期限 ${node.deadline?.slice(0,10) || '未排定'}${isProductionNode(node.key) ? `，計畫 ${node.quantity.planned ?? '未知'}，${node.quantity.actual === null ? '實際完成量來源未連結' : `實際 ${node.quantity.actual}${node.quantity.unit ? ` ${node.quantity.unit}` : '（單位待核對）'}`}` : ''}${node.needs ? `，${node.needs}` : ''}`} tabIndex={selected===node.key || !selected && index===0 ? 0 : -1} disabled={loading} onKeyDown={e=>navigate(e,index)} onClick={()=>onSelect(node.key)}>
    <span className="pf-step-circle" aria-hidden="true">{loading ? <Skeleton width="100%" height="100%"/> : ['已完成','略過','待審核'].includes(node.state) ? <Icon size={18}/> : String(index+1).padStart(2,'0')}</span>
    <span className="pf-node-title"><strong>{node.label}</strong></span>
    {stageNavigation&&<span className="pf-stage-marker">{currentIds.includes(node.key)&&'目前階段'}{currentIds.includes(node.key)&&selected===node.key&&' · '}{selected===node.key&&'已選取'}</span>}
    {loading ? <><Skeleton width="4rem"/><Skeleton width="5rem"/></> : <>
     <span className="pf-state"><Icon size={14} aria-hidden="true"/>{node.state}</span>
     {node.needs && <span className="pf-needs">{node.needs}</span>}
    </>}
   </button>
  </li>})}</ol>{compact && <div className="po-stage-scroll" role="group" aria-label="捲動流程節點"><button aria-label="向前捲動流程節點" onClick={()=>chain.current?.scrollBy({left:-288})}>←</button><button aria-label="向後捲動流程節點" onClick={()=>chain.current?.scrollBy({left:288})}>→</button></div>}
 </section>;
}
export function FlowPanelSkeleton(){return <section className="pf-panel glass--card" aria-label="節點明細載入中" aria-busy="true"><Skeleton width="40%" height="2rem"/><div className="pf-facts"><Skeleton lines={2}/><Skeleton lines={2}/><Skeleton lines={2}/></div><Skeleton height="10rem"/><Skeleton height="3rem" lines={3}/></section>}

export function FlowWorkspaceSkeleton(){return <div className="project-flow" aria-label="案件流程載入中" aria-busy="true"><section className="pf-diagram pf-diagram-compact"><ol className="pf-chain">{NODE_ASSIGNMENT_ORDER.map(key=><li key={key}><div className="pf-node" data-production={isProductionNode(key) || undefined}><span className="pf-step-circle"><Skeleton width="100%" height="100%"/></span><Skeleton width="70%"/><Skeleton width="4rem"/><Skeleton width="5rem"/></div></li>)}</ol></section><FlowPanelSkeleton/></div>}
