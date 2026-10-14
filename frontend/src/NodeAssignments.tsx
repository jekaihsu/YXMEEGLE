import {useEffect, useMemo, useId, useRef, useState, type FormEvent, type ReactNode} from 'react';
import {ArrowRight, ChevronDown, Clock3, Loader2, Plus, RefreshCw, ShieldCheck, TriangleAlert, UserPlus, Users} from 'lucide-react';
import {getSessionEpoch} from './api';
import {NODE_ASSIGNMENT_ORDER, overviewDetail, assignmentErrorMessage, assignmentsDisabled, fetchNodeAssignmentDetail, nodeStatusLabel, taskStatusLabel, taskStatusValue, TASK_STATUS_OPTIONS,
  type AssignmentNode, type AssignmentPerson, type AssignmentMutation, type NewAssignmentTask, type NodeAssignmentDetail, type NodeAssignmentError, type NodePermissions, type NodeAssignmentList} from './nodeAssignmentApi';
import {useNodeAssignments} from './useNodeAssignments';
import './NodeAssignments.css';

const deadlineLabel = (value: string | null) => value ? value.slice(0, 10).replaceAll('-', '/') : '未排定';
const statusTone = (status: string) => {const label = nodeStatusLabel(status); return label === '已完成' ? 'done' : label === '進行中' ? 'active' : label === '待審核' ? 'review' : label === '待處理' ? 'pending' : label === '略過' ? 'skipped' : 'quiet'};
function StatusChip({status}: {status: string}) {
  const label = nodeStatusLabel(status);
  const tone = statusTone(status);
  return <span className={`na-status na-status-${tone}`}>{label}</span>;
}
function People({people, compact = false}: {people: AssignmentPerson[]; compact?: boolean}) {
  return <span className="na-people">{people.length ? (compact ? people.slice(0, 3) : people).map(p => <span className="na-person" key={p.open_id}><span className={`na-avatar na-person-color-${personColor(p.open_id)}`} aria-hidden="true">{p.name.slice(0, 1)}</span><span>{p.name}</span></span>) : <span className="na-muted">尚未指派</span>}{compact && people.length > 3 && <span className="na-muted">+{people.length - 3}</span>}</span>;
}
const personColor = (id: string) => Array.from(id).reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 0) % 6;
const FLOW_LABELS: Record<string, string> = {sales: '業務', pm: 'PM', confirmation: '確認單', field: '外業', control: '控制', mapping: '圖資', report: '報告', pricing: '計價', settlement: '結算'};
const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
function Overview({data, selected = '', onSelect}: {data?: NodeAssignmentList; selected?: string; onSelect?: (key: string) => void}) {
  const card = (key: string) => {
    const n = data?.nodes.find(n => n.key === key), label = n?.label || FLOW_LABELS[key];
    const status = n ? nodeStatusLabel(n.derived_status) : '', done = status === '已完成' || status === '略過';
    const overdue = !!n?.deadline && !done && new Date(n.deadline.length === 10 ? `${n.deadline}T23:59:59+08:00` : n.deadline).getTime() < Date.now();
    const percent = n ? Math.round(Math.min(1, n.progress) * 100) : 0;
    const hint = n ? actionHint(n, data?.writes_enabled ? data.can[key] || {} : {}) : '';
    return <button key={key} className={`na-flow-card na-card-${statusTone(n?.derived_status || '')}${data?.summary.current_node === key ? ' is-current' : ''}${selected === key ? ' is-selected' : ''}${!data ? ' is-skeleton' : ''}`} disabled={!n} aria-current={data?.summary.current_node === key ? 'step' : undefined} aria-expanded={n ? selected === key : undefined} aria-label={`${label}節點，${status || '讀取中'}，${n?.owners.map(p => p.name).join('、') || '尚未指派'}`} onClick={() => onSelect?.(key)}>
      <span className="na-card-top"><strong>{label}</strong>{n ? <StatusChip status={n.derived_status}/> : <span className="na-placeholder na-placeholder-status"/>}</span>
      {n ? <People people={n.owners} compact/> : <span className="na-placeholder na-placeholder-people"/>}
      <span className="na-card-progress">{n ? <><span>{n.tasks.done}/{n.tasks.total} 項任務</span><strong>{percent}%</strong></> : <span className="na-placeholder"/>}</span>
      <span className="na-progress-track" aria-hidden="true"><span style={{width: `${percent}%`}}/></span>
      <span className={`na-card-deadline${overdue ? ' is-overdue' : ''}`}>{n ? <><Clock3 size={12}/>{deadlineLabel(n.deadline)}{overdue && <strong>逾期</strong>}</> : <span className="na-placeholder"/>}</span>
      {n && <span className="na-card-footer"><span className={hint ? 'needs-action' : 'na-muted'}>{hint || '檢視交接'}</span>{!!n.warnings.length && <span className="na-warning-dot" title={n.warnings.join('、')} aria-label="有節點警告"/>}</span>}
    </button>;
  };
  const arrow = (keys: readonly string[]) => <ArrowRight className={`na-flow-arrow${data && keys.every(key => nodeStatusLabel(data.nodes.find(n => n.key === key)?.derived_status || '') === '已完成') ? ' is-done' : ''}`} size={18} aria-hidden="true"/>;
  return <><div className="na-overview" aria-label="案件流程總覽" aria-busy={!data}>
    <div className="na-flow-group na-leading" aria-label="接案與確認">{NODE_ASSIGNMENT_ORDER.slice(0, 3).map((key, i) => <div className="na-flow-unit" key={key}>{card(key)}{i < 2 && arrow([key])}</div>)}</div>
    {arrow(['confirmation'])}<div className="na-production" aria-label="生產作業"><div className="na-production-label">生產作業 <span>· 依工項交接，可並行處理</span></div><div className="na-production-cards">{NODE_ASSIGNMENT_ORDER.slice(3, 7).map(card)}</div></div>
    {arrow(NODE_ASSIGNMENT_ORDER.slice(3, 7))}<div className="na-flow-group na-ending" aria-label="計價與結算">{card('pricing')}{arrow(['pricing'])}{card('settlement')}</div>
  </div><div className="na-flow-legend" aria-label="流程圖例">{['未開始', '待處理', '進行中', '待審核', '已完成', '略過'].map(status => <StatusChip key={status} status={status}/>)}<span>彩色頭像 · 節點負責人</span><span>外框 · 目前節點</span></div></>;
}
function ActionButton({allowed, busy, children, onClick, type = 'button', reason, primary = false}: {
  allowed: boolean; busy: boolean; children: ReactNode; onClick?: () => void; type?: 'button' | 'submit'; reason?: string; primary?: boolean;
}) {
  const id = useId();
  const explanation = reason || (busy ? '正在儲存，請稍候。' : '目前沒有此操作權限，或節點狀態不允許此操作。');
  const disabled = !allowed || busy;
  return <span className="na-action-wrap" title={disabled ? explanation : undefined} tabIndex={disabled ? 0 : undefined}>
    <button type={type} className={`button compact${primary ? ' primary' : ''}`} disabled={disabled} aria-describedby={disabled ? id : undefined} onClick={onClick}>{children}</button>
    {disabled && <span id={id} className="na-sr-only">{explanation}</span>}
  </span>;
}
function ErrorBanner({message, retry, busy = false}: {message: string; retry?: () => void; busy?: boolean}) {
  return <div className="na-banner na-error" role="alert"><TriangleAlert size={17}/><span>{message}</span>{retry && <button className="text-button" disabled={busy} onClick={retry}>重試</button>}</div>;
}
function actionHint(n: AssignmentNode, can: NodePermissions): string {
  const status = nodeStatusLabel(n.derived_status);
  if (status === '已完成' || status === '略過') return '';
  if (status === '待審核' && (can.approve || can.reject)) return '待你審核';
  if (!n.owners.length && can.claim) return '待你認領';
  return can.complete ? '待你處理' : '';
}
export function NodeAssignments({projectId, enabled = false, legacy, before}: {projectId: string; enabled?: boolean; legacy: ReactNode; before?: ReactNode}) {
  const assignments = useNodeAssignments(projectId, enabled);
  const [expanded, setExpanded] = useState('');
  const listRef = useRef<HTMLOListElement>(null);
  const listId = useId();
  const {state, refreshing, pending, notice, error} = assignments;
  const data = 'data' in state ? state.data : undefined;
  const details = useMemo(() => data ? Object.fromEntries(data.nodes.map(n => [n.key, overviewDetail(data, n)])) : {}, [data]);
  useEffect(() => {if (expanded) document.getElementById(`${listId}-${expanded}`)?.scrollIntoView({behavior: reducedMotion(), block: 'nearest'})}, [expanded, listId]);
  if (state.kind === 'disabled') return <>{legacy}</>;
  if (!data) return <>
    {state.kind === 'error' && <ErrorBanner message={state.message} retry={() => void assignments.reload()} busy={refreshing}/>}
    {before}<section className="node-assignments" aria-label="案件節點指派"><header className="na-heading"><div><p className="na-eyebrow">流程與交付</p><h2>案件流程</h2><p role="status">正在讀取節點與交接進度…</p></div></header><Overview/></section>
  </>;
  const finished = data.summary.total > 0 && data.summary.done >= data.summary.total;
  const summaryLabel = finished ? '已完成' : '進行中';
  const jumpToList = () => {listRef.current?.scrollIntoView({behavior: reducedMotion(), block: 'start'}); listRef.current?.focus({preventScroll: true})};
  return <>{before}<section className="node-assignments" aria-label="案件節點指派">
    <header className="na-heading"><div><p className="na-eyebrow">流程與交付</p><h2>案件流程</h2><p>從接案到結算，掌握每一次交接。</p></div>
      <button className="na-summary" aria-controls={listId} onClick={jumpToList}><span className="na-summary-count">{data.summary.done}/{data.summary.total}</span><span><strong>{summaryLabel}</strong><small>節點完成 · 查看清單</small></span><ArrowRight size={18}/></button>
    </header>
    <Overview data={data} selected={expanded} onSelect={key => {setExpanded(key === expanded ? '' : key); assignments.clearFeedback()}}/>
    {!data.writes_enabled && <div className="na-banner na-stale" role="status">{data.writes_disabled_reason || '節點修改已停用。'}</div>}
    {data.stale && <div className="na-banner na-stale" role="status"><Clock3 size={17}/><span>目前顯示上次同步的資料，Lark 資料可能尚未更新。</span><button className="text-button" disabled={refreshing} onClick={() => void assignments.reload()}>重新讀取</button></div>}
    {state.kind === 'error' && <ErrorBanner message={state.message} retry={() => void assignments.reload()} busy={refreshing}/>}
    {notice && <div className="na-banner na-notice" role="status">{notice}</div>}
    {error && <ErrorBanner message={assignmentErrorMessage(error)} retry={error.code === 'outcome_unknown' || error.code === 'readback_mismatch' ? () => void assignments.retryMutation() : undefined} busy={!!pending || !data.writes_enabled || refreshing}/>}
    <div className="na-list-heading"><h3>節點清單 <span>{data.nodes.length} 個節點</span></h3><button className="text-button" disabled={refreshing || !!pending} onClick={() => void assignments.reload()}><RefreshCw size={14} className={refreshing ? 'spin' : ''}/>{refreshing ? '更新中…' : '重新讀取'}</button></div>
    <div className="na-columns" aria-hidden="true"><span>節點 / 狀態</span><span>任務進度</span><span>負責人</span><span>下個期限</span><span>待辦提示</span><span/></div>
    <ol id={listId} className="na-list" ref={listRef} tabIndex={-1} aria-label="案件節點清單">{data.nodes.map((n, i) => {
      const can = data.writes_enabled ? data.can[n.key] || {} : {}, hint = actionHint(n, can), open = expanded === n.key, panelId = `${listId}-${n.key}`;
      return <li key={n.key} className={`na-list-item${open ? ' is-expanded' : ''}`}>
        <button className="na-row" aria-label={`${n.label}節點，${nodeStatusLabel(n.derived_status)}，${n.tasks.done}/${n.tasks.total} 項任務`} aria-expanded={open} aria-controls={panelId} onClick={() => {setExpanded(open ? '' : n.key); assignments.clearFeedback()}}>
          <span className="na-node-cell"><span className="na-index">{String(i + 1).padStart(2, '0')}</span><span><strong>{n.label}</strong><StatusChip status={n.derived_status}/></span></span>
          <span className="na-progress-cell"><strong>{n.tasks.done}/{n.tasks.total}</strong><span className="na-progress-track" aria-hidden="true"><span style={{width: `${n.tasks.total ? Math.min(100, n.tasks.done / n.tasks.total * 100) : 0}%`}}/></span><small className="na-mobile-label">項任務完成</small></span>
          <People people={n.owners}/><span className="na-deadline"><span className="na-mobile-label">下個期限 </span>{deadlineLabel(n.deadline)}</span>
          <span className={`na-hint${hint ? ' needs-action' : ''}`}>{hint || '檢視進度'}</span><ChevronDown size={17} className="na-chevron"/>
        </button>
        {open && <div id={panelId}><NodeDetail key={n.key} projectId={projectId} node={n} initialDetail={details[n.key]} revision={assignments.revision} listBlocked={!data.writes_enabled || refreshing || state.kind === 'error'} pending={pending} error={error} mutate={assignments.mutate} onAbandon={assignments.clearFeedback} onDisabled={() => void assignments.reload()}/></div>}
      </li>;
    })}</ol>
    {!data.nodes.length && <p className="na-empty">尚未建立節點指派。重新讀取後再確認。</p>}
  </section></>;
}

type DetailState = {kind: 'loading'} | {kind: 'ready'; data: NodeAssignmentDetail; refreshing: boolean} | {kind: 'error'; message: string; data?: NodeAssignmentDetail};
type Mutate = (mutation: AssignmentMutation) => Promise<boolean>;
function NodeDetail({projectId, node, initialDetail, revision, listBlocked, pending, error, mutate, onAbandon, onDisabled}: {
  projectId: string; node: AssignmentNode; initialDetail?: NodeAssignmentDetail; revision: number; listBlocked: boolean; pending: string; error: NodeAssignmentError | null; mutate: Mutate; onAbandon: () => void; onDisabled: () => void;
}) {
  const [state, setState] = useState<DetailState>(() => initialDetail ? {kind: 'ready', data: initialDetail, refreshing: false} : {kind: 'loading'});
  const [retry, setRetry] = useState(0);
  const [form, setForm] = useState<'assign' | 'task' | 'reject' | ''>('');
  const [changedTask, setChangedTask] = useState('');
  const detailId = useId();
  useEffect(() => {
    if (initialDetail) {setState({kind: 'ready', data: initialDetail, refreshing: false}); return}
    const controller = new AbortController(), epoch = getSessionEpoch();
    const current = () => !controller.signal.aborted && epoch === getSessionEpoch();
    setState(previous => 'data' in previous && previous.data ? {kind: 'ready', data: previous.data, refreshing: true} : {kind: 'loading'});
    void fetchNodeAssignmentDetail(projectId, node.key, controller.signal, current).then(data => {
      if (current()) setState({kind: 'ready', data, refreshing: false});
    }).catch(failure => {
      if (!current()) return;
      if (assignmentsDisabled(failure)) onDisabled();
      setState(previous => ({kind: 'error', message: assignmentErrorMessage(failure), data: 'data' in previous ? previous.data : undefined}));
    });
    return () => controller.abort();
  }, [projectId, node.key, revision, retry, initialDetail]);
  const data = initialDetail || ('data' in state ? state.data : undefined);
  if (!data) return <section className="na-detail" aria-label={`${node.label}節點明細`}>{state.kind === 'loading' ? <p className="na-loading" role="status"><Loader2 size={16} className="spin"/>正在讀取負責人與任務…</p>
    : state.kind === 'error' && <ErrorBanner message={state.message} retry={() => setRetry(r => r + 1)}/>}</section>;
  const can = data.can;
  const busy = !data.writes_enabled || listBlocked || !!pending || state.kind !== 'ready' || state.refreshing;
  const busyReason = !data.writes_enabled ? data.writes_disabled_reason || '節點修改已停用。' : state.kind === 'error' ? '明細更新失敗，請重試後操作。' : '正在更新節點資料，請稍候。';
  const changeForm = (next: typeof form) => {onAbandon(); setForm(next)};
  const save = async (mutation: AssignmentMutation) => {if (await mutate(mutation)) setForm('')};
  return <section className="na-detail" aria-label={`${node.label}節點明細`} aria-busy={busy}>
    {state.kind === 'error' && <ErrorBanner message={state.message} retry={() => setRetry(r => r + 1)}/>}
    {!data.writes_enabled && <div className="na-banner na-stale" role="status">{data.writes_disabled_reason || '節點修改已停用。'}</div>}
    <div className="na-detail-heading"><div><h3>{node.label}交接與任務</h3><p>負責人共同維護進度，完成後送交審核。</p></div>{(!!pending || (state.kind === 'ready' && state.refreshing)) && <span className="na-loading" role="status"><Loader2 size={14} className="spin"/>{pending ? '儲存中…' : '更新中…'}</span>}</div>
    <div className="na-owner-section"><div><span className="na-field-label">節點負責人</span><People people={data.node.owners}/></div><div className="na-actions">
      <ActionButton allowed={can.claim === true} busy={busy} reason={busy ? busyReason : undefined} onClick={() => void save({action: 'claim', nodeKey: node.key, expected_revision: data.node.revision})}><UserPlus size={15}/>認領節點</ActionButton>
      <ActionButton allowed={can.assign === true} busy={busy} reason={busy ? busyReason : undefined} onClick={() => changeForm(form === 'assign' ? '' : 'assign')}><Users size={15}/>指派負責人</ActionButton>
    </div></div>
    <dl className="na-facts">{data.node.assigned_by && <div><dt>指派人</dt><dd>{data.node.assigned_by.name}</dd></div>}{data.node.approver && <div><dt>審核人</dt><dd>{data.node.approver.name}</dd></div>}{data.node.approved_at && <div><dt>核准日期</dt><dd>{deadlineLabel(data.node.approved_at)}</dd></div>}<div><dt>節點期限</dt><dd>{deadlineLabel(data.node.deadline)}</dd></div></dl>
    {data.node.reject_reason && <div className="na-banner na-stale"><span>退回原因 · {data.node.reject_reason}</span></div>}
    {!!data.node.warnings.length && <ul className="na-warnings">{data.node.warnings.map((warning, i) => <li key={i}><TriangleAlert size={14}/>{warning}</li>)}</ul>}
    {form === 'assign' && <AssignForm detail={data} busy={busy} error={error} onCancel={() => changeForm('')} onSubmit={assignees => save({action: 'assign', nodeKey: node.key, owner_open_ids: assignees, expected_revision: data.node.revision})}/>}
    <div className="na-tasks-heading"><h4>節點任務 <span>{data.tasks.length} 項</span></h4><ActionButton allowed={can.create_task === true} busy={busy} reason={busy ? busyReason : undefined} onClick={() => changeForm(form === 'task' ? '' : 'task')}><Plus size={15}/>新增任務</ActionButton></div>
    {form === 'task' && <TaskCreator detail={data} busy={busy} error={error} onCancel={() => changeForm('')} onSubmit={task => save({action: 'create_task', nodeKey: node.key, task})}/>}
    <ul className="na-tasks">{data.tasks.map(task => <li key={task.id}><div className="na-task-body"><strong>{task.title}</strong>{task.detail && <p>{task.detail}</p>}<div className="na-task-meta"><span>{task.assignee?.name || '尚未指派'}</span><span>{task.department || '未設定部門'}</span><span><Clock3 size={13}/>{deadlineLabel(task.deadline)}</span></div></div>
      <label className="na-task-status" title={!(task.can.edit_status || task.can.cancel) ? '目前沒有更新任務狀態的權限。' : busy ? busyReason : undefined}><span>任務狀態</span><select aria-label={`${task.title}狀態`} value={taskStatusValue(task.status)} disabled={!(task.can.edit_status || task.can.cancel) || busy} aria-invalid={changedTask === task.id && !!error?.fields.status} aria-describedby={changedTask === task.id && error?.fields.status ? `${detailId}-${task.id}` : undefined} onChange={e => {setChangedTask(task.id); void mutate({action: 'update_task', nodeKey: node.key, taskId: task.id, expected_revision: task.revision, patch: {status: e.target.value}})}}>
        {!taskStatusValue(task.status) && <option value="">{taskStatusLabel(task.status)}</option>}{TASK_STATUS_OPTIONS.filter(([value]) => value === task.status || (value === '取消' ? task.can.cancel : task.can.edit_status)).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{!(task.can.edit_status || task.can.cancel) && <small>需有任務處理權限</small>}{changedTask === task.id && error?.fields.status && <small className="na-field-error" id={`${detailId}-${task.id}`} role="alert">{error.fields.status}</small>}</label>
    </li>)}</ul>
    {!data.tasks.length && <p className="na-empty">此節點尚無任務。新增任務後即可追蹤交付進度。</p>}
    <div className="na-review"><div><ShieldCheck size={19}/><span><strong>節點交接</strong><small>確認任務與成果後，再完成或審核此節點。</small></span></div><div className="na-actions">
      <ActionButton allowed={can.complete === true} busy={busy} primary reason={busy ? busyReason : undefined} onClick={() => void save({action: 'complete', nodeKey: node.key, expected_revision: data.node.revision})}>完成節點</ActionButton>
      <ActionButton allowed={can.approve === true} busy={busy} reason={busy ? busyReason : undefined} onClick={() => void save({action: 'approve', nodeKey: node.key, expected_revision: data.node.revision})}>核准</ActionButton>
      <ActionButton allowed={can.reject === true} busy={busy} reason={busy ? busyReason : undefined} onClick={() => changeForm(form === 'reject' ? '' : 'reject')}>退回</ActionButton>
    </div></div>
    {form === 'reject' && <RejectForm busy={busy} error={error} onCancel={() => changeForm('')} onSubmit={reason => save({action: 'reject', nodeKey: node.key, reason, expected_revision: data.node.revision})}/>}
  </section>;
}

function AssignForm({detail, busy, error, onCancel, onSubmit}: {detail: NodeAssignmentDetail; busy: boolean; error: NodeAssignmentError | null; onCancel: () => void; onSubmit: (ids: string[]) => Promise<void>}) {
  const [selected, setSelected] = useState(detail.node.owners.filter(p => detail.assignable_people.some(candidate => candidate.open_id === p.open_id)).map(p => p.open_id));
  const [validation, setValidation] = useState('');
  const submit = (event: FormEvent) => {event.preventDefault(); const ids = selected.filter(id => detail.assignable_people.some(p => p.open_id === id)); if (!ids.length || ids.length > 20) {setValidation('請選擇 1 至 20 位負責人。'); return} setValidation(''); void onSubmit(ids)};
  return <form className="na-form" onSubmit={submit}><fieldset disabled={busy}><legend>選擇節點負責人</legend><div className="na-person-options">{detail.assignable_people.map(p => <label key={p.open_id}><input type="checkbox" checked={selected.includes(p.open_id)} onChange={e => setSelected(ids => e.target.checked ? [...ids, p.open_id] : ids.filter(id => id !== p.open_id))}/><span>{p.name}<small>{p.departments.join('、')}</small></span></label>)}</div>
    {!detail.assignable_people.length && <p className="na-empty">目前沒有可指派人員，請聯絡管理員。</p>}{(validation || error?.fields.owner_open_ids) && <p className="na-field-error" role="alert">{validation || error?.fields.owner_open_ids}</p>}
    <div className="na-form-actions"><button type="button" className="button compact" onClick={onCancel}>取消</button><button className="button primary compact" type="submit" disabled={!detail.assignable_people.length}>儲存指派</button></div></fieldset></form>;
}
function TaskCreator({detail, busy, error, onCancel, onSubmit}: {detail: NodeAssignmentDetail; busy: boolean; error: NodeAssignmentError | null; onCancel: () => void; onSubmit: (task: NewAssignmentTask) => Promise<void>}) {
  const [draft, setDraft] = useState<NewAssignmentTask>({title: '', detail: '', assignee_open_id: '', department: '', deadline: ''});
  const [validation, setValidation] = useState<Record<string, string>>({});
  const id = useId(), fields = {...error?.fields, ...validation};
  const departments = [...new Set(draft.assignee_open_id ? detail.assignable_people.find(p => p.open_id === draft.assignee_open_id)?.departments || [] : detail.node.departments)];
  const update = (field: keyof NewAssignmentTask, value: string) => {setDraft(d => ({...d, [field]: value, ...(field === 'assignee_open_id' ? {department: ''} : {})})); setValidation(v => {const next = {...v}; delete next[field]; return next})};
  const submit = (event: FormEvent) => {
    event.preventDefault(); const errors: Record<string, string> = {};
    if (!draft.title.trim()) errors.title = '請填寫任務名稱。';
    setValidation(errors); if (!Object.keys(errors).length) void onSubmit({...draft, title: draft.title.trim(), detail: draft.detail.trim()});
  };
  const invalid = (field: string) => ({'aria-invalid': !!fields[field], 'aria-describedby': fields[field] ? `${id}-${field}` : undefined});
  const fieldError = (field: string) => fields[field] && <small className="na-field-error" id={`${id}-${field}`} role="alert">{fields[field]}</small>;
  return <form className="na-form" noValidate onSubmit={submit}><fieldset disabled={busy}><legend>新增節點任務</legend><div className="na-form-grid">
    <label className="na-wide"><span>任務名稱 <small>必填</small></span><input value={draft.title} required {...invalid('title')} onChange={e => update('title', e.target.value)} placeholder="例如 控制點成果核對"/>{fieldError('title')}</label>
    <label className="na-wide"><span>任務說明</span><textarea value={draft.detail} {...invalid('detail')} onChange={e => update('detail', e.target.value)} rows={3} placeholder="補充作業範圍與交付內容"/>{fieldError('detail')}</label>
    {detail.assignable_people.length > 0 && <label><span>負責人 <small>{detail.can.assign ? '未選擇則建立未指派任務' : '未選擇則由自己負責'}</small></span><select value={draft.assignee_open_id} {...invalid('assignee_open_id')} onChange={e => update('assignee_open_id', e.target.value)}><option value="">選擇負責人</option>{detail.assignable_people.map(p => <option key={p.open_id} value={p.open_id}>{p.name}</option>)}</select>{fieldError('assignee_open_id')}</label>}
    <label><span>部門</span><select value={draft.department} {...invalid('department')} onChange={e => update('department', e.target.value)}><option value="">選擇部門</option>{departments.map(d => <option key={d} value={d}>{d}</option>)}</select>{fieldError('department')}</label>
    <label><span>期限 <small>僅日期</small></span><input type="date" value={draft.deadline} {...invalid('deadline')} onChange={e => update('deadline', e.target.value)}/>{fieldError('deadline')}</label>
  </div><div className="na-form-actions"><button type="button" className="button compact" onClick={onCancel}>取消</button><button type="submit" className="button primary compact">建立任務</button></div></fieldset></form>;
}
function RejectForm({busy, error, onCancel, onSubmit}: {busy: boolean; error: NodeAssignmentError | null; onCancel: () => void; onSubmit: (reason: string) => Promise<void>}) {
  const [reason, setReason] = useState(''), [validation, setValidation] = useState('');
  const id = useId(), message = validation || error?.fields.reason;
  const submit = (event: FormEvent) => {event.preventDefault(); if (!reason.trim()) {setValidation('請填寫退回原因。'); return} setValidation(''); void onSubmit(reason.trim())};
  return <form className="na-form" noValidate onSubmit={submit}><fieldset disabled={busy}><legend>退回節點</legend><label><span>退回原因 <small>必填</small></span><textarea rows={3} value={reason} required aria-invalid={!!message} aria-describedby={message ? id : undefined} onChange={e => {setReason(e.target.value); setValidation('')}}/></label>{message && <p id={id} className="na-field-error" role="alert">{message}</p>}
    <div className="na-form-actions"><button type="button" className="button compact" onClick={onCancel}>取消</button><button type="submit" className="button primary compact">確認退回</button></div></fieldset></form>;
}
