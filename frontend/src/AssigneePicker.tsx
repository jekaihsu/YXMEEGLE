import {useEffect,useId,useRef,useState} from 'react';
import {api,getSessionEpoch,onSessionEpochChange} from './api';
import {Button} from './design';
import {draftChanged,type TaskDraft,type TaskEditorModel} from './nodeWorkbenchModel';
import './AssigneePicker.css';

type Person={id:string;name:string;teams?:string[]};
type Page={people:Person[];next_cursor:string|null};
const EMPTY_PEOPLE:Person[]=[];
const cache=new Map<string,{at:number;page:Page}>();
onSessionEpochChange(()=>cache.clear());
function parsePage(value:unknown):Page{
 if(!value || typeof value!=='object' || !('people' in value) || !Array.isArray(value.people))throw new Error('人員回應格式錯誤');
 const people=value.people.map((p:unknown)=>{
  if(!p || typeof p!=='object' || !('id' in p) || typeof p.id!=='string' || !('name' in p) || typeof p.name!=='string')throw new Error('人員回應格式錯誤');
  return {id:p.id,name:p.name,teams:'teams' in p && Array.isArray(p.teams)?p.teams.filter((t:unknown):t is string=>typeof t==='string'):[]};
 });
 return {people,next_cursor:'next_cursor' in value && typeof value.next_cursor==='string'?value.next_cursor:null};
}

export function AssigneePicker({projectId,nodeKey,title,value,valueLabel,disabled=false,busy=false,onChange,people=EMPTY_PEOPLE}:{projectId?:string;nodeKey?:string;title:string;value:string;valueLabel?:string;disabled?:boolean;busy?:boolean;onChange:(id:string)=>void;people?:Person[]}){
 const [open,setOpen]=useState(false),[query,setQuery]=useState(''),[search,setSearch]=useState('');
 const [page,setPage]=useState<Page>({people:[],next_cursor:null}),[cursor,setCursor]=useState<string|null>(null);
 const [loading,setLoading]=useState(false),[error,setError]=useState(''),[active,setActive]=useState(0);
 const [epoch,setEpoch]=useState(getSessionEpoch);
 const root=useRef<HTMLDivElement>(null),id=useId();
 useEffect(()=>onSessionEpochChange(()=>{setEpoch(getSessionEpoch());setOpen(false);setPage({people:[],next_cursor:null})}),[]);
 useEffect(()=>{const timer=setTimeout(()=>{setSearch(query.trim());setCursor(null)},250);return()=>clearTimeout(timer)},[query]);
 useEffect(()=>{if(!open)return;const away=(e:MouseEvent)=>{if(e.target instanceof Node&&!root.current?.contains(e.target))setOpen(false)};document.addEventListener('mousedown',away);return()=>document.removeEventListener('mousedown',away)},[open]);
 useEffect(()=>{
  if(!open)return;
  if(query.trim()!==search){setLoading(true);setPage({people:[],next_cursor:null});return}
  if(!projectId){setPage({people:people.filter(p=>p.name.includes(search)),next_cursor:null});return}
  const controller=new AbortController();let current=true;
  const scope=search?'all':'team';
  const key=JSON.stringify([epoch,projectId,nodeKey,scope,search,cursor]);
  const params=new URLSearchParams({scope,q:search,limit:'20'});if(nodeKey)params.set('node_key',nodeKey);if(cursor)params.set('cursor',cursor);
  const receive=(result:Page)=>{if(current&&epoch===getSessionEpoch()){setPage(old=>cursor?{...result,people:[...old.people,...result.people]}:result);setActive(0);setLoading(false)}};
  setError('');setLoading(true);if(!cursor)setPage({people:[],next_cursor:null});
  const stored=cache.get(key);
  if(stored&&Date.now()-stored.at<60000)receive(stored.page);
  else void api<unknown>(`/api/projects/${encodeURIComponent(projectId)}/sop-assignees?${params}`,{signal:controller.signal},()=>current&&epoch===getSessionEpoch()).then(parsePage).then(result=>{
   if(current&&epoch===getSessionEpoch()){cache.set(key,{at:Date.now(),page:result});if(cache.size>100)cache.delete(cache.keys().next().value||'');receive(result)}
  }).catch(()=>{if(current&&epoch===getSessionEpoch()){setError('無法讀取人員，請重新開啟重試');setLoading(false)}});
  return()=>{current=false;controller.abort()};
 },[open,projectId,nodeKey,search,query,cursor,epoch,people]);
 useEffect(()=>{if(open)document.getElementById(`${id}-${active}`)?.scrollIntoView?.({block:'nearest'})},[open,active,id]);
 const options=[{id:'',name:'未指派'},...page.people];
 const pick=(index:number)=>{const person=options[index];if(person){onChange(person.id);setOpen(false);root.current?.querySelector('button')?.focus()}};
 return <div className="assignee-picker ds-picker" ref={root}>
  <Button aria-label={`task: ${title}`} aria-haspopup="listbox" aria-expanded={open} disabled={disabled} aria-disabled={disabled || busy} onKeyDown={e=>{if(busy)return;if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setOpen(true)}}} onClick={()=>{if(busy)return;setOpen(v=>!v);setQuery('');setSearch('');setCursor(null)}}>{valueLabel || people.find(p=>p.id===value)?.name || page.people.find(p=>p.id===value)?.name || (value?'目前負責人':'未指派')}</Button>
  {open&&<div className="assignee-picker-popover"><input autoFocus role="combobox" aria-label={`搜尋人員：${title}`} aria-expanded="true" aria-controls={id} aria-autocomplete="list" aria-activedescendant={`${id}-${active}`} placeholder="搜尋所有在職人員" value={query} onChange={e=>{setQuery(e.target.value);setActive(0)}} onKeyDown={e=>{
   if(e.key==='Escape'){e.preventDefault();setOpen(false);root.current?.querySelector('button')?.focus()}
   else if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setActive(a=>Math.max(0,Math.min(options.length-1,a+(e.key==='ArrowDown'?1:-1))))}
   else if(e.key==='Home'||e.key==='End'){e.preventDefault();setActive(e.key==='Home'?0:options.length-1)}
   else if(e.key==='Enter'){e.preventDefault();if(!loading&&query.trim()===search)pick(active)}
  }}/><small>{search?'所有在職人員（同組優先）':'同組人員'}</small>
   {loading&&<p role="status">載入人員中…</p>}{error&&<p role="alert">{error}</p>}
   {!loading&&!error&&page.people.length===0&&<p role="status">沒有符合的人員</p>}
   <ul id={id} role="listbox" aria-label={`task: ${title}`} aria-busy={loading}>{options.map((p,index)=><li key={p.id} id={`${id}-${index}`} role="option" aria-selected={p.id===value} data-active={active===index} onMouseDown={e=>e.preventDefault()} onClick={()=>pick(index)}>{p.name}{p.teams?.length?` · ${p.teams.join('、')}`:''}</li>)}</ul>
   {page.next_cursor&&<Button disabled={loading} onClick={()=>setCursor(page.next_cursor)}>更多人員</Button>}
  </div>}
 </div>;
}

export function AssigneeTaskEditor({model,busy=false,onSave,projectId,nodeKey}:{model:TaskEditorModel;busy?:boolean;onSave:(draft:TaskDraft)=>Promise<boolean>;projectId?:string;nodeKey?:string}) {
 const [draft,setDraft]=useState(model.draft),[saving,setSaving]=useState(false),[message,setMessage]=useState('');
 const changed=draftChanged(model.draft,draft),dueChanged=draft.due!==model.draft.due;
 const blocked=busy || saving;
 const denied=(['title','assignee','due','notes','status'] as const).find(key=>draft[key]!==model.draft[key]&&!model.fields[key].enabled);
 const locked=model.readOnlyReason || (Object.values(model.fields).every(f=>!f.enabled)?model.fields.title.reason:'');
 const saveReason=locked || (denied?model.fields[denied].reason:!draft.title.trim() ? '請填寫任務名稱' : !changed ? '請先修改任務內容' : model.dueReason && dueChanged && !draft.reason.trim() ? '請填寫期限變更原因' : '');
 const update=(key:keyof TaskDraft,value:string)=>{setDraft(d=>({...d,[key]:value}));setMessage('')};
 const readOnlyReason=locked;
 const field=(key:keyof TaskEditorModel['fields'])=>({disabled:blocked || !!locked || !model.fields[key].enabled,'aria-describedby':readOnlyReason ? 'task-editor-readonly' : !model.fields[key].enabled ? `task-editor-${key}-reason` : undefined});
 const reason=(key:keyof TaskEditorModel['fields'])=>!readOnlyReason && !model.fields[key].enabled && <small id={`task-editor-${key}-reason`}>{model.fields[key].reason}</small>;
 const submit=async()=>{if(blocked || saveReason)return;setSaving(true);setMessage('');try{const ok=await onSave(draft);setMessage(ok?'已儲存任務':'尚未儲存，請核對錯誤後重試')}finally{setSaving(false)}};
 return <form className="nw-task-editor" aria-label="編輯任務" onSubmit={e=>{e.preventDefault();void submit()}}>
  {readOnlyReason && <p className="nw-editor-wide" id="task-editor-readonly">{readOnlyReason}</p>}
  <label>任務名稱<input aria-label="任務名稱" value={draft.title} maxLength={model.maxTitle} required {...field('title')} onChange={e=>update('title',e.target.value)}/>{reason('title')}</label>
  <div>負責人<AssigneePicker projectId={projectId} nodeKey={nodeKey} title={model.draft.title} value={draft.assignee} people={model.people} disabled={field('assignee').disabled} onChange={id=>update('assignee',id)}/>{reason('assignee')}</div>
  <label>期限<input aria-label="任務期限" type="date" value={draft.due} {...field('due')} onChange={e=>update('due',e.target.value)}/>{reason('due')}</label>
  <label>任務狀態<select aria-label="任務狀態" value={draft.status} {...field('status')} onChange={e=>update('status',e.target.value)}>{model.statuses.map(s=><option key={s.id} value={s.id}>{s.label}</option>)}</select>{reason('status')}</label>

  <label className="nw-editor-wide">備註<textarea aria-label="任務備註" rows={4} value={draft.notes} maxLength={model.maxNotes} {...field('notes')} onChange={e=>update('notes',e.target.value)}/>{reason('notes')}</label>
  {model.dueReason && dueChanged && <label className="nw-editor-wide">期限變更原因<input aria-label="期限變更原因" value={draft.reason} maxLength={1000} required disabled={blocked} onChange={e=>update('reason',e.target.value)}/></label>}
  {!locked&&<div className="nw-editor-wide nw-editor-save"><Button type="submit" variant="primary" disabled={blocked || !!saveReason} disabledReason={blocked ? '正在儲存，請稍候' : saveReason}>{saving ? '儲存中…' : '儲存任務'}</Button>{message && <span role="status">{message}</span>}</div>}
 </form>;
}
