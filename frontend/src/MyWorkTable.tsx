// My Work Presentational UI (VCC-126).
// Pure presentational component: renders ONLY the output of buildMyWorkView from myWorkView.ts.
// Does NOT recompute any state, label, sort, or count.
// No fetch and no writes.

import {homeTarget} from './projectRoutes';
import { useRef, useEffect, useState } from 'react';
import {Avatar} from './Avatar';
import type {
  MyWorkView,
  MyWorkMode,
  MyWorkRow,
  MyWorkDetail,
  MyWorkAction,
} from './myWorkView.ts';
import { MY_WORK_LABELS, myWorkStatusText } from './myWorkView.ts';
import './my-work-table.css';

export interface MyWorkTableProps {
  view: MyWorkView;
  onSelect?: (id: string | null) => void;
  onModeChange?: (mode: MyWorkMode) => void;
  onSearch?: (search: string) => void;
  onNavigate?: (route: string) => void;
  /** Set when remounted by browser Back from a row navigation: focus the selected row, else the heading. */
  restoreFocus?: boolean;
  onFocusRestored?: () => void;
}

export function MyWorkTable({
  view,
  onSelect,
  onModeChange,
  onSearch,
  onNavigate,
  restoreFocus,
  onFocusRestored,
}: MyWorkTableProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const selectedId = view.filters.selectedId;
  const rowSelectButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const lastOpenedTaskIdRef = useRef<string | null>(null);
  const prevDrawerOpenRef = useRef(view.drawer.open);

  if (view.drawer.open && view.drawer.task) {
    lastOpenedTaskIdRef.current = view.drawer.task.id;
  }

  const restoreFocusToRow = () => {
    const targetId = lastOpenedTaskIdRef.current;
    if (targetId) {
      const btn = rowSelectButtonRefs.current.get(targetId);
      btn?.focus();
    }
  };

  const handleCloseDrawer = () => {
    onSelect?.(null);
    restoreFocusToRow();
  };

  useEffect(() => {
    if (prevDrawerOpenRef.current && !view.drawer.open) {
      restoreFocusToRow();
    }
    prevDrawerOpenRef.current = view.drawer.open;
  }, [view.drawer.open]);

  const loading = (view.pageState?.states as readonly string[] | undefined)?.includes('loading') ?? false;
  useEffect(() => {
    if (!restoreFocus || loading) return;
    const active = document.activeElement;
    if (!active || active === document.body) {
      const row = selectedId ? rowSelectButtonRefs.current.get(selectedId) : undefined;
      (row ?? headingRef.current)?.focus();
    }
    onFocusRestored?.();
  }, [restoreFocus, loading, selectedId, view.rows]);

  // Banner text handles every C-STATE value, including view.pageState null (clean complete read).
  // Unknown count is never rendered as 0.
  const bannerText =
    view.pageStateLabel !== null
      ? view.pageStateLabel
      : view.count !== null
      ? `完整讀取（${view.count} 筆）`
      : '完整讀取';

  const bannerStateClass = view.pageState
    ? view.pageState.states.join(' ')
    : 'ready';

  return (
    <div className="my-work-container">
      <div className="my-work-main-panel">
        <header className="my-work-header">
          <div className="my-work-title-group">
            <h2 ref={headingRef} tabIndex={-1}>我的工作</h2>
            <p className="my-work-subtitle">所有尚待處理事項，不限建立週次</p>
          </div>
        </header>

        {/* Toolbar: Mode Toggle (only when showModeToggle) and Search */}
        <div className="my-work-toolbar">
          {view.showModeToggle && (
            <div
              className="my-work-mode-toggle"
              role="group"
              aria-label="工作模式切換"
            >
              {view.modes.map((m) => (
                <button
                  key={m.mode}
                  type="button"
                  aria-pressed={view.mode === m.mode}
                  className={`my-work-mode-tab ${
                    view.mode === m.mode ? 'is-active' : ''
                  }`}
                  onClick={() => onModeChange?.(m.mode)}
                >
                  {m.label}
                </button>
              ))}
            </div>
          )}

          <div className="my-work-search-box">
            <input
              type="search"
              className="my-work-search-input"
              value={view.filters.search}
              onChange={(e) => onSearch?.(e.target.value)}
              placeholder="搜尋任務識別碼、任務或案件名稱…"
              aria-label="搜尋任務或案件"
            />
            {view.filters.search ? (
              <button
                type="button"
                className="my-work-search-clear"
                onClick={() => onSearch?.('')}
                aria-label="清除搜尋"
              >
                ×
              </button>
            ) : null}
          </div>
        </div>

        {/* Empty reads explain their state below instead of repeating the banner. */}
        {view.rows.length>0&&<div
          className={`my-work-page-state-banner state-${
            view.pageState ? view.pageState.states.join('-') : 'ready'
          }`}
          role="status"
          aria-live="polite"
          data-state={bannerStateClass}
        >
          <span className="my-work-banner-state-text">{bannerText}</span>
          {!view.dataAsOfLabel.endsWith(MY_WORK_LABELS.unknown)&&<span className="my-work-banner-as-of"> · {view.dataAsOfLabel}</span>}
          {view.selectionDropped && (
            <span className="my-work-selection-dropped-note">
              · 原選取項目已不再符合目前條件或已被移除
            </span>
          )}
        </div>}

        {/* Main Table or Distinct Empty State */}
        {view.rows.length === 0 ? (
          <div className="my-work-empty-container" role="status">
            {view.emptyReason === 'unassigned' && (
              <p className="my-work-empty-reason unassigned">尚未被指派工作</p>
            )}
            {view.emptyReason === 'no_pending' && (
              <p className="my-work-empty-reason no-pending">目前沒有待辦工作</p>
            )}
            {!view.emptyReason && (
              <p className="my-work-empty-reason generic">
                {view.pageState?.states.some(state=>state==='filtered_empty')?'沒有符合條件的工作。':view.pageState?.states.some(state=>state==='forbidden')?'沒有檢視工作資料的權限。':loading?'正在讀取工作…':`${view.pageStateLabel||'工作資料尚未完整'}，請重新讀取。`}
              </p>
            )}
          </div>
        ) : (
          <div
            className="my-work-table-scroll"
            tabIndex={0}
            aria-label="我的工作任務清單，可左右捲動"
          >
            <table className="my-work-table">
              <thead>
                <tr>
                  <th scope="col">任務識別 / 名稱</th>
                  <th scope="col">案件 / 工作項</th>
                  <th scope="col">負責人</th>
                  <th scope="col">狀態與原因</th>
                  <th scope="col">下一交付物</th>
                  <th scope="col">有效期限</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {view.rows.map((row: MyWorkRow) => {
                  const isSelected = selectedId === row.id;
                  return (
                    <tr
                      key={row.id}
                      className={`my-work-row ${
                        isSelected ? 'is-selected' : ''
                      } ${row.needsAttention ? 'needs-attention' : ''}`}
                      onClick={() => {
                        lastOpenedTaskIdRef.current = row.id;
                        onSelect?.(row.id);
                      }}
                      onKeyDown={(e) => {
                        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                          e.preventDefault();
                          lastOpenedTaskIdRef.current = row.id;
                          onSelect?.(row.id);
                        }
                      }}
                    >
                      <td>
                        <div className="my-work-cell-task">
                          <button
                            type="button"
                            id={`my-work-row-btn-${row.id}`}
                            data-row-select-id={row.id}
                            className="my-work-row-title-btn"
                            ref={(el) => {
                              if (el) {
                                rowSelectButtonRefs.current.set(row.id, el);
                              } else {
                                rowSelectButtonRefs.current.delete(row.id);
                              }
                            }}
                            aria-pressed={isSelected}
                            aria-label={`選取任務：${row.title===MY_WORK_LABELS.unknown?'未命名工作':row.title}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              lastOpenedTaskIdRef.current = row.id;
                              onSelect?.(row.id);
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                lastOpenedTaskIdRef.current = row.id;
                              }
                            }}
                          >
                            <strong>{row.title===MY_WORK_LABELS.unknown?'未命名工作':row.title}</strong>
                          </button>
                          {/* Outcome note shown verbatim */}
                          {row.outcomeNote && (
                            <div className="my-work-outcome-note" role="note">
                              {row.outcomeNote}
                            </div>
                          )}
                        </div>
                      </td>

                      <td>
                        <div className="my-work-cell-case">
                          <span>{row.caseTitle===MY_WORK_LABELS.unknown?'':row.caseTitle}</span>
                          <small>{row.workItemTitle===MY_WORK_LABELS.unknown?'':row.workItemTitle}</small>
                        </div>
                      </td>

                      <td>
                        <span>{row.assignee===MY_WORK_LABELS.unknown?'':row.assignee}</span>
                      </td>

                      <td><span className={`my-work-status-text ${row.needsAttention?'status-attention':''}`}>{myWorkStatusText(row)}</span></td>

                      <td>
                        <span>{row.nextDeliverable===MY_WORK_LABELS.unknown?'':row.nextDeliverable}</span>
                      </td>

                      {/* Effective due date: verified formal field only or unknown text, never 0 */}
                      <td>
                        <span className="my-work-due-text">{row.dueLabel===MY_WORK_LABELS.unknown?'期限未提供':row.dueLabel}</span>
                      </td>

                      {/* Actions: navigation links/buttons calling onNavigate(route) only */}
                      {/* NO Complete/Approve/submit controls */}
                      <td>
                        <div className="my-work-actions">
                          {row.actions.map((act: MyWorkAction) => (
                            <button
                              key={act.kind}
                              type="button"
                              className="my-work-action-button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onNavigate?.(act.route);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.stopPropagation();
                                }
                              }}
                            >
                              {act.label}
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Weekly activity: separate dataset and date control */}
        {view.weekly &&
          (view.weekly.period.start ||
            view.weekly.period.end ||
            view.weekly.items.length > 0) && (
            <section
              className="my-work-weekly-section"
              aria-label="每週活動紀錄"
            >
              <header className="my-work-weekly-header">
                <h3>每週活動紀錄</h3>
                <span className="my-work-weekly-period">
                  區間：{view.weekly.period.start ?? '未提供'} ~{' '}
                  {view.weekly.period.end ?? '未提供'}
                </span>
              </header>
              {view.weekly.items.length === 0 ? (
                <p className="my-work-weekly-empty">本週尚無活動紀錄</p>
              ) : (
                <ul className="my-work-weekly-list">
                  {view.weekly.items.map((item) => (
                    <li key={item.id}>
                      <span>{item.date}</span>
                      <strong>{item.title}</strong>
                      <small>{item.id}</small>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
      </div>

      {/* Detail Drawer: only after selection */}
      {view.drawer.open && view.drawer.task && (
        <aside
          className="my-work-drawer"
          aria-label="任務詳情面板"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation();
              handleCloseDrawer();
            }
          }}
        >
          <header className="my-work-drawer-header">
            <div className="my-work-drawer-title-group">
              <h3 className="my-work-drawer-title">{view.drawer.task.title===MY_WORK_LABELS.unknown?'未命名工作':view.drawer.task.title}</h3>
              <span className="my-work-drawer-task-id">
                {view.drawer.task.id}
              </span>
            </div>
            <button
              type="button"
              className="my-work-drawer-close"
              onClick={handleCloseDrawer}
              aria-label="關閉詳情面板"
            >
              ×
            </button>
          </header>

          <div className="my-work-drawer-body">
            {/* Outcome note shown verbatim */}
            {view.drawer.task.outcomeNote && (
              <div className="my-work-drawer-outcome-note" role="note">
                {view.drawer.task.outcomeNote}
              </div>
            )}

            {/* Task Information */}
            <section className="my-work-drawer-section">
              <h4>任務資訊</h4>
              <dl className="my-work-drawer-dl">
                {view.drawer.task.assignee!==MY_WORK_LABELS.unknown&&<div>
                  <dt>負責人</dt>
                  <dd>{view.drawer.task.assignee}</dd>
                </div>}
                <div>
                  <dt>處理狀態</dt>
                  <dd>
                    <span
                      className={`my-work-status-text ${
                        view.drawer.task.needsAttention
                          ? 'status-attention'
                          : view.drawer.task.statusLabel === '待處理'
                          ? 'status-pending'
                          : 'status-unknown'
                      }`}
                    >
                      {myWorkStatusText(view.drawer.task)}
                    </span>
                  </dd>
                </div>
                {view.drawer.task.dueLabel!==MY_WORK_LABELS.unknown&&<div>
                  <dt>有效期限</dt>
                  <dd>{view.drawer.task.dueLabel}</dd>
                </div>}
                {view.drawer.task.nextDeliverable!==MY_WORK_LABELS.unknown&&<div>
                  <dt>下一交付物</dt>
                  <dd>{view.drawer.task.nextDeliverable}</dd>
                </div>}
              </dl>
            </section>

            {/* Input / Output */}
            {(view.drawer.task.requiredInput!==MY_WORK_LABELS.unknown||view.drawer.task.requiredOutput!==MY_WORK_LABELS.unknown)&&<section className="my-work-drawer-section">
              <h4>交付需求</h4>
              <dl className="my-work-drawer-dl">
                {view.drawer.task.requiredInput!==MY_WORK_LABELS.unknown&&<div>
                  <dt>必要輸入</dt>
                  <dd>{view.drawer.task.requiredInput}</dd>
                </div>}
                {view.drawer.task.requiredOutput!==MY_WORK_LABELS.unknown&&<div>
                  <dt>必要輸出</dt>
                  <dd>{view.drawer.task.requiredOutput}</dd>
                </div>}
              </dl>
            </section>}

            {/* Attached Evidence */}
            <section className="my-work-drawer-section">
              <h4>附加佐證</h4>
              {view.drawer.task.evidence === null ? (
                <p className="my-work-drawer-empty-text">佐證資料尚未提供</p>
              ) : view.drawer.task.evidence.length === 0 ? (
                <p className="my-work-drawer-empty-text">無附加佐證</p>
              ) : (
                <ul className="my-work-drawer-evidence-list">
                  {view.drawer.task.evidence.map((ev) => (
                    <li key={ev.id}>
                      <span className="my-work-evidence-title">{ev.title===MY_WORK_LABELS.unknown?'未命名佐證':ev.title}</span>
                      <span className="my-work-evidence-id">{ev.id}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="my-work-evidence-notice">
                佐證存在僅為客觀紀錄，不代表任務已完成。
              </p>
            </section>

            {/* Parent Case / Work Item */}
            {(view.drawer.task.parent.caseTitle!==MY_WORK_LABELS.unknown||view.drawer.task.parent.workItemTitle!==MY_WORK_LABELS.unknown)&&<section className="my-work-drawer-section">
              <h4>母層關聯</h4>
              <dl className="my-work-drawer-dl">
                {view.drawer.task.parent.caseTitle!==MY_WORK_LABELS.unknown&&<div>
                  <dt>母案件</dt>
                  <dd>{view.drawer.task.parent.caseTitle}</dd>
                </div>}
                {view.drawer.task.parent.workItemTitle!==MY_WORK_LABELS.unknown&&<div>
                  <dt>母工作項</dt>
                  <dd>{view.drawer.task.parent.workItemTitle}</dd>
                </div>}
              </dl>
            </section>}

            {/* Actions: Navigation only */}
            {view.drawer.task.actions.length > 0 && (
              <section className="my-work-drawer-section my-work-drawer-actions-section">
                <h4>可用操作</h4>
                <div className="my-work-drawer-actions">
                  {view.drawer.task.actions.map((act: MyWorkAction) => (
                    <button
                      key={act.kind}
                      type="button"
                      className="my-work-action-button"
                      onClick={() => onNavigate?.(act.route)}
                    >
                      {act.label}
                    </button>
                  ))}
                </div>
              </section>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

export default MyWorkTable;

export function AssignmentTable({items,onNavigate,compact=false}:{items:import('./useHomePanels').HomeItem[];onNavigate:(target:import('./useHomePanels').HomeTarget)=>void;compact?:boolean}) {
 const [expanded,setExpanded] = useState<string|null>(null);
 if (!compact) return <div className="my-work-table-scroll" role="region" tabIndex={0} aria-label="工作表格，可左右捲動"><table className="my-work-table">
  <thead><tr><th scope="col">工作與案件</th><th scope="col">負責人</th><th scope="col">期限</th><th scope="col">狀態</th><th scope="col">下一步</th><th scope="col">操作</th></tr></thead>
  <tbody>{items.map(item=><tr key={item.id}>
   <td><details><summary>{item.title}</summary><p>{item.detail || '來源未提供內容'}</p><AssignmentChildren item={item} onNavigate={onNavigate}/><p>指派人 {item.assigned_by?.name || '來源未提供'}{item.assignment_method ? ` · ${item.assignment_method}` : ''}</p><p>原始期限 {item.original_deadline || '未提供'}</p><p>{item.deadline_basis==='related_tasks_max' ? '節點期限取關聯任務的最晚截止日' : item.deadline_basis==='lark_task_deadline' ? '期限來自 Lark 任務截止日' : '期限來自本地工作流程'}</p></details><small>{item.kind==='sop_task' ? 'SOP 任務' : item.kind==='node_assignment' ? '節點責任' : item.origin==='local_workflow' ? '本地 SOP' : 'Lark 任務'} · {item.case.code || '案號待核對'} · {item.case.name || '案件關聯待核對'}</small></td>
   <td>{item.assignees.map(person=><span key={person.id}><Avatar small user={{name:person.name,avatar_url:person.avatar_url ?? undefined}}/>{person.name || '姓名未提供'} </span>)}</td>
   <td>{item.deadline || '未排期限'}{item.next_due && item.next_due!==item.deadline && <small>下一任務期限 {item.next_due}</small>}</td>
   <td>{item.source_status || WORK_STATUS[item.status] || '來源未提供'}</td>
   <td>{item.overdue && <span>{item.can_execute ? '逾期' : '期限已過，等待條件'} · </span>}{item.blocked_reasons.join('、') || (item.can_execute ? '可前往作業' : item.status==='done' ? '' : '請檢視作業條件')}</td>
   <td>{item.target ? <button type="button" className="text-button" onClick={()=>{if(item.target)onNavigate(homeTarget(item.target))}}>{item.kind==='sop_task'?'開啟任務':'開啟案件'}</button> : <a href="#view=projects">案件關聯待核對</a>}</td>
  </tr>)}</tbody>
 </table></div>;
 return <div className={compact ? 'ds-group glass--flat' : 'my-work-table-scroll'}>
  {items.map(item => <section key={item.id} className="dh-personal-queue">
   <div className="ds-row">
    <span className="ds-row-main">
     <button type="button" className="text-button" aria-expanded={expanded===item.id} onClick={()=>setExpanded(expanded===item.id ? null : item.id)}><strong>{item.title}</strong></button>
     <small>{item.kind==='sop_task' ? 'SOP 任務' : item.kind==='node_assignment' ? '節點責任' : item.origin==='local_workflow' ? '本地 SOP' : 'Lark 任務'} · {item.case.code || '案號待核對'} · {item.case.name || '案件關聯待核對'}</small>
     <span>{item.source_status || WORK_STATUS[item.status] || '來源未提供'} · {item.deadline || '未排期限'}{item.overdue ? item.can_execute ? ' · 逾期' : ' · 期限已過，等待條件' : item.due_today ? ' · 今日到期' : ''}</span>
     {item.next_due && item.next_due!==item.deadline && <small>下一任務期限 {item.next_due}</small>}
     <small>{item.blocked_reasons.join('、') || (item.can_execute ? '可前往作業' : item.status==='done' ? '' : '請檢視作業條件')}</small>
     <span>{item.assignees.map(person=><span key={person.id}><Avatar small user={{name:person.name,avatar_url:person.avatar_url ?? undefined}}/>{person.name || '姓名未提供'} </span>)}</span>
    </span>
    {item.target && <button type="button" className="text-button" onClick={()=>{if(item.target)onNavigate(homeTarget(item.target))}}>{item.kind==='sop_task'?'開啟任務':'開啟案件'}</button>}
   </div>
   {expanded===item.id && <div className="my-work-drawer-section">
    <p>{item.detail || '來源未提供內容'}</p>
    <AssignmentChildren item={item} onNavigate={onNavigate}/>
    <p>指派人 {item.assigned_by?.name || '來源未提供'}{item.assignment_method ? ` · ${item.assignment_method}` : ''}</p>
    <p>原始期限 {item.original_deadline || '未提供'} · 現行期限 {item.deadline || '未排期限'}</p>
    <p>{item.deadline_basis==='related_tasks_max' ? '節點期限取關聯任務的最晚截止日' : item.deadline_basis==='lark_task_deadline' ? '期限來自 Lark 任務截止日' : '期限來自本地工作流程'}</p>
    {item.home_detail?.proxy && <p>代理 {item.home_detail.proxy.principal_name} · {item.home_detail.proxy.start_date} 至 {item.home_detail.proxy.end_date} · {item.home_detail.proxy.basis}</p>}
    {!item.target && <a href="#view=projects">案件關聯待核對，前往案件列表</a>}
   </div>}
  </section>)}
 </div>;
}
const WORK_STATUS:Record<string,string> = {not_started:'未開始',todo:'待處理',in_progress:'進行中',in_review:'待審核',rework:'退回修正',done:'已完成',pending:'待處理',paused:'暫停中'};

function AssignmentChildren({item,onNavigate}:{item:import('./useHomePanels').HomeItem;onNavigate:(target:import('./useHomePanels').HomeTarget)=>void}) {
 if (!item.children?.length) return null;
 return <ul>{item.children.map(task=><li key={task.id}>{task.title} · {task.status} · {task.deadline || '未排期限'} · {task.assignee?.name || '未指派'}<p>{task.detail || '來源未提供內容'}</p>{item.target && <button type="button" className="text-button" onClick={()=>{if(item.target)onNavigate({...homeTarget(item.target),task:task.id})}}>開啟任務</button>}</li>)}</ul>;
}
