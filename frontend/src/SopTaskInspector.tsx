import {InlineTaskEditor} from './InlineTaskEditor';
import {editorFields,type TaskDraft} from './nodeWorkbenchModel';
import {TaskSuggestion,SuggestionReview} from './SopSuggestions';
import {createPortal} from 'react-dom';
import {useState, type ReactNode} from 'react';
import {Badge, Button, Row, Section, Sheet} from './design';
import {SopError, sopApi, sopErrorText, sopNodeLabel, type Applicability, type MutationResult, type SopTask, SOP_ERROR_TEXT} from './sopTaskApi';
import {APPLICABILITY_LABEL, ROLE_LABEL, stateLabel, taskActions, type TaskAction} from './sopTaskModel';
import {FlowAction} from './FlowActions';
import type {useSopTasks} from './useSopTasks';
import type {User} from './types';

const RAW_FIELDS: [string, string][] = [['owner_role_raw','負責角色'],['trigger_raw','觸發'],['anchor_raw','起算'],['deadline_raw','期限'],['inputs_raw','輸入'],['procedure_raw','作法'],['human_decision_raw','人工判斷'],['outputs_raw','產出'],['done_when_raw','完成條件'],['next_raw','下一步'],['escalation_raw','升級'],['applicability_raw','適用條件'],['unresolved_raw','待確認事項']];
const record = (v: unknown) => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
const plain = (v: unknown) => typeof v === 'string' || typeof v === 'number' ? String(v) : '';

function Provenance({task}: {task: SopTask}) {
 const row = record(task.source?.row), raw = record(row.raw), template = record(task.source?.template);
 return <details className="sop-source"><summary>來源</summary>
  {task.manual ? <Section><Row label="來源" value="手動建立"/></Section>
   : task.restricted ? <Section><Row label="來源" value="無來源讀取權限"/></Section>
   : <><Section>
     <Row label="範本版本" value={plain(template.revision)}/>
     <Row label="位置" value={plain(row.source_locator)}/>
    </Section>
    <Section title="原始內容">{RAW_FIELDS.filter(([k]) => plain(raw[k]).trim()).map(([k, label]) => <Row key={k} label={label} value={<span className="sop-raw">{plain(raw[k])}</span>}/>)}</Section></>}
 </details>;
}

function Reasoned({label, busy, onSubmit}: {label: string; busy: boolean; onSubmit: (reason: string) => void}) {
 const [open, setOpen] = useState(false), [reason, setReason] = useState('');
 if (!open) return <FlowAction allowed={!busy} reason="處理中" onClick={() => setOpen(true)}>{label}</FlowAction>;
 return <form className="sop-inline" onSubmit={e => {e.preventDefault(); if (reason.trim()) onSubmit(reason.trim())}}>
  <label>{label}原因<input autoFocus value={reason} maxLength={1000} onChange={e => setReason(e.target.value)}/></label>
  <Button onClick={() => setOpen(false)} disabled={busy}>取消</Button><Button type="submit" variant="primary" disabled={!reason.trim() || busy} disabledReason="請填寫原因">{label}</Button>
 </form>;
}

function Field({label, children}: {label: string; children: ReactNode}) {
 return <label className="sop-field">{label}{children}</label>;
}

export function SopTaskInspector({task, project, users, sop, onClose}: {task: SopTask; project: {id:string}; users: User[]; sop: ReturnType<typeof useSopTasks>; onClose: () => void}) {
 const [review,setReview]=useState(false);
 const [resultNote,setResultNote]=useState('');
 const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
 const run = async (call: () => Promise<MutationResult>, done: string) => {
  setBusy(true); setError(''); setNotice('');
  try {await call(); await sop.reload(); if (sop.current()) setNotice(done); return true}
  catch (e) {
   if (!sop.current()) return false;
   setError(sopErrorText(e));
   if (e instanceof SopError && (e.code === 'task_revision_conflict' || e.ambiguous)) await sop.reload();
  return false;
  } finally {if (sop.current()) setBusy(false)}
 };
 const patch = (body: Record<string, unknown>, done: string) => run(() => sopApi.patch(project.id, task.id, {expected_revision: task.revision, ...body}, sop.current), done);
 const transition = (action: TaskAction|'set_applicability', extra: Record<string, unknown> = {}) => run(() => sopApi.transition(project.id, task.id, {expected_revision: task.revision, action, ...extra}, sop.current), '已更新狀態');
 const completionReason=busy?'處理中':task.completionBlockedReason?SOP_ERROR_TEXT[task.completionBlockedReason]||'完成條件待核對':!task.allowedActions.includes('complete')?'目前無法完成此任務':!resultNote.trim()?'請填寫結果說明':'';
 const draft={title:task.title,assignee:task.participants.executor || '',due:task.dueDate || '',notes:task.instructions || '',status:task.state,reason:''};
 const editable=task.allowedActions.includes('edit');
 const save=(value:TaskDraft)=>{
  const body:Record<string,unknown>={};
  if(value.title!==task.title)body.title=value.title.trim();
  if(value.notes!==draft.notes && task.instructions!==null)body.instructions=value.notes;
  if(value.assignee!==draft.assignee)body.participants=Object.fromEntries(Object.entries({...task.participants,executor:value.assignee}).filter(([,v])=>v));
  if(value.due!==draft.due){body.due_date=value.due || null;body.reason=value.reason.trim()}
  return patch(body,'已儲存任務');
 };

 return createPortal(<Sheet title={`SOP 任務 · ${task.title}`} onClose={() => {if (!busy) onClose()}}>
  <div className="sop-inspector">
   <div className="sop-badges"><Badge tone="accent">SOP 任務</Badge><Badge>{stateLabel(task)}</Badge>{task.overdue && <Badge tone="critical">逾期</Badge>}{task.shared && <Badge>共用</Badge>}{task.applicability !== 'applicable' && <Badge tone="warning">{APPLICABILITY_LABEL[task.applicability]}</Badge>}</div>
   {error && <p role="alert" className="pg-callout">{error}</p>}
   {notice && <p role="status" className="sop-muted">{notice}</p>}
   <InlineTaskEditor busy={busy || sop.state.kind!=='ready' || sop.state.refreshing} model={{draft,fields:editorFields({title:editable,assignee:editable,due:editable,notes:editable && task.instructions!==null,status:false},task.state==='archived'?'已封存':task.state==='done'?'已完成':'需管理權限'),people:sop.assignees,statuses:[{id:task.state,label:stateLabel(task)}],maxTitle:500,maxNotes:20000,dueReason:true,readOnlyReason:task.state==='archived'?'已封存':task.state==='done'?'已完成':undefined}} onSave={save}/>
   {editable && <ParticipantRoles task={task} people={sop.assignees} busy={busy} save={participants=>patch({participants},'已更新人員')}/>}
   {task.allowedActions.includes('set_applicability') && <ApplicabilityEditor task={task} busy={busy} save={(applicability,reason)=>transition('set_applicability',{applicability,reason})}/>}
   <div className="pf-actions sop-transitions" role="group" aria-label="狀態操作">{taskActions(task).filter(a=>a.action!=='complete').map(a => a.reason
    ? <Reasoned key={a.action} label={a.label} busy={busy} onSubmit={reason => void transition(a.action, {reason})}/>
    : <FlowAction key={a.action} allowed={!busy} reason="處理中" onClick={() => void transition(a.action)}>{a.label}</FlowAction>)}</div>
   {task.result && <Section title="完成結果"><Row label="完成人員" value={task.result.actorName}/><Row label="完成時間" value={new Date(task.result.at*1000).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})}/><Row label="結果說明" value={<span className="sop-raw">{task.result.note}</span>}/></Section>}
   {task.state!=='done'&&task.state!=='archived'&&<form className="sop-form sop-result" onSubmit={e=>{e.preventDefault();if(!completionReason)void transition('complete',{result_note:resultNote.trim()})}}>
    <Field label="結果說明"><textarea rows={4} maxLength={20000} value={resultNote} disabled={busy||!task.allowedActions.includes('complete')} onChange={e=>setResultNote(e.target.value)}/></Field>
    {completionReason&&<p className="sop-muted" role="status">{completionReason}</p>}
    <Button type="submit" variant="primary" disabled={!!completionReason} disabledReason={completionReason}>完成</Button>
   </form>}
   <TaskSuggestion projectId={project.id} task={task} current={sop.current} reload={sop.reload} onAccept={()=>setReview(true)}/><Provenance task={task}/>{review && <SuggestionReview projectId={project.id} tasks={'data' in sop.state ? sop.state.data?.tasks||[] : []} initial={[task.id]} current={sop.current} reload={sop.reload} onClose={()=>setReview(false)}/>}
  </div>
 </Sheet>, document.body);
}

function ApplicabilityEditor({task,busy,save}:{task:SopTask;busy:boolean;save:(value:Applicability,reason:string)=>Promise<boolean|undefined>}) {
 const [value,setValue]=useState(task.applicability),[reason,setReason]=useState('');
 return <form className="sop-form" onSubmit={e=>{e.preventDefault();if(reason.trim())void save(value,reason.trim())}}>
  <Field label="適用"><select aria-label="適用" value={value} disabled={busy} onChange={e=>{const next=e.target.value;if(next==='applicable'||next==='not_applicable'||next==='unresolved')setValue(next)}}>{(Object.entries(APPLICABILITY_LABEL)).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></Field>
  <Field label="適用原因"><input aria-label="適用原因" value={reason} maxLength={1000} disabled={busy} onChange={e=>setReason(e.target.value)}/></Field>
  <Button type="submit" disabled={busy||value===task.applicability||!reason.trim()} disabledReason="請變更適用狀態並填寫原因">儲存適用</Button>
 </form>;
}

function ParticipantRoles({task,people,busy,save}:{task:SopTask;people:{id:string;name:string}[];busy:boolean;save:(participants:SopTask['participants'])=>Promise<boolean|undefined>}) {
 const [roles,setRoles]=useState(task.participants);
 return <details><summary>檢核與確認人員</summary><form className="sop-form" onSubmit={e=>{e.preventDefault();void save(Object.fromEntries(Object.entries({...task.participants,checker:roles.checker,confirmer:roles.confirmer}).filter(([,v])=>v)))}}>
  {(['checker','confirmer'] as const).map(role=><Field key={role} label={ROLE_LABEL[role]}><select value={roles[role]||''} disabled={busy} onChange={e=>setRoles(old=>({...old,[role]:e.target.value||undefined}))}><option value="">未指派</option>{people.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>)}
  <Button type="submit" disabled={busy} disabledReason="正在儲存">儲存檢核與確認人員</Button>
 </form></details>;
}
