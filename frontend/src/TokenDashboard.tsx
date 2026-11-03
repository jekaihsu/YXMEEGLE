import {useEffect,useRef,useState} from 'react';
import {api,ApiError,getSessionEpoch} from './api';
import {usePageOwner,type FetchIntent} from './pageData';
import {usePageResource} from './viewData';
import {DataState,Button} from './design';
import {TableLoadingSkeleton} from './DetailLoadingSkeleton';
import {contentText,toolLabel,exportUrl,type Exchange,scopeLabel,formatPercent,satisfaction,reasonLabels,reasonSeries,sortProviders,rangeError,chartSeries,filterQuery,formatCost,formatNumber,formatReadTime,formatTime,presetRange,readFilters,sortPeople,type Filters,type Usage,type SortKey,type DayUsage} from './tokenDashboardModel';
import './TokenDashboard.css';

let usageOpen=0;
const providerName=(provider:string)=>provider==='claude'?'Claude':provider==='gpt'?'GPT':provider;
const sortColumns:[SortKey,string][]=[['name','同事'],['questions','提問數'],['input_tokens','輸入 tokens'],['output_tokens','輸出 tokens'],['cost_usd','費用 USD'],['up','👍 按讚'],['down','👎 倒讚'],['last_at','最近提問（台北）']];
export default function TokenDashboard(){
 const heading=useRef<HTMLHeadingElement>(null);
 useEffect(()=>{const previous=document.title;document.title='AI 助理用量｜詠翔工作台';heading.current?.focus();return()=>{document.title=previous}},[]);
 const errorRegion=useRef<HTMLElement>(null);
 const [filters,setFilters]=useState<Filters>(()=>readFilters(location.search));
 const [search,setSearch]=useState(()=>readFilters(location.search).q);
 const [selected,setSelected]=useState<string>();
 const [exportState,setExportState]=useState('');
 const [people,setPeople]=useState<Usage['people']>([]);
 const [retry,setRetry]=useState(0);
 const [openedAt]=useState(()=>new Date());
 const [openId]=useState(()=>`usage:${++usageOpen}`);
 const [sort,setSort]=useState<{key:SortKey;direction:'asc'|'desc'}>({key:'cost_usd',direction:'desc'});
 const [providerSort,setProviderSort]=useState<{key:'up'|'down';direction:'asc'|'desc'}>({key:'down',direction:'desc'});
 const query=filterQuery(filters),invalid=rangeError(filters);
 useEffect(()=>{const pop=()=>{const next=readFilters(location.search);setFilters(next);setSearch(next.q);setSelected(undefined)};window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop)},[]);
 useEffect(()=>{history.replaceState(null,'',location.pathname+'?'+query)},[query]);
 const owner=usePageOwner({workspace:'ai-usage',identityFingerprint:openId,openId:`${openId}:${query}`});
 const initialQuery=useRef({query,initial:true});
 if(initialQuery.current.query!==query)initialQuery.current={query,initial:false};
 useEffect(()=>{setExportState('')},[owner]);
 const resource={endpoint:'/api/ai/usage',query:{query}};
 const [refreshIntent,setRefreshIntent]=useState({query:'',id:''});
 const intent:FetchIntent=refreshIntent.query===query?{reason:'explicit_refresh',id:refreshIntent.id}:{reason:initialQuery.current.initial?'initial_open':'user_query_change'};
 const result=usePageResource<Usage>(owner,resource,intent,async(signal,current)=>{
  if(invalid)throw new Error(invalid);
  const raw=await api<Usage>('/api/ai/usage?'+query,{signal,headers:{'X-YX-Fetch-Intent':intent.reason}},current);
  const complete=['questions','input_tokens','output_tokens','cost_usd','unpriced_calls'].every(key=>typeof (raw.totals as unknown as Record<string,unknown>)?.[key]==='number')&&['people','by_day','by_person','by_provider','recent'].every(key=>Array.isArray((raw as unknown as Record<string,unknown>)[key]));
  const data={...raw,range:raw.range||{from:filters.from,to:filters.to},totals:raw.totals||{},people:raw.people||[],by_day:raw.by_day||[],by_person:raw.by_person||[],by_provider:raw.by_provider||[],recent:raw.recent||[]} as Usage;
  return {data,snapshotId:null,fetchedAt:new Date().toISOString(),verifiedAt:null,changedAt:null,completeness:complete?'complete':'unknown',localRevision:null,empty:complete&&data.totals.questions===0,stale:false};
 });
 useEffect(()=>{if(result.kind==='Denied')owner.close()},[owner,result.kind]);
 const denied=result.kind==='Denied'||result.kind==='Closed';
 const value=!denied?('value' in result?result.value:'previous' in result?result.previous:undefined):undefined;
 const data=invalid?undefined:value?.data;
 const pending=result.kind==='Loading'||result.kind==='Stale';
 const failure=result.kind==='Error';
 const focusError=invalid||denied||failure&&!data;
 useEffect(()=>{if(focusError)errorRegion.current?.focus()},[focusError]);
 const refresh=()=>{setRetry(n=>n+1);setRefreshIntent({query,id:`${openId}:${retry+1}`})};
 const unknown=!!data&&(value?.completeness!=='complete'||[data.totals.questions,data.totals.input_tokens,data.totals.output_tokens,data.totals.cost_usd,data.totals.unpriced_calls].some(n=>typeof n!=='number'||!Number.isFinite(n)));
 const exportDisabled=!!invalid||pending||failure||denied||!data||unknown||!data.totals.feedback;
 useEffect(()=>{if(data)setPeople(data.people);if(denied){setPeople([]);setSelected(undefined)}},[data,denied]);
 const update=(next:Partial<Filters>)=>{const value={...filters,...next};setSelected(undefined);setFilters(value);history.pushState(null,'',location.pathname+'?'+filterQuery(value))};
 useEffect(()=>{if(search===filters.q)return;const timer=setTimeout(()=>{setSelected(undefined);setFilters(current=>({...current,q:search}));},300);return()=>clearTimeout(timer)},[search,filters.q]);
 const download=async()=>{if(exportDisabled)return;const epoch=getSessionEpoch();const current=()=>epoch===getSessionEpoch()&&owner.state(resource).kind!=='Closed';setExportState('正在匯出…');try{const response=await fetch(exportUrl(filters),{credentials:'same-origin'});if(response.status===401||response.status===403){owner.close();setSelected(undefined);if(response.status===401)window.dispatchEvent(new Event('yx:session-expired'));throw new Error('403 · 無權查看')}if(!response.ok)throw new Error('匯出失敗，請重試。');const blob=await response.blob();if(!current())return;const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=`ai-usage-${filters.from}-${filters.to}.jsonl`;link.click();setTimeout(()=>URL.revokeObjectURL(url),0);setExportState('匯出完成');}catch(error){if(current())setExportState((error as Error).message)}};
 const feedback=data?.totals.feedback;
 const reasons=reasonSeries(data?.reasons,feedback?.down);
 return <main className="token-dashboard">
  <div className="td-heading"><div><h1 ref={heading} tabIndex={-1}>AI 助理用量</h1><p>查看同事的提問與 token 費用。時間以台北時區顯示。</p><p>資料時間：來源未提供{value?.fetchedAt&&` · 讀取時間：${formatReadTime(value.fetchedAt)}`}</p></div><span className="td-private">僅主管可見</span></div>
  <div className="td-actions"><Button variant="primary" disabled={pending||!!invalid||denied} onClick={refresh}>重新讀取</Button><Button disabled={exportDisabled||exportState==='正在匯出…'} onClick={()=>void download()}>匯出 JSONL</Button><span role="status">{exportState}</span></div>
  <section className="td-filters" aria-label="用量篩選">
   <div className="td-presets" aria-label="日期捷徑">{([['today','今天'],['week','近 7 天'],['month','近 30 天'],['thisMonth','本月']] as const).map(([key,label])=>{const range=presetRange(key,openedAt);return <button key={key} aria-pressed={filters.from===range.from&&filters.to===range.to} onClick={()=>update(range)}>{label}</button>})}</div>
   <details className="td-more"><summary>更多篩選</summary><div className="td-filter-fields"><label>開始日期<input type="date" value={filters.from} onChange={e=>e.target.value&&update({from:e.target.value})}/></label><label>結束日期<input type="date" value={filters.to} onChange={e=>e.target.value&&update({to:e.target.value})}/></label><label>提問同事<select value={filters.actor} onChange={e=>update({actor:e.target.value})}><option value="">全部同事</option>{(denied?[]:people).map(person=><option key={person.actor_id} value={person.actor_id}>{person.name}</option>)}{filters.actor&&!(denied?[]:people).some(person=>person.actor_id===filters.actor)&&<option value={filters.actor}>已選取同事</option>}</select></label><label>供應商<select value={filters.provider} onChange={e=>update({provider:e.target.value as Filters['provider']})}><option value="">全部</option><option value="claude">Claude</option><option value="gpt">GPT</option></select></label><label>評分<select value={filters.rating} onChange={e=>update({rating:e.target.value as Filters['rating']})}><option value="">全部</option><option value="down">只看倒讚</option><option value="up">只看按讚</option><option value="none">未評分</option></select></label><label>範圍<select value={filters.scope} onChange={e=>update({scope:e.target.value as Filters['scope']})}><option value="">全部</option><option value="global">全域</option><option value="project">案件</option></select></label></div>
   <div className="td-review-controls"><label>搜尋問題／回答<input type="search" maxLength={200} value={search} onChange={e=>setSearch(e.target.value)}/></label><button aria-pressed={filters.rating==='down'} onClick={()=>update({rating:filters.rating==='down'?'':'down'})}>只看倒讚</button></div></details>
  </section>
  <section ref={errorRegion} tabIndex={-1} aria-label="用量資料">
  {invalid?<DataState kind="Error" title="請確認日期範圍" body={invalid}/>:denied?<DataState kind="Denied" title="403 · 無權查看" body="AI 用量儀表板僅限主管查看。" actions={<a className="ds-button" href="/">回到工作台</a>}/>:<>
   {pending&&!data&&<TableLoadingSkeleton label="正在讀取用量…"/>}
   {failure&&<DataState kind={data?'Stale':'Error'} title={data?'保留上次用量 · 資料待更新':'用量讀取失敗'} body={<p>{'error' in result&&result.error instanceof Error?result.error.message:'請重新讀取。'}{data&&` · 讀取時間：${value?.fetchedAt?formatReadTime(value.fetchedAt):'尚未取得'}`}</p>} actions={<Button onClick={refresh}>重新嘗試</Button>}/>}
   {pending&&data&&<DataState kind="Stale" title="正在重新讀取用量" body="目前保留上次讀取的資料。"/>}
   {data&&<>
   {(unknown||!data.totals.feedback)&&<DataState kind="Partial" title="部分用量尚未取得" body="已知費用不代表完整費用；未取得的數字以「待確認」顯示。"/>}
   <section className="td-kpis" aria-label="用量摘要">{[['提問數',formatNumber(data.totals.questions)],['輸入 tokens',formatNumber(data.totals.input_tokens)],['輸出 tokens',formatNumber(data.totals.output_tokens)],['費用 USD',data.totals.cost_usd==null?'待確認':formatCost(data.totals.cost_usd)]].map(([label,value])=><article key={label}><span>{label}</span><strong>{value}</strong></article>)}<article className="td-satisfaction"><span>滿意度</span><strong>{feedback?formatPercent(feedback.rated?feedback.up_rate:null):'待確認'}</strong><small>👍 {formatNumber(feedback?.up)} / 👎 {formatNumber(feedback?.down)} · 已評分 {formatNumber(feedback?.rated)} 次</small></article></section>
   {data.totals.unpriced_calls>0&&<p className="td-unpriced" role="note"><strong>未計價 {formatNumber(data.totals.unpriced_calls)} 次</strong>　這些提問尚無單價，已排除於費用總額之外。已知費用不代表完整費用。</p>}
   {data.totals.questions===0&&!unknown?<DataState kind="Empty" title="這段期間尚無提問" body="試著調整日期、同事、供應商或評分篩選。"/>:unknown?<DataState kind="Partial" title="完整結果尚未確認" body="請重新讀取後再判斷是否沒有提問。"/>:<>
    <section className="td-panel"><div className="td-section-title"><h2>{(Date.parse(data.range.to)-Date.parse(data.range.from))/86400000+1>62?'每週提問':'每日提問'}</h2><span>{data.range.from} 至 {data.range.to}</span></div><p>僅彙整來源提供的紀錄；缺少的日期不視為零。</p><DailyChart rows={chartSeries(data.by_day,data.range)} weekly={(Date.parse(data.range.to)-Date.parse(data.range.from))/86400000+1>62}/></section>
    <section className="td-panel"><div className="td-section-title"><h2>同事用量</h2><span>點選姓名可篩選同事</span></div><div className="td-scroll" tabIndex={0} role="region" aria-label="同事用量表，可左右捲動"><table><caption className="sr-only">用量統計</caption><thead><tr>{sortColumns.map(([key,label])=><th key={key} aria-sort={sort.key===key?(sort.direction==='desc'?'descending':'ascending'):'none'}><button onClick={()=>setSort({key,direction:sort.key===key&&sort.direction==='desc'?'asc':'desc'})}>{label} {sort.key===key?(sort.direction==='desc'?'↓':'↑'):''}</button></th>)}</tr></thead><tbody>{sortPeople(data.by_person,sort.key,sort.direction).map(person=><tr key={person.actor_id}><td><button className="td-person" onClick={()=>update({actor:person.actor_id})}>{person.name}</button></td><td>{formatNumber(person.questions)}</td><td>{formatNumber(person.input_tokens)}</td><td>{formatNumber(person.output_tokens)}</td><td>{person.cost_usd==null?'待確認':formatCost(person.cost_usd)}{(person.unpriced_calls??0)>0&&<small> · 未計價 {formatNumber(person.unpriced_calls??0)} 次</small>}</td><td>{formatNumber(person.up)}</td><td>{formatNumber(person.down)}</td><td>{formatTime(person.last_at)}</td></tr>)}</tbody></table></div></section>
    <section className="td-panel"><h2>供應商分布</h2><div className="td-providers">{data.by_provider.map(row=><article key={row.provider}><div><strong>{providerName(row.provider)}</strong><span>{formatNumber(row.questions)} 次提問 · {formatCost(row.cost_usd)}{(row.unpriced_calls??0)>0&&` · 未計價 ${formatNumber(row.unpriced_calls??0)} 次`}</span></div><meter min={0} max={Math.max(1,data.totals.questions)} value={row.questions} aria-label={`${providerName(row.provider)} 提問佔比`}/><p className="td-provider-feedback"><strong>{satisfaction(row)}</strong><span>👍 {formatNumber(row.up)} / 👎 {formatNumber(row.down)}</span></p><small>輸入 {formatNumber(row.input_tokens)} / 輸出 {formatNumber(row.output_tokens)} tokens</small></article>)}</div><div className="td-scroll" tabIndex={0} role="region" aria-label="供應商評分表，可左右捲動"><table><caption className="sr-only">用量統計</caption><thead><tr><th>供應商</th><th>滿意度</th>{(['up','down'] as const).map(key=><th key={key} aria-sort={providerSort.key===key?(providerSort.direction==='desc'?'descending':'ascending'):'none'}><button onClick={()=>setProviderSort({key,direction:providerSort.key===key&&providerSort.direction==='desc'?'asc':'desc'})}>{key==='up'?'👍 按讚':'👎 倒讚'} {providerSort.key===key?(providerSort.direction==='desc'?'↓':'↑'):''}</button></th>)}</tr></thead><tbody>{sortProviders(data.by_provider,providerSort.key,providerSort.direction).map(row=><tr key={row.provider}><td>{providerName(row.provider)}</td><td>{satisfaction(row)}</td><td>{formatNumber(row.up)}</td><td>{formatNumber(row.down)}</td></tr>)}</tbody></table></div></section>
    {(feedback?.down??0)>0&&<section className="td-panel td-reasons"><div className="td-section-title"><h2>倒讚原因</h2><span>含未填寫原因的倒讚</span></div><ul aria-label="倒讚原因分布">{reasons.map(row=><li key={row.key}><span>{row.label}</span><span className="td-reason-track" aria-hidden="true"><span style={{width:`${(row.value??0)/Math.max(1,...reasons.map(item=>item.value??0))*100}%`}}/></span><strong>{formatNumber(row.value)} 次</strong></li>)}</ul></section>}
    <section className="td-panel"><div className="td-section-title"><h2>最近提問</h2><span>最近 {data.recent.length} 筆，最多 50 筆</span></div><div className="td-scroll td-recent-scroll" tabIndex={0} role="region" aria-label="最近提問表，可左右捲動"><table className="td-recent"><caption className="sr-only">最近提問</caption><thead><tr>{['時間（台北）','同事','供應商','範圍','評分','問題','回答','工具','輸入 tokens','輸出 tokens','費用 USD','耗時','狀態','詳情'].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{data.recent.map((call,index)=><tr key={`${call.created_at}-${index}`}><td>{formatTime(call.created_at)}</td><td>{call.name}</td><td>{providerName(call.provider)}</td><td>{scopeLabel(call.scope)}</td><td><span role="img" aria-label={call.rating==='up'?'按讚':call.rating==='down'?'倒讚':'未評分'}>{call.rating==='up'?'👍':call.rating==='down'?'👎':'未評分'}</span>{call.rating==='down'&&call.reason&&<small className="td-reason-label">{reasonLabels[call.reason]}</small>}</td><td><span className="td-preview">{contentText(call.question_preview)}</span></td><td><span className="td-preview">{contentText(call.answer_preview)}</span></td><td>{call.tools?.map(toolLabel).join("、")||"—"}</td><td>{formatNumber(call.input_tokens)}</td><td>{formatNumber(call.output_tokens)}</td><td>{formatCost(call.cost_usd)}</td><td>{(call.latency_ms/1000).toFixed(1)} 秒</td><td><span className={`td-status td-status-${call.status}`}>{statusLabel(call.status)}</span>{call.status==='error'&&call.error_detail&&<small className="td-error-detail">{call.error_detail}</small>}</td><td>{call.usage_id?<button className="td-person" onClick={()=>setSelected(call.usage_id)} aria-label={`開啟 ${call.name} 的提問詳情`}>開啟</button>:'—'}</td></tr>)}</tbody></table></div><ul className="td-recent-mobile" aria-label="最近提問紀錄">{data.recent.map((call,index)=><li key={call.usage_id||index}>
     <div className="td-record-heading"><strong>{call.name}</strong><span>{formatTime(call.created_at)}</span></div>
     <p>{providerName(call.provider)} · {scopeLabel(call.scope)} · {call.rating==='up'?'按讚':call.rating==='down'?'倒讚':'未評分'}</p>
     <span className="td-status">{statusLabel(call.status)}</span>
     <details><summary>查看提問摘要</summary><dl>{[['問題',contentText(call.question_preview)],['回答',contentText(call.answer_preview)],['工具',call.tools?.map(toolLabel).join('、')||'—'],['輸入 tokens',formatNumber(call.input_tokens)],['輸出 tokens',formatNumber(call.output_tokens)],['費用 USD',formatCost(call.cost_usd)],['耗時',Number.isFinite(call.latency_ms)?`${(call.latency_ms/1000).toFixed(1)} 秒`:'待確認'],['原因',call.reason?reasonLabels[call.reason]:'—']].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>{call.error_detail&&<p>{call.error_detail}</p>}</details>
     {call.usage_id&&<button className="td-person" onClick={()=>setSelected(call.usage_id)} aria-label={`開啟 ${call.name} 的提問詳情`}>開啟提問詳情</button>}
    </li>)}</ul></section>
   </>}
  </>}
  </>}
 </section>
 {selected&&data&&<ExchangeDialog id={selected} rows={data.recent} onSelect={setSelected} onClose={()=>setSelected(undefined)} onDenied={()=>owner.close()}/>}
 </main>;
}
const statusLabel=(status:string)=>({ok:'完成',error:'失敗',aborted:'已中止'} as Record<string,string>)[status]||status;
function ExchangeDialog({id,rows,onSelect,onClose,onDenied}:{id:string;rows:Usage['recent'];onSelect:(id:string)=>void;onClose:()=>void;onDenied:()=>void}){
 const dialog=useRef<HTMLDivElement>(null);
 const [state,setState]=useState<{kind:'loading'}|{kind:'error';message:string}|{kind:'ready';data:Exchange}>({kind:'loading'});
 const [copied,setCopied]=useState('');
 const [retry,setRetry]=useState(0);
 const ids=rows.flatMap(row=>row.usage_id?[row.usage_id]:[]),index=ids.indexOf(id);
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.querySelector<HTMLButtonElement>('button')?.focus();const overflow=document.body.style.overflow;document.body.style.overflow='hidden';return()=>{document.body.style.overflow=overflow;previous?.focus()}},[]);
 useEffect(()=>{const controller=new AbortController();setState({kind:'loading'});setCopied('');api<Exchange>('/api/ai/usage/'+encodeURIComponent(id)+'/exchange',{signal:controller.signal},()=>!controller.signal.aborted).then(data=>{if(!controller.signal.aborted)setState({kind:'ready',data})}).catch(error=>{if(error instanceof ApiError&&[401,403].includes(error.status)){onDenied();return}if(!controller.signal.aborted)setState({kind:'error',message:error instanceof ApiError&&error.status===404?'找不到這筆提問。':error instanceof ApiError&&error.status===403?'403 · 無權查看': '詳情讀取失敗，請重試。'})});return()=>controller.abort()},[id,retry]);
 const copy=async(label:string,value:string)=>{try{await navigator.clipboard.writeText(value);setCopied(`已複製${label}`)}catch{setCopied('複製失敗，請選取文字複製。')}};
 const data=state.kind==='ready'?state.data:undefined;
 return <div className="td-dialog-backdrop"><div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="td-exchange-title" className="td-dialog" onKeyDown={event=>{
  if(event.key==='Escape'){event.preventDefault();onClose()}
  if(event.key==='Tab'){const buttons=[...dialog.current!.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];const first=buttons[0],last=buttons.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}
 }}>
  <header><h2 id="td-exchange-title">提問詳情</h2><button onClick={onClose}>關閉</button></header>
  <nav aria-label="瀏覽提問"><button disabled={index<=0} onClick={()=>onSelect(ids[index-1])}>上一筆</button><span>{index+1} / {ids.length}</span><button disabled={index<0||index>=ids.length-1} onClick={()=>onSelect(ids[index+1])}>下一筆</button></nav>
  {state.kind==='loading'?<p role="status">正在讀取詳情…</p>:state.kind==='error'?<div role="alert"><p>{state.message}</p><button onClick={()=>setRetry(n=>n+1)}>重新嘗試</button></div>:data&&<>
   <dl className="td-exchange-meta">{[['同事',data.name],['時間（台北）',formatTime(data.created_at)],['供應商',providerName(data.provider)],['範圍',scopeLabel(data.scope)],['案件 ID',data.project_id||'—'],['狀態',statusLabel(data.status)],['耗時',`${(data.latency_ms/1000).toFixed(1)} 秒`],['輸入 / 輸出 tokens',`${formatNumber(data.input_tokens)} / ${formatNumber(data.output_tokens)}`],['費用 USD',formatCost(data.cost_usd)],['評分',data.rating==='up'?'按讚':data.rating==='down'?'倒讚':'未評分'],['原因',data.reason?reasonLabels[data.reason]:'—'],['工具',data.tools?.map(toolLabel).join('、')||'—']].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
   {data.error_detail&&<p className="td-exchange-error">{data.error_detail}</p>}
   {(['question','answer'] as const).map(key=><section key={key} className="td-exchange-content"><div><h3>{key==='question'?'問題':'回答'}</h3><button disabled={data[key]==null} onClick={()=>void copy(key==='question'?'問題':'回答',data[key]!)} aria-label={`複製${key==='question'?'問題':'回答'}`}>複製</button></div><p>{contentText(data[key]??null)}</p></section>)}
   <p role="status">{copied}</p>
  </>}
 </div></div>;
}
function DailyChart({rows,weekly}:{rows:DayUsage[];weekly:boolean}){
 const period=weekly?'每週':'每日';
 const [active,setActive]=useState<DayUsage>();const max=Math.max(1,...rows.map(row=>row.questions));const top=Math.ceil(max/4)*4;const width=850,height=230,left=52,bottom=190,plotWidth=780;
 return <><p className="td-scroll-hint">圖表與表格可左右捲動，查看完整數據。</p><div className="td-chart"><svg viewBox={`0 0 ${width} ${height}`} role="group" aria-labelledby="td-chart-title td-chart-desc"><title id="td-chart-title">{period}提問數長條圖</title><desc id="td-chart-desc">橫軸為日期，縱軸為提問數。菱形標記代表倒讚次數，與提問數使用相同刻度。可聚焦各長條查看數值，下方提供資料表。</desc>{[0,1,2,3,4].map(tick=><g key={tick}><line x1={left} y1={bottom-tick*40} x2={width-18} y2={bottom-tick*40}/><text x={left-9} y={bottom-tick*40+4} textAnchor="end">{formatNumber(top*tick/4)}</text></g>)}<text x={left} y={15}>長條 提問數 · ◆ 倒讚數</text>{rows.map((row,index)=>{const step=plotWidth/rows.length,h=row.questions/top*160;return <g key={row.day}><rect tabIndex={0} role="img" aria-label={`${row.day}，${row.questions} 次提問，${formatNumber(row.up)} 次按讚，${formatNumber(row.down)} 次倒讚，${formatCost(row.cost_usd)}`} x={left+index*step+step*.15} y={bottom-Math.max(h,2)} width={step*.7} height={Math.max(h,2)} onMouseEnter={()=>setActive(row)} onMouseLeave={()=>setActive(undefined)} onFocus={()=>setActive(row)} onBlur={()=>setActive(undefined)}><title>{row.day} · {formatNumber(row.questions)} 次提問 · 👎 {formatNumber(row.down)} 次倒讚 · {formatCost(row.cost_usd)}</title></rect>{(row.down??0)>0&&<path className="td-dislike-marker" aria-hidden="true" d={`M ${left+index*step+step/2} ${bottom-(row.down??0)/top*160-5} l 5 5 l -5 5 l -5 -5 Z`}/>}{(index===0||index===rows.length-1||index%Math.ceil(rows.length/6)===0)&&<text x={left+index*step+step/2} y={bottom+22} textAnchor="middle">{row.day.slice(5)}</text>}</g>})}<text x={width-18} y={height-2} textAnchor="end">日期</text></svg></div><p className="td-chart-tooltip" role="status">{active?`${active.day} · ${formatNumber(active.questions)} 次提問 · 👍 ${formatNumber(active.up)} 次按讚 · 👎 ${formatNumber(active.down)} 次倒讚 · ${formatCost(active.cost_usd)}`:`滑過或使用 Tab 聚焦長條，查看${period}用量。`}</p><details><summary>查看{period}數據表</summary><div className="td-scroll" tabIndex={0} role="region" aria-label={`${period}用量表，可左右捲動`}><table><caption className="sr-only">用量統計</caption><thead><tr><th>{weekly?'週起日':'日期'}</th><th>提問數</th><th>👍 按讚</th><th>👎 倒讚</th><th>輸入 tokens</th><th>輸出 tokens</th><th>費用 USD</th></tr></thead><tbody>{rows.map(row=><tr key={row.day}><td>{row.day}</td><td>{formatNumber(row.questions)}</td><td>{formatNumber(row.up)}</td><td>{formatNumber(row.down)}</td><td>{formatNumber(row.input_tokens)}</td><td>{formatNumber(row.output_tokens)}</td><td>{formatCost(row.cost_usd)}</td></tr>)}</tbody></table></div></details></>;
}
