import {DetailRefreshProvider,useCaseWrite} from './detailRefresh';
import {usePageOwner,usePageResource} from './viewData';
import {Select as FormSelect} from './design/Select';
import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Search} from 'lucide-react';
import {getSessionEpoch} from './api';
import {Badge,Button,DataState,Page,Row,Section,Sheet} from './design';
import {amountLabel,quoteApi,QUOTE_PAGE_SIZE,quoteKey,QUOTE_STAGES,sortQuotes,type Quote,type QuoteDetail,type QuoteSort} from './quoteApi';
import {SopError,sopErrorText,SOP_NODES,type SopNodeKey} from './sopTaskApi';
import {QuoteCreateSheet} from './QuoteCreateSheet';
import {SopImportSheet} from './SopImportSheet';
import {SopTasks,type SopImportTarget} from './SopTasks';
import {useSopTasks,canReadSop} from './useSopTasks';
import type {Ctx} from './appCommon';
import './SopTasks.css';
import './Quotes.css';

function QuoteSopStart({c,projectId,onStart}:{c:Ctx;projectId:string;onStart:()=>void}) {
 const sop=useSopTasks(projectId,c.s.workspace_id||'',canReadSop(c.s.user));
 return <><p>資料時間：{sop.dataTime||'來源未提供'}</p>{sop.state.kind==='ready'&&sop.state.data.allowed.import?<Button onClick={onStart}>開始 SOP</Button>:null}</>;
}
function QuoteFields({q,pmName}:{q:Quote;pmName?:string}) {return <Section><Row label="報價編號" value={q.quote_no}/><Row label="工程編號" value={q.engineering_no||'未設定'}/><Row label="案件名稱" value={q.name}/><Row label="業主" value={q.client||'未設定'}/><Row label="報價日期" value={q.quoted_on||'未設定'}/><Row label="報價期限" value={q.quote_deadline||'未設定'}/><Row label="合約金額" value={amountLabel(q)}/><Row label="報價負責人" value={q.quote_owners.join('、')||'未指派'}/><Row label="PM" value={q.pm_names.join('、')||pmName||'未指派'}/><Row label="SOP 進度" value={!q.project_id?'未納入案件':q.sop_counts?`${q.sop_counts.done}/${q.sop_counts.total}`:'無任務'}/></Section>}
function LocalFlow({c,q}:{c:Ctx;q:Quote}) {
 const sop=useSopTasks(q.project_id||'',c.s.workspace_id||'',canReadSop(c.s.user));
 const [node,setNode]=useState<SopNodeKey>('sales'),[importing,setImporting]=useState<SopImportTarget>(null);
 return <><p>資料時間：{sop.dataTime||'來源未提供'}</p><div className="quote-stages" role="group" aria-label="SOP 節點">{SOP_NODES.map(([key,label])=><Button key={key} aria-pressed={node===key} onClick={()=>setNode(key)}>{label}</Button>)}</div><SopTasks c={c} p={{id:q.project_id!}} nodeKey={node} sop={sop} importing={importing} setImporting={setImporting}/></>;
}
function QuoteSheet({c,detail,onClose,onReload}:{c:Ctx;detail:QuoteDetail;onClose:()=>void;onReload:()=>Promise<void>}) {
 const q=detail.quote,[importing,setImporting]=useState(false),commit=useCaseWrite();
 const local=q.origin==='local';
 const openFlow=()=>{onClose();c.go(local?{view:'quotes',project:quoteKey(q),tab:'flow'}:{view:'project',project:q.project_id!,tab:'flow'})};
 return createPortal(<Sheet title={q.name} onClose={onClose}><div className="sop-import quote-detail-sheet"><div className="sop-badges"><Badge>{QUOTE_STAGES[q.stage]}</Badge>{local&&<Badge>本地規劃</Badge>}</div><QuoteFields q={q} pmName={c.w.users.find(u=>u.id===q.pm_id)?.name}/>
  <div className="sop-sheet-actions">{q.project_id&&<Button variant="primary" onClick={openFlow}>開啟流程</Button>}{q.project_id&&!q.sop_counts&&<QuoteSopStart c={c} projectId={q.project_id} onStart={()=>setImporting(true)}/>}</div>
  <details><summary>來源</summary><Section>{Object.entries(detail.facts).map(([key,value])=><Row key={key} label={key} value={typeof value==='object'?JSON.stringify(value):String(value??'未設定')}/>)}</Section></details>
  {importing&&q.project_id&&<SopImportSheet projectId={q.project_id} startNode="sales" onApplied={async()=>{await commit([{endpoint:`${c.s.workspace_id||''}:${q.project_id}:tasks`}]);await onReload()}} onClose={()=>setImporting(false)} onOpenImported={openFlow}/>}
 </div></Sheet>,document.body);
}

const EMPTY_QUOTES:Quote[]=[];
const COLUMNS = [
  ['name', '案件名稱', 'col-name'],
  ['contract_amount', '合約金額', 'col-amount'],
  ['stage', '階段', 'col-stage'],
  ['quote_owners', '負責人', 'col-owner'],
] as const;

export function Quotes({c}:{c:Ctx}) {return <DetailRefreshProvider scope={c.s.workspace_id||''} identityFingerprint={JSON.stringify([c.s.user?.id,c.s.user?.authz_version,c.s.user?.capabilities])}><QuotesContent key={JSON.stringify([c.s.workspace_id,c.s.user?.id,c.s.user?.role,c.s.user?.authz_version,c.s.user?.capabilities])} c={c}/></DetailRefreshProvider>}
function QuotesContent({c}:{c:Ctx}) {
 const [detailError,setError]=useState('');
 const [q,setQ]=useState(''),[stage,setStage]=useState(''),[sort,setSort]=useState<QuoteSort>('quote_no'),[dir,setDir]=useState(-1),[page,setPage]=useState(0),[size,setSize]=useState(25);
 const [detail,setDetail]=useState<QuoteDetail|null>(null),[creating,setCreating]=useState(false),[version,setVersion]=useState(0);
 const life=useRef({active:true,epoch:getSessionEpoch(),seq:0});
 const detailSeq=useRef(0);
 const detailRequest=useRef<AbortController>();
 useEffect(()=>{life.current.active=true;return()=>{life.current.active=false;detailRequest.current?.abort()}},[]);
 const current=useCallback(()=>life.current.active&&life.current.epoch===getSessionEpoch(),[]);
 const [refreshCause,setRefreshCause]=useState<'explicit_refresh'|'own_write_committed'>('explicit_refresh');
 const reload=(cause:'explicit_refresh'|'own_write_committed'='explicit_refresh')=>{setError('');setRefreshCause(cause);setVersion(v=>v+1)};
 const owner=usePageOwner({workspace:c.s.workspace_id||'',identityFingerprint:JSON.stringify([c.s.user?.id,c.s.user?.role,c.s.user?.authz_version,c.s.user?.capabilities]),openId:'quotes'});
 const result=usePageResource(owner,{endpoint:'/api/quotes'},version||c.reloadVersion?{reason:refreshCause,id:`${c.reloadVersion??0}:${version}`}:{reason:'initial_open'},async(signal,valid)=>{
  let rows:Quote[]=[],offset=0,total=1;
  while(offset<total){const p=await quoteApi.list(new URLSearchParams({limit:String(QUOTE_PAGE_SIZE),offset:String(offset)}).toString(),valid,signal);rows=rows.concat(p.items);total=p.total;if(!p.items.length)break;offset+=p.items.length}
  return {data:{items:rows,total},snapshotId:null,fetchedAt:null,verifiedAt:null,changedAt:null,completeness:rows.length<total?'partial':'complete',localRevision:null,empty:rows.length===0&&total===0,stale:false};
 });
 const denied=result.kind==='Denied';
 const value='value' in result?result.value:!denied&&'previous' in result?result.previous:undefined;
 const items=value?.data.items??EMPTY_QUOTES,loading=result.kind==='Loading';
 const error='error' in result?sopErrorText(result.error):detailError;
 const routeKey=c.route.project;
 useEffect(()=>{if(!routeKey)return;const controller=new AbortController();const valid=()=>!controller.signal.aborted&&current();void quoteApi.detail(routeKey,valid,controller.signal).then(d=>{if(valid())setDetail(d)}).catch(e=>{if(valid()){if(e instanceof SopError&&(e.status===401||e.status===403))setDetail(null);setError(sopErrorText(e))}});return()=>controller.abort()},[routeKey,version,c.reloadVersion,current]);
 const open=async(item:Quote)=>{detailRequest.current?.abort();const controller=new AbortController();detailRequest.current=controller;const seq=++detailSeq.current;const valid=()=>!controller.signal.aborted&&current()&&seq===detailSeq.current;setError('');try{const d=await quoteApi.detail(quoteKey(item),valid,controller.signal);if(valid())setDetail(d)}catch(e){if(valid()){if(e instanceof SopError&&(e.status===401||e.status===403))setDetail(null);setError(sopErrorText(e))}}};
 const searchable=useMemo(()=>items.map(item=>({item,text:`${item.quote_no} ${item.engineering_no||""} ${item.name} ${item.client}`.toLocaleLowerCase()})),[items]);
 const rows=useMemo(()=>{const query=q.toLocaleLowerCase();return sortQuotes(searchable.filter(({item,text})=>(!stage||item.stage===stage)&&text.includes(query)).map(({item})=>item),sort,dir)},[searchable,q,stage,sort,dir]);
 const pages=Math.max(1,Math.ceil(rows.length/size)),safePage=Math.min(page,pages-1);
 const changeSort=(key:QuoteSort)=>{if(sort===key)setDir(v=>-v);else{setSort(key);setDir(1)}setPage(0)};
 const canCreate=c.s.features?.local_case_creation===true&&c.s.user?.capabilities?.includes('create_local_case')===true;
 useEffect(()=>{if(denied){setDetail(null);setCreating(false);detailRequest.current?.abort()}},[denied]);
 const localFlow=!denied&&routeKey&&c.route.tab==='flow'&&detail?.quote.origin==='local'&&quoteKey(detail.quote)===routeKey;
 return <Page title={localFlow?detail.quote.name:'報價總表'} actions={<>{localFlow&&<Button onClick={()=>{setDetail(null);c.go({view:'quotes'})}}>報價總表</Button>}{canCreate&&<Button variant="primary" onClick={e=>{e.currentTarget.focus();setCreating(true)}}>建立報價</Button>}<Button onClick={()=>reload()}>重新讀取</Button></>}>
  {!localFlow&&!loading&&<p>資料時間：來源未提供</p>}
  {result.kind==='Stale'&&!error&&<DataState kind="Stale" title="保留上次讀取資料" body="正在重新讀取，下方保留上次快照；資料時間由來源提供。"/>}
  {error&&<DataState kind={denied?'Denied':items.length?'Stale':'Error'} title="報價暫時無法更新" body={error} actions={<Button onClick={()=>reload()}>重新讀取</Button>}/>}
  {localFlow?<><Badge>本地規劃</Badge><LocalFlow key={detail.quote.project_id} c={c} q={detail.quote}/></>:<div className="quote-register">
   <div className="table-toolbar"><label className="search-field"><Search size={15} className="search-icon" aria-hidden="true"/><input aria-label="搜尋報價" maxLength={240} placeholder="報價編號、工程編號、案件名稱、業主" value={q} onChange={e=>{setQ(e.target.value);setPage(0)}}/>{q&&<button type="button" className="search-clear" aria-label="清除搜尋" onClick={()=>{setQ('');setPage(0)}}>&times;</button>}</label><label className="quote-stage-filter">階段<FormSelect value={stage} onChange={e=>{setStage(e.target.value);setPage(0)}}><option value="">全部階段</option>{Object.entries(QUOTE_STAGES).map(([key,label])=><option key={key} value={key}>{label}</option>)}</FormSelect></label><label className="quote-sort">排序<FormSelect aria-label="報價排序" value={sort} onChange={e=>{setSort(e.target.value as QuoteSort);setPage(0)}}><option value="quote_no">報價編號</option><option value="name">案件名稱</option><option value="contract_amount">合約金額</option></FormSelect></label><Button aria-label="切換報價排序方向" onClick={()=>setDir(v=>-v)}>{dir===1?'升冪 ↑':'降冪 ↓'}</Button><span role="status">{loading?'正在載入報價…':`${rows.length} 筆`}</span></div>
   {value?.completeness==='partial'&&<DataState kind="Partial" title="報價清單不完整" body={`已載入 ${items.length} / ${value.data.total} 筆；搜尋僅涵蓋已載入項目。`}/>}
   {denied||error&&!items.length?null:loading&&!items.length?<DataState kind="Loading" title="正在載入報價" body="總筆數未知"/>:<div className="quote-table-card"><div className="table-scroll" tabIndex={0} aria-label="報價總表"><table className="data-table quote-table"><caption className="sr-only">報價總表，依目前篩選，每頁 {size} 筆</caption><thead><tr>{COLUMNS.map(([key,label,colClass])=>{const sortable=['quote_no','name','quoted_on','quote_deadline','contract_amount'].includes(key);return <th key={key} className={colClass} aria-sort={key===sort?(dir===1?'ascending':'descending'):undefined}>{sortable?<button onClick={()=>changeSort(key as QuoteSort)}>{label}{key===sort?(dir===1?' ↑':' ↓'):''}</button>:label}</th>})}</tr></thead><tbody>{rows.slice(safePage*size,(safePage+1)*size).map(item=><tr key={quoteKey(item)} className="clickable" onClick={()=>void open(item)}><td className="col-name"><button className="quote-name-button" onClick={e=>{e.stopPropagation();e.currentTarget.focus();void open(item)}}><small className="quote-code">{item.quote_no}</small><strong>{item.name}</strong><span className="quote-client">{item.client||'未設定'}</span></button>{item.origin==='local'&&<small>本地規劃</small>}</td><td className="col-amount">{amountLabel(item)}</td><td className="col-stage"><Badge>{QUOTE_STAGES[item.stage]}</Badge></td><td className="col-owner">{item.quote_owners.join('、')||'未指派'}</td></tr>)}</tbody></table></div>{!rows.length&&<DataState kind={value?.completeness==='partial'?'Partial':'Empty'} title={value?.completeness==='partial'?'已載入報價尚無符合項目':items.length?'沒有符合條件的報價':'目前沒有報價'} body="可調整搜尋或重新讀取。"/>}<div className="quote-pagination"><label>每頁<FormSelect value={size} onChange={e=>{setSize(Number(e.target.value));setPage(0)}}>{[10,25,50,100].map(n=><option key={n}>{n}</option>)}</FormSelect></label><Button disabled={!safePage} onClick={()=>setPage(safePage-1)}>上一頁</Button><span>第 {safePage+1} / {pages} 頁 · {rows.length} 筆</span><Button disabled={safePage+1>=pages} onClick={()=>setPage(safePage+1)}>下一頁</Button></div></div>}
  </div>}
  {detail&&!denied&&!localFlow&&<QuoteSheet key={quoteKey(detail.quote)} c={c} detail={detail} onReload={async()=>{reload('own_write_committed');await open(detail.quote)}} onClose={()=>{detailSeq.current++;setDetail(null);if(routeKey)c.go({view:'quotes'})}}/>}
  {creating&&<QuoteCreateSheet users={c.w.users} canImport={c.s.features?.sop_task_writes===true&&(c.s.user?.role==='manager'||c.s.user?.capabilities?.includes('sop_task_import')===true)} onClose={()=>setCreating(false)} onCreated={()=>reload('own_write_committed')} onOpen={ref=>{setCreating(false);c.go({view:'quotes',project:ref,tab:'flow'})}}/>}
 </Page>;
}
