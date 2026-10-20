import {TaskSuggestion,SuggestionReview} from './SopSuggestions';
import {createPortal} from 'react-dom';
import {useState, type ReactNode} from 'react';
import {Badge, Button, Row, Section, Sheet} from './design';
import {ROLES, SopError, sopApi, sopErrorText, sopNodeLabel, type Applicability, type MutationResult, type Role, type SopTask} from './sopTaskApi';
import {APPLICABILITY_LABEL, dueLabel, ROLE_LABEL, stateLabel, taskActions, type TaskAction} from './sopTaskModel';
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
   : task.restricted ? <Section><Row label="來源" value="無來源讀取權限"/><Row label="範本" value={task.origin.template_family_id}/></Section>
   : <><Section>
     <Row label="範本" value={`${plain(template.template_family_id)} ${plain(template.revision)}`}/>
     <Row label="版本" value={plain(template.version_id)}/>
     <Row label="來源列" value={plain(row.source_row_key)}/>
     <Row label="位置" value={plain(row.source_locator)}/>
     <Row label="範圍" value={task.origin.instance_scope}/>
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
 const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
 const [title, setTitle] = useState(task.title), [instructions, setInstructions] = useState(task.instructions ?? '');
 const [people, setPeople] = useState(task.participants);
 const [due, setDue] = useState(task.dueDate || ''), [dueReason, setDueReason] = useState('');
 const [applicability, setApplicability] = useState<Applicability>(task.applicability), [appReason, setAppReason] = useState('');
 const names = new Map([...users,...sop.assignees].map(u => [u.id, u.name]));
 const candidates = sop.assignees;
 const editReason = task.allowedActions.includes('edit') ? '' : '不可編輯';
 const run = async (call: () => Promise<MutationResult>, done: string) => {
  setBusy(true); setError(''); setNotice('');
  try {await call(); await sop.reload(); if (sop.current()) setNotice(done)}
  catch (e) {
   if (!sop.current()) return;
   setError(sopErrorText(e));
   if (e instanceof SopError && (e.code === 'task_revision_conflict' || e.ambiguous)) await sop.reload();
  } finally {if (sop.current()) setBusy(false)}
 };
 const patch = (body: Record<string, unknown>, done: string) => run(() => sopApi.patch(project.id, task.id, {expected_revision: task.revision, ...body}, sop.current), done);
 const transition = (action: TaskAction|'set_applicability', extra: Record<string, unknown> = {}) => run(() => sopApi.transition(project.id, task.id, {expected_revision: task.revision, action, ...extra}, sop.current), '已更新狀態');
 const contentChanged = title.trim() !== task.title || (task.instructions !== null && instructions !== task.instructions);
 const peopleChanged = ROLES.some(r => (people[r] || '') !== (task.participants[r] || ''));
 const options = (role: Role) => {
  const current = task.participants[role];
  const list = current && !candidates.some(u => u.id === current) ? [{id: current, name: names.get(current) || '人員待確認'}, ...candidates] : candidates;
  return [<option key="" value="">未指派</option>, ...list.map(u => <option key={u.id} value={u.id}>{u.name}</option>)];
 };

 return createPortal(<Sheet title={`SOP 任務 · ${task.title}`} onClose={() => {if (!busy) onClose()}}>
  <div className="sop-inspector">
   <div className="sop-badges"><Badge tone="accent">SOP 任務</Badge><Badge>{stateLabel(task)}</Badge>{task.overdue && <Badge tone="critical">逾期</Badge>}{task.shared && <Badge>共用</Badge>}{task.applicability !== 'applicable' && <Badge tone="warning">{APPLICABILITY_LABEL[task.applicability]}</Badge>}</div>
   {error && <p role="alert" className="pg-callout">{error}</p>}
   {notice && <p role="status" className="sop-muted">{notice}</p>}
   <Section>
    <Row label="狀態" value={stateLabel(task)}/>
    <Row label="期限" value={dueLabel(task)}/>
    <Row label="節點" value={task.nodes.map(n => sopNodeLabel(n.node_key)).join('、') || '未連結節點'}/>
    {ROLES.map(r => <Row key={r} label={ROLE_LABEL[r]} value={task.participants[r] ? names.get(task.participants[r]!) || '人員待確認' : '未指派'}/>)}
   </Section>
   <div className="pf-actions sop-transitions" role="group" aria-label="狀態操作">{taskActions(task).map(a => a.reason
    ? <Reasoned key={a.action} label={a.label} busy={busy} onSubmit={reason => void transition(a.action, {reason})}/>
    : <FlowAction key={a.action} allowed={!busy} reason="處理中" onClick={() => void transition(a.action)}>{a.label}</FlowAction>)}</div>
   <form className="sop-form" onSubmit={e => {e.preventDefault(); if (contentChanged) void patch({title: title.trim(), ...(task.instructions !== null ? {instructions} : {})}, '已儲存內容')}}>
    <Field label="任務名稱"><input value={title} maxLength={500} disabled={!!editReason || busy} onChange={e => setTitle(e.target.value)}/></Field>
    {task.instructions !== null && <Field label="作法"><textarea rows={4} value={instructions} disabled={!!editReason || busy} onChange={e => setInstructions(e.target.value)}/></Field>}
    <Button type="submit" disabled={!!editReason || busy || !contentChanged || !title.trim()}>儲存內容</Button>
   </form>
   <form className="sop-form" onSubmit={e => {e.preventDefault(); if (peopleChanged) void patch({participants: Object.fromEntries(ROLES.filter(r => people[r]).map(r => [r, people[r]]))}, '已更新人員')}}>
    {ROLES.map(r => <Field key={r} label={`${ROLE_LABEL[r]}人員`}><select value={people[r] || ''} disabled={!!editReason || busy} onChange={e => setPeople(p => ({...p, [r]: e.target.value || undefined}))}>{options(r)}</select></Field>)}
    {sop.assigneeError && <small role="alert">{sop.assigneeError}</small>}{!candidates.length && <small className="sop-muted">無可指派人員</small>}
    <Button type="submit" disabled={!!editReason || busy || !peopleChanged}>儲存人員</Button>
   </form>
   <form className="sop-form" onSubmit={e => {e.preventDefault(); void patch({due_date: due || null, reason: dueReason.trim()}, '已更新期限')}}>
    <Field label="期限"><input type="date" value={due} disabled={!!editReason || busy} onChange={e => setDue(e.target.value)}/></Field>
    <Field label="期限原因"><input value={dueReason} maxLength={1000} disabled={!!editReason || busy} onChange={e => setDueReason(e.target.value)}/></Field>
    <Button type="submit" disabled={!!editReason || busy || (due || null) === task.dueDate || !dueReason.trim()}>儲存期限</Button>
   </form>
   {task.allowedActions.includes('set_applicability') && <form className="sop-form" onSubmit={e => {e.preventDefault(); void transition('set_applicability', {applicability, reason: appReason.trim()})}}>
    <Field label="適用"><select value={applicability} disabled={!!editReason || busy} onChange={e => setApplicability(e.target.value as Applicability)}>{(Object.keys(APPLICABILITY_LABEL) as Applicability[]).map(a => <option key={a} value={a}>{APPLICABILITY_LABEL[a]}</option>)}</select></Field>
    <Field label="適用原因"><input value={appReason} maxLength={1000} disabled={!!editReason || busy} onChange={e => setAppReason(e.target.value)}/></Field>
    <Button type="submit" disabled={!!editReason || busy || applicability === task.applicability || !appReason.trim()}>儲存適用</Button>
   </form>}
   <TaskSuggestion projectId={project.id} task={task} current={sop.current} reload={sop.reload} onAccept={()=>setReview(true)}/><Provenance task={task}/>{review && <SuggestionReview projectId={project.id} tasks={'data' in sop.state ? sop.state.data?.tasks||[] : []} initial={[task.id]} current={sop.current} reload={sop.reload} onClose={()=>setReview(false)}/>}
  </div>
 </Sheet>, document.body);
}
