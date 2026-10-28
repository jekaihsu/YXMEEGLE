import {Select as FormSelect} from './design/Select';
import {useCallback,useEffect,useState} from 'react';
import {Badge,Button,Section} from './design';
import {api,ApiError} from './api';
import {OpsState,STATES,MOCK_NOTICE,FIELDS,reasonText,valueText} from './opsSyncView';
import {Denial,DECISION_RESULT,DEADLINE_LABEL,Draft,Entity,MAPPING_BADGE,MOCK_DECISION_NOTE,MOCK_OUTCOME_LABEL,PROPOSAL_STATE,Person,SEAT_LABEL,deliverySentence,edited,emptyDraft,entityTitle,personLabel,withIdentity} from './opsFlowView';
import {Command,OpsSyncPanel} from './OpsSyncPanel';
import './ops-sync.css';

type Cmd={command_id:string;entity_id:string;state:OpsState;reason?:string|null;field_id:string};
type Flow={notice:string;mapping_notice:string;roster:Person[];entities:Entity[];mock_outcomes:string[];dispatch_denial:Denial;commands:Cmd[];outcome?:{status:string;reason?:string|null;reason_text?:string;duplicate:boolean;decision?:string};command?:Cmd|null};
const KEY='ops-flow-drafts';
const load=():Record<string,Draft>=>{try{return JSON.parse(sessionStorage.getItem(KEY)||'{}')}catch{return{}}};
const uuid=()=>crypto.randomUUID();const now=()=>new Date().toISOString();

// Synthetic, flag-gated vertical flow. Flag OFF => the server has no such route (404) and this renders nothing.
export function OpsFlowPanel(){
 const[flow,setFlow]=useState<Flow|null>(null);const[hidden,setHidden]=useState(false);const[error,setError]=useState('');const[busy,setBusy]=useState('');
 const[entityId,setEntityId]=useState('');const[drafts,setDrafts]=useState<Record<string,Draft>>(load);const[notice,setNotice]=useState('');const[tick,setTick]=useState(0);
 const[stale,setStale]=useState<{what:string}|null>(null);
 const refresh=useCallback(async()=>{try{const next=await api<Flow>('/api/ops-sync/flow');setFlow(next);setEntityId(id=>id||next.entities[0]?.entity_id||'')}catch(e){if(e instanceof ApiError&&e.status===404)setHidden(true);else setError((e as Error).message)}},[]);
 useEffect(()=>{void refresh()},[refresh]);
 useEffect(()=>{try{sessionStorage.setItem(KEY,JSON.stringify(drafts))}catch{/* private mode: drafts stay in memory */}},[drafts]);
 if(hidden)return null;
 const entity=flow?.entities.find(e=>e.entity_id===entityId);
 const draft=(entityId&&drafts[entityId])||emptyDraft();
 const setDraft=(next:Draft)=>setDrafts(all=>({...all,[entityId]:next}));
 const post=async(key:string,path:string,body:Record<string,unknown>,onDone:(f:Flow)=>string)=>{setBusy(key);setError('');setNotice('');setStale(null);
  try{const next=await api<Flow>(`/api/ops-sync/flow/${path}`,{method:'POST',body:JSON.stringify(body)});setFlow(next);setNotice(onDone(next));setTick(t=>t+1);return true}
  catch(e){const status=e instanceof ApiError?e.status:0;
   // Rejections and 409s never discard the draft: reload the latest state and show current vs intended side by side.
   if(status===409){setStale({what:path});setError((e as Error).message+'。已重新載入最新內容，您的輸入仍保留，請核對後再送出。');await refresh()}else setError((e as Error).message);return false}finally{setBusy('')}};
 const sentence=(f:Flow)=>deliverySentence(f.command?.state,STATES);
 const submitSeat=()=>{if(!entity)return;const d=withIdentity(draft,uuid,now);setDraft(d);
  void post('seat','assign',{command_id:d.cid,entity_id:entity.entity_id,person_ids:d.people,occurred_at:d.occurredAt,mock_outcome:d.outcome==='normal'?undefined:d.outcome},f=>`指派已受理（本機模擬）。${sentence(f)}`)};
 const submitDate=()=>{if(!entity)return;const d=withIdentity(draft,uuid,now);setDraft(d);
  void post('date','propose',{command_id:d.cid,entity_id:entity.entity_id,intended:d.date,expected:entity.deadline.effective.value||undefined,expected_revision:entity.deadline.effective.revision,occurred_at:d.occurredAt},
   f=>`期限變更已提出為「提案」，尚未核准、生效日期未變。${sentence(f)}`).then(ok=>{if(ok)setDraft({...emptyDraft(),outcome:draft.outcome})})};
 const decide=(p:{proposal_id:string},decision:'approved'|'rejected'|'stale')=>post('decide:'+p.proposal_id+decision,'decide',{command_id:p.proposal_id,entity_id:entityId,decision,mock_outcome:draft.outcome==='normal'?undefined:draft.outcome},
  f=>`${DECISION_RESULT[decision]}（mock）結果：${f.outcome?.status==='denied'?`被拒（${f.outcome.reason_text||f.outcome.reason}），生效日期未變`:f.outcome?.status==='failed'?'提案已結案，生效日期未變':f.outcome?.duplicate?'重複決定，未再變更':'已記錄'}。${sentence(f)}`);
 // A failed command is certain-not-written: keep the user's intent by pre-filling a fresh draft (new operation id) for the same target.
 const retry=(c:Command)=>{const v=c.intended.value||'';const date=c.field_id.endsWith('deadline');
  setEntityId(c.entity_id);setDrafts(all=>({...all,[c.entity_id]:{...emptyDraft(),people:date||c.intended.kind!=='set'?[]:[v.split('|')[2]],date:date?v:''}}));
  setNotice('已帶回原本的內容，請核對後重新送出（會是新的申請，不會覆蓋原紀錄）。')};
 const denial=flow?.dispatch_denial;
 const lastSeat=entity&&flow?.commands.filter(c=>c.entity_id===entity.entity_id&&c.field_id===entity.seat_field).at(-1);
 const pendingSeat=lastSeat&&lastSeat.state!=='confirmed'?lastSeat:undefined;
 const people=(flow?.roster||[]);
 return <section aria-label="營運同步操作流程（本機模擬）" className="owned-view ops-sync ops-flow">
  <div className="section-heading"><div><h2>營運同步操作流程（本機模擬）</h2><p role="note" className="ops-sync-notice">{flow?.notice||MOCK_NOTICE}</p><p role="note" className="ops-sync-notice" data-testid="mapping-notice"><Badge tone="warning">{MAPPING_BADGE}</Badge> {flow?.mapping_notice}</p></div></div>
  {error&&<p role="alert" className="owned-alert">操作未完成：{error}</p>}
  {notice&&<p role="status" className="ops-flow-notice">{notice}</p>}
  {!flow&&!error&&<p role="status">讀取中…</p>}
  {denial&&denial.suspended.length>0&&<div role="alert" className="owned-alert ops-flow-denial" data-testid="dispatch-denial"><strong>派送已全域暫停</strong>：{denial.suspended.map(s=>reasonText(s.reason)).join('、')}（自 {denial.suspended[0].since}）。
   {denial.held_commands.length>0?`後續 ${denial.held_commands.length} 筆申請已排隊，暫停期間不會送出。`:'目前沒有排隊中的後續申請。'}
   <Button disabled={!!busy} onClick={()=>void post('resume','resume-dispatch',{},()=>'已恢復派送（本機模擬），排隊申請將重新處理。')}>修復後恢復派送</Button></div>}
  {flow&&!flow.entities.length&&<p>您目前沒有可操作的模擬案件或節點。</p>}
  {flow&&entity&&<Section>
   <div className="ops-flow-pick"><label>選擇案件或節點（模擬資料）<FormSelect value={entityId} onChange={e=>{setEntityId(e.target.value);setStale(null);setError('')}}>{flow.entities.map(e=><option key={e.entity_id} value={e.entity_id}>{entityTitle(e)}</option>)}</FormSelect></label></div>
   <article className="ops-sync-item" aria-label={`${entityTitle(entity)}：${FIELDS[entity.seat_field]}`}>
    <header><strong>{FIELDS[entity.seat_field]}</strong><Badge tone="warning">{MAPPING_BADGE}</Badge></header>
    <p>{SEAT_LABEL[entity.kind]}</p>
    <dl className="ops-sync-values"><div><dt>目前指派</dt><dd data-testid="seat-current">{entity.seat.person_id?`${entity.seat.name}（${entity.seat.person_id}）`:'（尚未指派）'}{pendingSeat&&<span className="ops-sync-entity"> — 模擬派送尚未確認（{STATES[pendingSeat.state].label}）</span>}</dd></div>
     {entity.seat.open_conflicts.length>0&&<div><dt>未解決的多人指派衝突</dt><dd>{entity.seat.open_conflicts.join('、')}</dd></div>}</dl>
    <fieldset className="ops-flow-people"><legend>選擇被指派人（一次只能一位；人員以代號綁定，不以姓名比對）</legend>
     {people.map(p=><label key={p.person_id}><input type="checkbox" checked={draft.people.includes(p.person_id)} onChange={e=>setDraft(edited(draft,{people:e.target.checked?[...draft.people,p.person_id]:draft.people.filter(x=>x!==p.person_id)}))}/>{personLabel(p)}</label>)}</fieldset>
    <div className="inline-actions"><Button variant="primary" disabled={!!busy||!draft.people.length} onClick={submitSeat}>{busy==='seat'?'送出中…':'送出指派'}</Button>
     <Button disabled={!!busy||!entity.seat.person_id} onClick={()=>{const d=withIdentity(edited(draft,{people:[]}),uuid,now);setDraft(d);void post('seat','assign',{command_id:d.cid,entity_id:entity.entity_id,person_ids:[],occurred_at:d.occurredAt},f=>`清除指派已受理（本機模擬）。${sentence(f)}`)}}>清除指派</Button></div>
   </article>
   <article className="ops-sync-item" aria-label={`${entityTitle(entity)}：期限`}>
    <header><strong>{entity.kind==='case'?'案件期限':'節點期限'}</strong><Badge tone="warning">{MAPPING_BADGE}</Badge></header>
    <p>{DEADLINE_LABEL}</p>
    <dl className="ops-sync-values" aria-label="期限比較" data-testid="date-compare"><div><dt>目前生效（版本 {entity.deadline.effective.revision}）</dt><dd data-testid="effective-date">{entity.deadline.effective.value||'（尚未設定）'}</dd></div>
     <div><dt>{stale?'您擬變更（草稿已保留）':'擬變更（提案）'}</dt><dd data-testid="intended-date">{draft.date||'（尚未輸入）'}</dd></div>
     {entity.deadline.original&&<div><dt>原始（合約證據）</dt><dd>{entity.deadline.original}</dd></div>}</dl>
    <label>擬變更日期<input type="date" value={draft.date} onChange={e=>setDraft(edited(draft,{date:e.target.value}))}/></label>
    <div className="inline-actions"><Button variant="primary" disabled={!!busy||!draft.date} onClick={submitDate}>{busy==='date'?'送出中…':'提出期限變更'}</Button></div>
    <p role="note" className="ops-sync-reason">提出後僅為「提案」，尚未核准；只有「已核准（模擬收據已消耗）」才會改變生效日期。</p>
    {entity.deadline.proposals.length>0&&<ul className="ops-flow-proposals" aria-label="提案與模擬收據">{entity.deadline.proposals.map(p=><li key={p.proposal_id} data-kind={p.mock_receipt?'receipt':'proposal'} data-state={p.state}>
     <Badge tone={p.state==='confirmed'?'positive':p.state==='waiting_approval'?'warning':'critical'}>{p.mock_receipt?'已核准（模擬收據）':'提案'}</Badge> {p.expected||'（空白）'} → {p.intended} — {PROPOSAL_STATE[p.state]||p.state}{p.reason?`（${reasonText(p.reason)}）`:''}
     {p.mock_receipt&&<span className="ops-sync-entity"> 模擬收據 {p.receipt_id}</span>}
     {p.state==='waiting_approval'&&<span className="inline-actions" role="group" aria-label="模擬決定（mock）"><Button disabled={!!busy} onClick={()=>void decide(p,'approved')}>模擬核准</Button><Button disabled={!!busy} onClick={()=>void decide(p,'rejected')}>模擬駁回</Button><Button disabled={!!busy} onClick={()=>void decide(p,'stale')}>模擬過期核准</Button></span>}</li>)}</ul>}
    <p role="note" className="ops-sync-notice">{MOCK_DECISION_NOTE}</p>
   </article>
   <details className="ops-sync-item"><summary>模擬情境（僅本機 mock，用於演練失敗與復原）</summary>
    <label>下一次派送的模擬結果<FormSelect value={draft.outcome} onChange={e=>setDrafts(all=>({...all,[entityId]:{...draft,outcome:e.target.value}}))}>{flow.mock_outcomes.map(o=><option key={o} value={o}>{MOCK_OUTCOME_LABEL[o]||o}</option>)}</FormSelect></label></details>
  </Section>}
  <OpsSyncPanel key={tick} onRetry={retry}/>
 </section>;
}
