import {useCallback,useEffect,useState} from 'react';
import {Badge,Button,Section} from './design';
import {api,ApiError} from './api';
import {FIELDS,MOCK_NOTICE,OpsState,OpsValue,STATES,reasonText,valueText} from './opsSyncView';
import './ops-sync.css';

export type Command={command_id:string;entity_id:string;field_id:string;state:OpsState;reason?:string|null;actor:string;expected:OpsValue;expected_revision:number;intended:OpsValue;attempts:number;reconcile?:{phase:string;reads:number;blocker?:string|null}|null};
type Conflict={conflict_id:string;command_id:string;entity_id:string;field_id:string;reason:string;open:boolean;expected:OpsValue&{revision:number};current:OpsValue&{revision:number};intended:OpsValue;resolution?:string|null};
type Status={notice:string;live:boolean;commands:Command[];conflicts:Conflict[]};
const wire=(v:OpsValue)=>v.kind==='set'?{t:'set',v:v.value}:{t:'clear'};
const BINDING='mock-binding-v1';

// Flag OFF => the server has no such route (404) and this renders nothing.
export function OpsSyncPanel({onRetry}:{onRetry?:(c:Command)=>void}={}){
 const[status,setStatus]=useState<Status|null>(null);const[hidden,setHidden]=useState(false);const[error,setError]=useState('');const[busy,setBusy]=useState('');
 const[intent,setIntent]=useState<{conflict:string;mode:'keep_current'|'apply_intended'}|null>(null);
 const load=useCallback(async(keepError=false)=>{try{setStatus(await api<Status>('/api/ops-sync/status'));if(!keepError)setError('')}catch(e){if(e instanceof ApiError&&e.status===404)setHidden(true);else setError((e as Error).message)}},[]);
 useEffect(()=>{void load()},[load]);
 // A 409 means the data moved under the user. Reload the latest state but keep what they chose on screen (`intent`) and
 // never resubmit it on their behalf: they confirm against the fresh values and press again.
 const act=async(key:string,url:string,body:unknown)=>{setBusy(key);setError('');try{setStatus(await api<Status>(url,{method:'POST',body:JSON.stringify(body)}));setIntent(null)}catch(e){
   if(e instanceof ApiError&&e.status===409){setError('資料在您操作期間已被更新，已重新載入最新內容。您的選擇尚未送出，請核對後再按一次。');await load(true)}else setError((e as Error).message)}finally{setBusy('')}};
 if(hidden)return null;
 const conflictOf=(c:Command)=>status?.conflicts.find(x=>x.command_id===c.command_id);
 const resolve=(k:Conflict,mode:'keep_current'|'apply_intended')=>{setIntent({conflict:k.conflict_id,mode});return act(k.conflict_id+mode,`/api/ops-sync/conflicts/${encodeURIComponent(k.conflict_id)}/resolve`,
  {command_id:`${k.command_id}:resolve:${crypto.randomUUID()}`,resolution:mode,expected:wire(k.current),expected_revision:k.current.revision,intended:wire(mode==='keep_current'?k.current:k.intended),schema_binding_version:BINDING})};
 return <section aria-label="營運同步（本機模擬）" className="owned-view ops-sync">
  <div className="section-heading"><div><h2>營運同步狀態（本機模擬）</h2><p role="note" className="ops-sync-notice">{status?.notice||MOCK_NOTICE}</p></div><Button disabled={!!busy} onClick={()=>void load()}>重新整理</Button></div>
  {error&&<p role="alert" className="owned-alert">操作未完成：{error}</p>}
  {!status&&!error&&<p role="status">讀取中…</p>}
  {status&&!status.commands.length&&<p>目前沒有進行中的申請。</p>}
  {status&&<Section>{status.commands.map(c=>{const meta=STATES[c.state];const k=conflictOf(c);return <article key={c.command_id} className="ops-sync-item" data-state={c.state} aria-label={`${FIELDS[c.field_id]||c.field_id}：${meta.label}`}>
   <header><strong>{FIELDS[c.field_id]||c.field_id}</strong><span className="ops-sync-entity">{c.entity_id}</span><Badge tone={meta.tone}>{meta.label}</Badge></header>
   <p>{meta.detail}</p>
   <dl className="ops-sync-values"><div><dt>申請變更為</dt><dd>{valueText(c.intended)}</dd></div>{c.state!=='conflict'&&<div><dt>送出時基準</dt><dd>{valueText(c.expected)}（版本 {c.expected_revision}）</dd></div>}</dl>
   {c.reason&&c.reason!=='awaiting_approval'&&<p className="ops-sync-reason">原因：{reasonText(c.reason)}</p>}
   {c.state==='unknown'&&<><p className="ops-sync-reason">核對進度：{c.reconcile?.phase==='exhausted'?'自動讀回次數已用完，需手動重新核對':'等待下一次讀回'}（已讀回 {c.reconcile?.reads??0} 次）</p>
    <Button disabled={!!busy} onClick={()=>void act(c.command_id,'/api/ops-sync/reconcile',{command_id:c.command_id})}>{busy===c.command_id?'核對中…':'立即重新核對'}</Button></>}
   {c.state==='failed'&&onRetry&&<Button disabled={!!busy} onClick={()=>onRetry(c)}>以相同內容重新送出（新申請）</Button>}
   {c.state==='conflict'&&k&&<>
    <dl className="ops-sync-values" aria-label="衝突內容"><div><dt>預期（送出時）</dt><dd>{valueText(k.expected)}（版本 {k.expected.revision}）</dd></div><div><dt>目前</dt><dd>{valueText(k.current)}（版本 {k.current.revision}）</dd></div><div><dt>擬變更</dt><dd>{valueText(k.intended)}</dd></div></dl>
    {intent&&intent.conflict===k.conflict_id&&error&&<p role="note" className="ops-sync-intent" data-intent={intent.mode}>您剛才選擇：{intent.mode==='keep_current'?'保留目前值':'套用擬變更值'}（尚未送出，請核對上方最新內容後再按一次）</p>}
    {k.open?(k.current.kind==='unknown'?<p role="note">目前值無法讀取，暫不能處理此衝突。</p>:<div className="inline-actions"><Button disabled={!!busy} onClick={()=>void resolve(k,'keep_current')}>保留目前值</Button><Button variant="primary" disabled={!!busy} onClick={()=>void resolve(k,'apply_intended')}>套用擬變更值</Button></div>):<p>已處理：{k.resolution==='keep_current'?'保留目前值':'套用擬變更值'}</p>}</>}
  </article>})}</Section>}
 </section>;
}
