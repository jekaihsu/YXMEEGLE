// My Work Presentational UI (VCC-126).
// Pure presentational component: renders ONLY the output of buildMyWorkView from myWorkView.ts.
// Does NOT recompute any state, label, sort, or count.
// No fetch and no writes.

import { useRef, useEffect } from 'react';
import type {
  MyWorkView,
  MyWorkMode,
  MyWorkRow,
  MyWorkDetail,
  MyWorkAction,
} from './myWorkView.ts';
import './my-work-table.css';

export interface MyWorkTableProps {
  view: MyWorkView;
  onSelect?: (id: string | null) => void;
  onModeChange?: (mode: MyWorkMode) => void;
  onSearch?: (search: string) => void;
  onNavigate?: (route: string) => void;
}

export function MyWorkTable({
  view,
  onSelect,
  onModeChange,
  onSearch,
  onNavigate,
}: MyWorkTableProps) {
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
            <h2>我的工作</h2>
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

        {/* Page State Banner: every C-STATE value including view.pageState null */}
        <div
          className={`my-work-page-state-banner state-${
            view.pageState ? view.pageState.states.join('-') : 'ready'
          }`}
          role="status"
          aria-live="polite"
          data-state={bannerStateClass}
        >
          <span className="my-work-banner-state-text">{bannerText}</span>
          {view.selectionDropped && (
            <span className="my-work-selection-dropped-note">
              · 原選取項目已不再符合目前條件或已被移除
            </span>
          )}
        </div>

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
                {view.pageStateLabel || '尚無資料'}
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
                  <th scope="col">流程狀態</th>
                  <th scope="col">處理狀態</th>
                  <th scope="col">下一交付物</th>
                  <th scope="col">有效期限</th>
                  <th scope="col">待處理原因</th>
                  <th scope="col">交接／確認狀態</th>
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
                            aria-label={`選取任務：${row.title}`}
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
                            <strong>{row.title}</strong>
                          </button>
                          <span className="my-work-task-id">{row.id}</span>
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
                          <span>{row.caseTitle}</span>
                          <small>{row.workItemTitle}</small>
                        </div>
                      </td>

                      <td>
                        <span>{row.assignee}</span>
                      </td>

                      <td>
                        <span className="my-work-workflow-text">
                          {row.workflowLabel}
                        </span>
                      </td>

                      {/* Text status labels (not colour alone) */}
                      <td>
                        <span
                          className={`my-work-status-text ${
                            row.needsAttention
                              ? 'status-attention'
                              : row.statusLabel === '待處理'
                              ? 'status-pending'
                              : 'status-unknown'
                          }`}
                        >
                          {row.statusLabel}
                        </span>
                      </td>

                      <td>
                        <span>{row.nextDeliverable}</span>
                      </td>

                      {/* Effective due date: verified formal field only or unknown text, never 0 */}
                      <td>
                        <span className="my-work-due-text">{row.dueLabel}</span>
                      </td>

                      <td>
                        <span className="my-work-pending-reason">
                          {row.pendingReason}
                        </span>
                      </td>

                      {/* Handoff state: awaiting confirmation shown as not approved */}
                      <td>
                        <span className="my-work-handoff-text">
                          {row.handoffLabel}
                        </span>
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
                <h3>每週活動紀錄（獨立資料集）</h3>
                <span className="my-work-weekly-period">
                  區間：{view.weekly.period.start ?? 'unknown'} ~{' '}
                  {view.weekly.period.end ?? 'unknown'}
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
              <h3 className="my-work-drawer-title">{view.drawer.task.title}</h3>
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
                <div>
                  <dt>負責人</dt>
                  <dd>{view.drawer.task.assignee}</dd>
                </div>
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
                      {view.drawer.task.statusLabel}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>流程狀態</dt>
                  <dd>{view.drawer.task.workflowLabel}</dd>
                </div>
                <div>
                  <dt>有效期限</dt>
                  <dd>{view.drawer.task.dueLabel}</dd>
                </div>
                <div>
                  <dt>待處理原因</dt>
                  <dd>{view.drawer.task.pendingReason}</dd>
                </div>
                <div>
                  <dt>下一交付物</dt>
                  <dd>{view.drawer.task.nextDeliverable}</dd>
                </div>
              </dl>
            </section>

            {/* Input / Output */}
            <section className="my-work-drawer-section">
              <h4>交付需求</h4>
              <dl className="my-work-drawer-dl">
                <div>
                  <dt>必要輸入</dt>
                  <dd>{view.drawer.task.requiredInput}</dd>
                </div>
                <div>
                  <dt>必要輸出</dt>
                  <dd>{view.drawer.task.requiredOutput}</dd>
                </div>
              </dl>
            </section>

            {/* Handoff & Confirmation */}
            <section className="my-work-drawer-section">
              <h4>交接與確認狀態</h4>
              <p className="my-work-drawer-handoff-status">
                {view.drawer.task.handoffLabel}
              </p>
            </section>

            {/* Attached Evidence */}
            <section className="my-work-drawer-section">
              <h4>附加佐證</h4>
              {view.drawer.task.evidence.length === 0 ? (
                <p className="my-work-drawer-empty-text">無附加佐證</p>
              ) : (
                <ul className="my-work-drawer-evidence-list">
                  {view.drawer.task.evidence.map((ev) => (
                    <li key={ev.id}>
                      <span className="my-work-evidence-title">{ev.title}</span>
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
            <section className="my-work-drawer-section">
              <h4>母層關聯</h4>
              <dl className="my-work-drawer-dl">
                <div>
                  <dt>母案件</dt>
                  <dd>{view.drawer.task.parent.caseTitle}</dd>
                </div>
                <div>
                  <dt>母工作項</dt>
                  <dd>{view.drawer.task.parent.workItemTitle}</dd>
                </div>
              </dl>
            </section>

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
