import {useCallback,useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {getSessionEpoch} from './api';
import {Badge,Button,Page,Row,Section,Sheet,Skeleton} from './design';
import {amountLabel,quoteApi,quoteKey,QUOTE_STAGES,sortQuotes,type Quote,type QuoteDetail,type QuoteSort} from './quoteApi';
import {sopErrorText,SOP_NODES,type SopNodeKey} from './sopTaskApi';
import {QuoteCreateSheet} from './QuoteCreateSheet';
import {SopImportSheet} from './SopImportSheet';
import {SopTasks,type SopImportTarget} from './SopTasks';
import {useSopTasks} from './useSopTasks';
import type {Ctx} from './appCommon';
import './SopTasks.css';
import './Quotes.css';

function QuoteSopStart({c,projectId,onStart}:{c:Ctx;projectId:string;onStart:()=>void}) {
 const sop=useSopTasks(projectId,c.s.workspace_id||'');
 return sop.state.kind==='ready'&&sop.state.data.allowed.import?<Button onClick={onStart}>開始 SOP</Button>:null;
}
function QuoteFields({q,pmName}:{q:Quote;pmName?:string}) {return <Section><Row label="報價編號" value={q.quote_no}/><Row label="工程編號" value={q.engineering_no||'未設定'}/><Row label="案件名稱" value={q.name}/><Row label="業主" value={q.client||'未設定'}/><Row label="報價日期" value={q.quoted_on||'未設定'}/><Row label="報價期限" value={q.quote_deadline||'未設定'}/><Row label="合約金額" value={amountLabel(q)}/><Row label="報價負責人" value={q.quote_owners.join('、')||'未指派'}/><Row label="PM" value={q.pm_names.join('、')||pmName||'未指派'}/><Row label="SOP 進度" value={!q.project_id?'未納入案件':q.sop_counts?`${q.sop_counts.done}/${q.sop_counts.total}`:'無任務'}/></Section>}
function LocalFlow({c,q}:{c:Ctx;q:Quote}) {
 const sop=useSopTasks(q.project_id||'',c.s.workspace_id||'');
 const [node,setNode]=useState<SopNodeKey>('sales'),[importing,setImporting]=useState<SopImportTarget>(null);
 return <><div className="quote-stages" role="group" aria-label="SOP 節點">{SOP_NODES.map(([key,label])=><Button key={key} aria-pressed={node===key} onClick={()=>setNode(key)}>{label}</Button>)}</div><SopTasks c={c} p={{id:q.project_id!}} nodeKey={node} sop={sop} importing={importing} setImporting={setImporting}/></>;
}
function QuoteSheet({c,detail,onClose,onReload}:{c:Ctx;detail:QuoteDetail;onClose:()=>void;onReload:()=>Promise<void>}) {
 const q=detail.quote,[importing,setImporting]=useState(false);
 const local=q.origin==='local';
 const openFlow=()=>{onClose();c.go(local?{view:'quotes',project:quoteKey(q),tab:'flow'}:{view:'project',project:q.project_id!,tab:'flow'})};
 return createPortal(<Sheet title={q.name} onClose={onClose}><div className="sop-import"><div className="sop-badges"><Badge>{QUOTE_STAGES[q.stage]}</Badge>{local&&<Badge>本地規劃</Badge>}</div><QuoteFields q={q} pmName={c.w.users.find(u=>u.id===q.pm_id)?.name}/>
  <div className="sop-sheet-actions">{q.project_id&&<Button variant="primary" onClick={openFlow}>開啟流程</Button>}{q.project_id&&!q.sop_counts&&<QuoteSopStart c={c} projectId={q.project_id} onStart={()=>setImporting(true)}/>}</div>
  <details><summary>來源</summary><Section>{Object.entries(detail.facts).map(([key,value])=><Row key={key} label={key} value={typeof value==='object'?JSON.stringify(value):String(value??'未設定')}/>)}</Section></details>
  {importing&&q.project_id&&<SopImportSheet projectId={q.project_id} startNode="sales" onApplied={onReload} onClose={()=>setImporting(false)} onOpenImported={openFlow}/>}
 </div></Sheet>,document.body);
}
export function Quotes({c}:{c:Ctx}) {
 const [items,setItems]=useState<Quote[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const [q,setQ]=useState(''),[stage,setStage]=useState(''),[sort,setSort]=useState<QuoteSort>('quote_no'),[dir,setDir]=useState(-1),[page,setPage]=useState(0),[size,setSize]=useState(25);
 const [detail,setDetail]=useState<QuoteDetail|null>(null),[creating,setCreating]=useState(false),[version,setVersion]=useState(0);
 const life=useRef({active:true,epoch:getSessionEpoch(),seq:0});
 const detailSeq=useRef(0);
 useEffect(()=>{life.current.active=true;return()=>{life.current.active=false}},[]);
 const current=useCallback(()=>life.current.active&&life.current.epoch===getSessionEpoch(),[]);
 const reload=()=>setVersion(v=>v+1);
 useEffect(()=>{const seq=++life.current.seq;const valid=()=>current()&&seq===life.current.seq;setLoading(true);setError('');void(async()=>{try{let rows:Quote[]=[];let offset=0;let total=1;while(offset<total){const p=await quoteApi.list(new URLSearchParams({limit:'100',offset:String(offset)}).toString(),valid);if(!valid())return;rows=rows.concat(p.items);total=p.total;if(!p.items.length)break;offset+=p.items.length}if(valid())setItems(rows)}catch(e){if(valid())setError(sopErrorText(e))}finally{if(valid())setLoading(false)}})();return()=>{life.current.seq++}},[version,current]);
 const routeKey=c.route.project;
 useEffect(()=>{if(!routeKey)return;let active=true;void quoteApi.detail(routeKey,()=>active&&current()).then(d=>{if(active&&current())setDetail(d)}).catch(e=>{if(active&&current())setError(sopErrorText(e))});return()=>{active=false}},[routeKey,version,current]);
 const open=async(item:Quote)=>{const seq=++detailSeq.current;const valid=()=>current()&&seq===detailSeq.current;setError('');try{const d=await quoteApi.detail(quoteKey(item),valid);if(valid())setDetail(d)}catch(e){if(valid())setError(sopErrorText(e))}};
 const rows=sortQuotes(items.filter(item=>(!stage||item.stage===stage)&&`${item.quote_no} ${item.name} ${item.client}`.toLocaleLowerCase().includes(q.toLocaleLowerCase())),sort,dir);
 const pages=Math.max(1,Math.ceil(rows.length/size)),safePage=Math.min(page,pages-1);
 const changeSort=(key:QuoteSort)=>{if(sort===key)setDir(v=>-v);else{setSort(key);setDir(1)}setPage(0)};
 const canCreate=c.s.features?.local_case_creation===true&&c.s.user?.capabilities?.includes('create_local_case')===true;
 const localFlow=routeKey&&c.route.tab==='flow'&&detail?.quote.origin==='local'&&quoteKey(detail.quote)===routeKey;
 return <Page title={localFlow?detail.quote.name:'報價總表'} actions={<>{localFlow&&<Button onClick={()=>{setDetail(null);c.go({view:'quotes'})}}>報價總表</Button>}{canCreate&&<Button variant="primary" onClick={e=>{e.currentTarget.focus();setCreating(true)}}>建立報價</Button>}<Button onClick={reload}>重新整理</Button></>}>
  {error&&<p role="alert">{error}<Button onClick={reload}>重試</Button></p>}
  {localFlow?<><Badge>本地規劃</Badge><LocalFlow key={detail.quote.project_id} c={c} q={detail.quote}/></>:<div className="quote-register">
   <div className="quote-stages" role="group" aria-label="報價階段"><Button aria-pressed={!stage} onClick={()=>{setStage('');setPage(0)}}>全部</Button>{Object.entries(QUOTE_STAGES).map(([key,label])=><Button key={key} aria-pressed={stage===key} onClick={()=>{setStage(key);setPage(0)}}>{label}</Button>)}</div>
   <div className="table-toolbar"><label className="search-field"><input aria-label="搜尋報價" maxLength={240} placeholder="報價編號、案件名稱、客戶" value={q} onChange={e=>{setQ(e.target.value);setPage(0)}}/></label><span role="status">{rows.length} 筆</span></div>
   {loading?<Skeleton lines={5} height="3rem"/>:<><div className="table-scroll" tabIndex={0} aria-label="報價總表"><table className="data-table quote-table"><thead><tr>{([['quote_no','報價編號'],['engineering_no','工程編號'],['name','案件名稱'],['client','業主'],['quoted_on','報價日期'],['quote_deadline','報價期限'],['contract_amount','合約金額'],['quote_owners','報價負責人'],['pm_names','PM'],['stage','階段'],['sop_counts','SOP 進度']] as const).map(([key,label])=>{const sortable=['quote_no','name','quoted_on','quote_deadline','contract_amount'].includes(key);return <th key={key} aria-sort={key===sort?(dir===1?'ascending':'descending'):undefined}>{sortable?<button onClick={()=>changeSort(key as QuoteSort)}>{label}{key===sort?(dir===1?' ↑':' ↓'):''}</button>:label}</th>})}</tr></thead><tbody>{rows.slice(safePage*size,(safePage+1)*size).map(item=><tr key={quoteKey(item)} className="clickable" onClick={()=>void open(item)}><td><button className="text-button" onClick={e=>{e.stopPropagation();void open(item)}}>{item.quote_no}</button>{item.origin==='local'&&<Badge>本地規劃</Badge>}</td><td>{item.engineering_no||'未設定'}</td><td>{item.name}</td><td>{item.client||'未設定'}</td><td>{item.quoted_on||'未設定'}</td><td>{item.quote_deadline||'未設定'}</td><td>{amountLabel(item)}</td><td>{item.quote_owners.join('、')||'未指派'}</td><td>{item.pm_names.join('、')||c.w.users.find(u=>u.id===item.pm_id)?.name||'未指派'}</td><td><Badge>{QUOTE_STAGES[item.stage]}</Badge></td><td>{!item.project_id?'未納入案件':item.sop_counts?`${item.sop_counts.done}/${item.sop_counts.total}`:'無任務'}</td></tr>)}</tbody></table></div>{!rows.length&&<p className="pf-empty">無報價</p>}<div className="quote-pagination"><label>每頁<select value={size} onChange={e=>{setSize(Number(e.target.value));setPage(0)}}>{[10,25,50,100].map(n=><option key={n}>{n}</option>)}</select></label><Button disabled={!safePage} onClick={()=>setPage(safePage-1)}>上一頁</Button><span>{safePage+1} / {pages}</span><Button disabled={safePage+1>=pages} onClick={()=>setPage(safePage+1)}>下一頁</Button></div></>}
  </div>}
  {detail&&!localFlow&&<QuoteSheet key={quoteKey(detail.quote)} c={c} detail={detail} onReload={async()=>{reload();await open(detail.quote)}} onClose={()=>{detailSeq.current++;setDetail(null);if(routeKey)c.go({view:'quotes'})}}/>}
  {creating&&<QuoteCreateSheet users={c.w.users} canImport={c.s.features?.sop_task_writes===true&&c.s.user?.capabilities?.includes('sop_task_import')===true} onClose={()=>setCreating(false)} onCreated={reload} onOpen={ref=>{setCreating(false);c.go({view:'quotes',project:ref,tab:'flow'})}}/>}
 </Page>;
}
