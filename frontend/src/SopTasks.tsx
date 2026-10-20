import {createPortal} from 'react-dom';
import {useState} from 'react';
import {Badge, Button, Sheet, Skeleton} from './design';
import {FlowAction} from './FlowActions';
import {isSopNode, sopApi, sopErrorText, sopNodeLabel, type SopNodeKey, type SopTask} from './sopTaskApi';
import {checklistComplete, countTasks, dueLabel, FILTERS, progressLabel, stateLabel, visibleTasks, type SopFilter} from './sopTaskModel';
import {SopImportSheet} from './SopImportSheet';
import {SopTaskInspector} from './SopTaskInspector';
import type {useSopTasks} from './useSopTasks';
import type {Ctx} from './appCommon';
import type {Project} from './types';
import './SopTasks.css';

export const SOP_TASK_SOURCE = 'sop_local';
export type SopImportTarget = 'case'|SopNodeKey|null;
type Sop = ReturnType<typeof useSopTasks>;

function TaskLine({task, people, scoped, onOpen}: {task: SopTask; people: Map<string, string>; scoped: boolean; onOpen: () => void}) {
 const executor = task.participants.executor;
 return <li data-sop-task={task.id}><button className="pf-task-open" onClick={onOpen} aria-label={`開啟 SOP 任務 ${task.title}`}>
  <strong>{task.title}</strong>
  <span>{executor ? people.get(executor) || '人員待確認' : '未指派'} · {stateLabel(task)} · {dueLabel(task)}
   {task.overdue && <Badge tone="critical">逾期</Badge>}{task.nodes.length > 1 && <Badge>共用</Badge>}{task.applicability === 'unresolved' && <Badge tone="warning">條件</Badge>}{task.manual && <Badge>手動</Badge>}</span>
  {!scoped && <small>{task.nodes.map(n => sopNodeLabel(n.node_key)).join('、') || '未連結節點'}</small>}
 </button></li>;
}

function CreateTask({projectId, node, current, onDone, onClose}: {projectId: string; node: SopNodeKey; current: () => boolean; onDone: () => Promise<void>; onClose: () => void}) {
 const [title, setTitle] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('');
 const submit = async () => {
  if (!title.trim() || busy) return;
  setBusy(true); setError('');
  try {await sopApi.create(projectId, {title: title.trim(), node_keys: [node]}, current); await onDone(); onClose()}
  catch (e) {if (current()) setError(sopErrorText(e))}
  finally {if (current()) setBusy(false)}
 };
 return createPortal(<Sheet title={`新增 SOP 任務 · ${sopNodeLabel(node)}`} onClose={() => {if (!busy) onClose()}}>
  <form className="sop-form" onSubmit={e => {e.preventDefault(); void submit()}}>
   <label>任務名稱<input value={title} maxLength={500} onChange={e => setTitle(e.target.value)} required/></label>
   {error && <p role="alert">{error}</p>}
   <div className="sop-sheet-actions"><Button onClick={onClose} disabled={busy}>取消</Button><Button type="submit" variant="primary" disabled={!title.trim() || busy} disabledReason="請輸入任務名稱">{busy ? '新增中…' : '新增'}</Button></div>
  </form>
 </Sheet>, document.body);
}

export function SopTasks({c, p, nodeKey, sop, importing, setImporting}: {c: Ctx; p: Project; nodeKey: string; sop: Sop; importing: SopImportTarget; setImporting: (target: SopImportTarget) => void}) {
 const [wholeCase, setWholeCase] = useState(false);
 const [filters, setFilters] = useState<SopFilter[]>([]);
 const [history, setHistory] = useState(false);
 const [creating, setCreating] = useState(false);
 const node = isSopNode(nodeKey) ? nodeKey : undefined;
 const scope = wholeCase ? undefined : node;
 const {state} = sop;
 const data = 'data' in state ? state.data : undefined;
 const me = c.s.user?.id || '';
 const people = new Map(c.w.users.map(u => [u.id, u.name]));
 const routeTask = c.route.task_source === SOP_TASK_SOURCE ? c.route.task : undefined;
 const openTask = data?.tasks.find(t => t.id === routeTask);
 const openRoute = (task?: string) => c.go({...c.route, tab: 'flow', task, task_source: task ? SOP_TASK_SOURCE : undefined});
 const toggle = (f: SopFilter) => setFilters(list => list.includes(f) ? list.filter(x => x !== f) : [...list, f]);
 const rows = data ? visibleTasks(data.tasks, {scope, filters, history}, me) : [];
 const counts = data ? (scope ? data.nodeCounts[scope] : data.caseCounts) : undefined;
 const filtered = filters.length > 0 || history;
 const allowed = data?.allowed;
 if (state.kind === 'forbidden') return <section id="sop-tasks" className="pf-tasks sop-tasks" aria-label="SOP 任務"><header><h3>SOP 任務</h3><span className="sop-muted">無 SOP 任務權限</span></header></section>;
 return <section id="sop-tasks" className="pf-tasks sop-tasks" aria-label="SOP 任務" tabIndex={-1}>
  <header>
   <h3>SOP 任務{counts && <span className="sop-progress" aria-label={`完成 ${progressLabel(counts)}`}>{progressLabel(counts)}</span>}{counts && checklistComplete(counts) && <Badge tone="positive">檢查清單已完成</Badge>}</h3>
   <div className="pf-actions">
    {allowed && <FlowAction allowed={allowed.import} reason="需 SOP 匯入權限" onClick={() => setImporting('case')}>匯入預設任務</FlowAction>}
    {allowed && node && <FlowAction allowed={allowed.manage} reason="需 SOP 任務管理權限" onClick={() => setCreating(true)}>新增任務</FlowAction>}
   </div>
  </header>
  <div className="pf-filters sop-filters">
   <div className="pf-actions" role="group" aria-label="SOP 任務範圍">{node && <Button aria-pressed={!wholeCase} onClick={() => setWholeCase(false)}>此節點</Button>}<Button aria-pressed={wholeCase || !node} onClick={() => setWholeCase(true)}>全案</Button></div>
   <div className="pf-actions" role="group" aria-label="SOP 任務篩選">{FILTERS.map(([key, label]) => <Button key={key} aria-pressed={filters.includes(key)} onClick={() => toggle(key)}>{label}</Button>)}<Button aria-pressed={history} onClick={() => setHistory(h => !h)}>封存紀錄</Button></div>
   {counts && <span role="status" className="sop-counts">
    {filtered ? `篩選後 ${rows.length} 項` : `${rows.length} 項`}
    {!history && counts.unresolved > 0 && <Badge tone="warning">待確認 {counts.unresolved}</Badge>}
    {!history && counts.not_applicable > 0 && <Badge>不適用 {counts.not_applicable}</Badge>}
    {!history && counts.archived > 0 && <Badge>已封存 {counts.archived}</Badge>}
    {filtered && !history && <span>篩選後完成 {progressLabel(countTasks(rows))}</span>}
   </span>}
  </div>
  {state.kind === 'error' && <div role="alert" className="pg-callout">SOP 任務讀取失敗 · {state.message}<Button onClick={() => void sop.reload()}>重試 SOP 任務</Button></div>}
  {state.kind === 'loading' ? <div aria-label="SOP 任務載入中" aria-busy="true"><Skeleton lines={3} height="3.5rem"/></div>
   : data && (rows.length ? <ul className="pf-task-list">{rows.map(t => <TaskLine key={t.id} task={t} people={people} scoped={!!scope} onOpen={() => openRoute(t.id)}/>)}</ul>
    : <p className="pf-empty">{history ? '無封存任務' : filtered ? '沒有符合的任務' : '無 SOP 任務'}</p>)}
  {routeTask && data && !openTask && state.kind === 'ready' && !state.refreshing && <p role="alert">找不到此 SOP 任務 <Button onClick={() => openRoute()}>關閉</Button></p>}
  {openTask && data && <SopTaskInspector key={openTask.id} task={openTask} project={p} users={c.w.users} me={me} allowed={data.allowed} sop={sop} onClose={() => openRoute()}/>}
  {importing && data && <SopImportSheet projectId={p.id} startNode={data.startNode} only={importing === 'case' ? undefined : importing} onApplied={sop.reload} onClose={() => setImporting(null)} onOpenImported={() => {setImporting(null); setWholeCase(true); setFilters([]); setHistory(false); requestAnimationFrame(() => document.getElementById('sop-tasks')?.focus())}}/>}
  {creating && node && <CreateTask projectId={p.id} node={node} current={sop.current} onDone={sop.reload} onClose={() => setCreating(false)}/>}
 </section>;
}
