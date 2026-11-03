import {Fragment,useEffect,useRef,useState,type ReactNode} from 'react';
import {DataState} from './design/DataState';
import type {ManagerOverviewView,Drilldown,OverviewSort,FactCell} from './managerOverviewView';
import './p2-lists.css';
import './manager-overview.css';
export interface ManagerOverviewCallbacks {filters?:ReactNode;onRefresh?:()=>void;onSelect?:(id:string|null)=>void;onDrilldown?:(d:Drilldown)=>void;onNavigate?:(route:string)=>void;onBack?:()=>void;onSort?:(s:OverviewSort)=>void;onSourceHealthLink?:(r:'sources')=>void}
export type ManagerOverviewProps=(ManagerOverviewView|{view:ManagerOverviewView})&ManagerOverviewCallbacks;
const detailCopy=(value:string|null|undefined,fallback:string)=>value&&/[\u3400-\u9fff]/.test(value)?value:fallback;
const fact=(cell:FactCell)=>cell.known?cell.text:'來源未提供';
export function ManagerOverview(props:ManagerOverviewProps){
 const view='header' in props?props:props.view;
 const [visible,setVisible]=useState(25);
 const refs=useRef(new Map<string,HTMLButtonElement>()),previous=useRef(view.selectedId);
 useEffect(()=>{if(previous.current&&!view.selectedId)refs.current.get(previous.current)?.focus();previous.current=view.selectedId},[view.selectedId]);
 useEffect(()=>{setVisible(25)},[view.header.scopeLabel]);
 const cases=view.snapshot.cases;
 const counts=new Map<string,number>();for(const row of cases)if(row.label.known)counts.set(row.label.text,(counts.get(row.label.text)??0)+1);
 const states:readonly string[]=view.snapshot.state.states;
 const loading=states.includes('loading'),denied=states.includes('forbidden');
 const canCount=cases.length>0||states.some(s=>s==='complete_empty'||s==='filtered_empty');
 const sourceLink=<button type="button" onClick={()=>props.onSourceHealthLink?props.onSourceHealthLink('sources'):props.onNavigate?.('sources')}>查看來源健康</button>;
 const cards=view.snapshot.cards.length?view.snapshot.cards:[['confirmation_versions','確認單版本'],['stable_cases','案件'],['pending_decisions','待決策'],['overdue_cases','逾期案件']].map(([id,label])=>({id,label,known:false,valueText:'—',unitLabel:'',asOfLabel:view.header.asOfLabel,stateLabel:'尚未載入',reason:'尚未載入',drilldown:null}));
 return <div className="manager-overview-root">
  <header className="overview-heading"><h1>{view.header.title}</h1>{props.onRefresh&&<button onClick={props.onRefresh}>重新讀取</button>}<p>{view.header.asOfLabel} · {view.header.scopeLabel}</p><p>來源：管理總覽快照 · 每列是一個專案 ID；確認單版本另計。</p></header>
  {props.filters}
  {view.header.filterMismatch&&<DataState kind="Partial" title="篩選尚未套用" body={view.header.filterMismatch}/>}
  {loading?<DataState kind="Loading" title="正在載入管理總覽" body="快照摘要與案件資料尚未載入，筆數尚未確認。"/>:denied?<DataState kind="Denied" title="無權檢視管理總覽" body="案件與摘要已停止顯示。"/>:states.some(s=>!['complete_empty','filtered_empty'].includes(s))&&<DataState kind={states.includes('read_failed')?'Error':states.includes('stale')?'Stale':'Partial'} title={states.includes('stale')?'舊資料 · 資料待更新':'統計與來源資料尚未完整'} body="未知摘要不代表沒有逾期或待決策；下方只顯示已載入的專案資料。" actions={sourceLink}/>}
  {!denied&&<section className="overview-summary" aria-label="快照摘要"><h2>快照摘要</h2><div>{cards.map(card=><div key={card.id}><span>{card.label}</span><strong>{card.known?card.valueText:'—'}</strong><small>{card.known?card.unitLabel:'尚未載入'} · {card.asOfLabel}</small>{card.known&&card.drilldown&&<button onClick={()=>props.onDrilldown?.(card.drilldown!)}>查看清單</button>}</div>)}</div></section>}
  {!denied&&<section className="overview-cases"><h2>未完成案件 · {canCount?`${cases.length} 列（已載入）`:'筆數尚未載入'}</h2><p className="overview-scope-note">同名提示僅按本次載入名稱計算，不代表同一案件或確認單版本。</p>
   {!cases.length?<p>{loading?'正在讀取案件…':view.snapshot.casesEmptyLabel||'案件資料尚未提供。'}</p>:<><div className="overview-scroll" role="region" aria-label="未完成案件清單" tabIndex={0}><table><caption>來源：管理總覽快照 · {view.header.asOfLabel}</caption><thead><tr><th scope="col">案件</th><th scope="col">負責人</th><th scope="col">操作</th></tr></thead><tbody>{cases.slice(0,visible).map(row=>{
    const selected=view.selectedId===row.id;
    return <Fragment key={row.id}><tr className={selected?'is-selected':undefined}><td data-label="案件"><small className="overview-project-id">{row.id}</small><strong>{row.label.known?row.label.text:'案件名稱未提供'}</strong>{(counts.get(row.label.text)??0)>1&&<small>同名 {counts.get(row.label.text)} 列（已載入名稱）</small>}</td><td data-label="負責人">{row.responsible.known?row.responsible.text:'未填'}</td><td data-label="操作"><div className="overview-actions">{row.entry&&<button onClick={()=>props.onNavigate?.(row.entry!.route)}>{row.entry.label} →</button>}<button ref={el=>{if(el)refs.current.set(row.id,el);else refs.current.delete(row.id)}} aria-expanded={selected} onClick={()=>props.onSelect?.(selected?null:row.id)} aria-label={`選取案件詳情：${row.label.text}`}>{selected?'收合':'詳情'}</button></div></td></tr>{selected&&<tr className="overview-detail"><td colSpan={3}><section aria-label={`案件詳情：${row.label.text}`}><h3>詳情 · {row.label.text}</h3><dl>{[['未完成狀態',row.unfinished],['可行動',row.actionable],['目前階段',row.currentStage],['有效期限',row.effectiveDueDate],['受阻',row.blocker],['待決策',row.pendingDecision]].map(([label,cell])=><div key={label as string}><dt>{label as string}</dt><dd>{fact(cell as FactCell)}</dd></div>)}</dl>{view.drawer.case&&<><p>{view.drawer.case.rowKeysText}</p><p>{detailCopy(view.drawer.case.rowKeysReason,'確認單來源尚未載入或對應待核對；確認單列未知，不代表沒有確認單。')}</p>{view.drawer.case.rowKeys?.length?<ul>{view.drawer.case.rowKeys.map(k=><li key={k}>{k}</li>)}</ul>:null}<p>合約金額：{view.drawer.case.amounts.text} · {detailCopy(view.drawer.case.amounts.reason,'金額尚未核准顯示，請回來源核對。')}</p></>}<button onClick={()=>props.onSelect?.(null)}>收合詳情</button></section></td></tr>}</Fragment>
   })}</tbody></table></div><footer>已顯示 {Math.min(visible,cases.length)} / {cases.length} 列{visible<cases.length&&<button onClick={()=>setVisible(n=>n+25)}>顯示更多（再 25 列）</button>}</footer></>}
  </section>}
 </div>
}
