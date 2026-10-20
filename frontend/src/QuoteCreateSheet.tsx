import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {getSessionEpoch} from './api';
import {Badge,Button,Row,Section,Sheet} from './design';
import {quoteApi,type QuoteDraft,type QuoteForm,type QuoteReceipt} from './quoteApi';
import {SopError,sopErrorText} from './sopTaskApi';
import type {User} from './types';

type Step={kind:'form'}|{kind:'preview';draft:QuoteDraft}|{kind:'receipt';receipt:QuoteReceipt};
export function QuoteCreateSheet({users,canImport,onClose,onCreated,onOpen}:{users:User[];canImport:boolean;onClose:()=>void;onCreated:()=>void;onOpen:(ref:string)=>void}) {
 const [form,setForm]=useState<QuoteForm>({name:'',pm_id:null,client:'',description:'',official_quote_no:'',import_tasks:canImport});
 const [step,setStep]=useState<Step>({kind:'form'}),[status,setStatus]=useState<'idle'|'busy'|'confirming'|'unknown'>('idle');
 const [error,setError]=useState(''),[numberError,setNumberError]=useState('');
 const attempt=useRef<{draft:string;request:string}|null>(null),life=useRef({active:true,epoch:getSessionEpoch()});
 useEffect(()=>{life.current.active=true;return()=>{life.current.active=false}},[]);
 const current=()=>life.current.active&&life.current.epoch===getSessionEpoch();
 const locked=status!=='idle';
 const fail=(e:unknown)=>{if(e instanceof SopError&&['quote_number_taken','quote_number_invalid'].includes(e.code)){setNumberError(e.code==='quote_number_taken'?'報價編號已使用':'報價編號格式不正確');setStep({kind:'form'})}else setError(sopErrorText(e))};
 const preview=async()=>{if(status!=='idle')return;setStatus('busy');setError('');setNumberError('');try{const draft=await quoteApi.preview(form,current);if(current()){attempt.current=null;setStep({kind:'preview',draft})}}catch(e){if(current())fail(e)}finally{if(current())setStatus('idle')}};
 const finish=(receipt:QuoteReceipt)=>{attempt.current=null;setStatus('idle');setError('');setStep({kind:'receipt',receipt});onCreated()};
 const recover=async()=>{const pending=attempt.current;if(!pending)return;setStatus('confirming');setError('');try{const r=await quoteApi.recover(pending.request,current);if(current())finish(r)}catch(e){if(!current())return;if(e instanceof SopError&&e.code==='run_not_found'){setStatus('idle');setError('尚未建立')}else{setStatus('unknown');fail(e)}}};
 const create=async()=>{if(step.kind!=='preview'||status!=='idle')return;const draft=step.draft;if(!attempt.current)attempt.current={draft:draft.draft_id,request:crypto.randomUUID()};const pending=attempt.current;setStatus('busy');setError('');try{const r=await quoteApi.create(pending.draft,pending.request,current);if(current())finish(r)}catch(e){if(!current())return;if(e instanceof SopError&&e.ambiguous){await recover();return}attempt.current=null;setStatus('idle');fail(e);if(e instanceof SopError&&['preview_stale','preview_not_found'].includes(e.code))setStep({kind:'form'})}};
 const update=<K extends keyof QuoteForm>(key:K,value:QuoteForm[K])=>setForm(f=>({...f,[key]:value}));
 return createPortal(<Sheet title="建立報價" onClose={()=>{if(!locked)onClose()}}><div className="sop-import">
  <Badge>本地規劃</Badge>
  {error&&<p role="alert">{error}</p>}
  {step.kind==='form'&&<form className="sop-form" onSubmit={e=>{e.preventDefault();void preview()}}>
   <label>案件名稱<input required maxLength={500} value={form.name} disabled={locked} onChange={e=>update('name',e.target.value)}/></label>
   <label>PM<select value={form.pm_id||''} disabled={locked} onChange={e=>update('pm_id',e.target.value||null)}><option value="">未指派</option>{users.filter(u=>u.active!==false&&['pm','manager'].includes(u.role)).map(u=><option key={u.id} value={u.id}>{u.name}</option>)}</select></label>
   <label>業主<input value={form.client} disabled={locked} maxLength={500} onChange={e=>update('client',e.target.value)}/></label>
   <label>說明<textarea value={form.description} disabled={locked} maxLength={5000} onChange={e=>update('description',e.target.value)}/></label>
   <label>報價編號<input aria-label="報價編號" value={form.official_quote_no} disabled={locked} aria-invalid={!!numberError} aria-describedby={numberError?'quote-number-error':undefined} onChange={e=>{update('official_quote_no',e.target.value);setNumberError('')}}/>{numberError&&<span id="quote-number-error" role="alert">{numberError}</span>}</label>
   <fieldset className="sop-choices"><legend>SOP 任務</legend>{canImport&&<label><input type="radio" name="quote-import" checked={form.import_tasks} disabled={locked} onChange={()=>update('import_tasks',true)}/>SOP 從報價開始 · 全部九個節點</label>}<label><input type="radio" name="quote-import" checked={!form.import_tasks} disabled={locked} onChange={()=>update('import_tasks',false)}/>建立但不匯入任務</label></fieldset>
   <div className="sop-sheet-actions"><Button disabled={locked} onClick={onClose}>取消</Button><Button type="submit" variant="primary" disabled={locked||!form.name.trim()}>{locked?'預覽中…':'預覽'}</Button></div>
  </form>}
  {step.kind==='preview'&&<><Section title="確認報價"><Row label="案件名稱" value={step.draft.case.name}/><Row label="業主" value={step.draft.case.client||'未設定'}/><Row label="PM" value={users.find(u=>u.id===step.draft.case.pm_id)?.name||'未指派'}/><Row label="報價編號" value={step.draft.case.official_quote_no||'未設定'}/><Row label="說明" value={step.draft.case.description||'未設定'}/><Row label="SOP 任務" value={step.draft.taskCount}/>{form.import_tasks&&<Row label="起始節點" value="報價 · 全部九個節點"/>}</Section>
   {(status==='confirming'||status==='unknown')&&<p role="status">正在確認建立結果</p>}
   <div className="sop-sheet-actions"><Button disabled={locked||!!attempt.current} onClick={()=>setStep({kind:'form'})}>上一步</Button>{status==='unknown'?<Button onClick={()=>void recover()}>重新確認建立結果</Button>:<Button variant="primary" disabled={locked} onClick={()=>void create()}>{locked?'建立中…':attempt.current?'重試建立':'確認建立'}</Button>}</div></>}
  {step.kind==='receipt'&&<><Section title="已建立"><Row label="案件名稱" value={step.receipt.name}/><Row label="報價編號" value={step.receipt.official_quote_no||'未設定'}/><Row label="本地規劃" value={step.receipt.local_reference}/><Row label="SOP 任務" value={step.receipt.imported?.created.length||0}/></Section><div className="sop-sheet-actions"><Button onClick={onClose}>關閉</Button><Button variant="primary" onClick={()=>onOpen(step.receipt.local_reference)}>開啟案件</Button></div></>}
 </div></Sheet>,document.body);
}
