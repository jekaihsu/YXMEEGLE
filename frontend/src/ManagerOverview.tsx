import { useRef, useEffect, useId, type ReactNode } from 'react';
import type {
  ManagerOverviewView,
  Drilldown,
  OverviewSort,
  FactCell,
  CaseRow,
} from './managerOverviewView.ts';
import './p2-lists.css';
import './manager-overview.css';

export interface ManagerOverviewCallbacks {
  filters?: ReactNode;
  onSelect?: (id: string | null) => void;
  onDrilldown?: (drilldown: Drilldown) => void;
  onNavigate?: (route: string) => void;
  onBack?: () => void;
  onSort?: (sort: OverviewSort) => void;
  onSourceHealthLink?: (route: 'sources') => void;
}

export type ManagerOverviewProps = (
  | ManagerOverviewView
  | { view: ManagerOverviewView }
) & ManagerOverviewCallbacks;

function renderFact(cell: FactCell) {
  return cell.known ? <span className="p2-cell-text">{cell.text}</span> : null;
}

const CASE_COLUMNS = [
  {key: 'label', label: '案件名稱'},
  {key: 'responsible', label: '負責人'},
  {key: 'unfinished', label: '未完成狀態'},
  {key: 'actionable', label: '可行動'},
  {key: 'currentStage', label: '目前階段'},
  {key: 'effectiveDueDate', label: '有效期限'},
  {key: 'blocker', label: '受阻'},
  {key: 'pendingDecision', label: '待決策'},
] satisfies {key: keyof Pick<CaseRow, 'label' | 'responsible' | 'unfinished' | 'actionable' | 'currentStage' | 'effectiveDueDate' | 'blocker' | 'pendingDecision'>; label: string}[];

export function ManagerOverview(props: ManagerOverviewProps) {
  const view: ManagerOverviewView =
    'header' in props && 'snapshot' in props
      ? props
      : (props as { view: ManagerOverviewView }).view;

  const {
    filters,
    onSelect,
    onDrilldown,
    onNavigate,
    onSourceHealthLink,
  } = props;

  const baseId = useId();
  const rowSelectButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const prevSelectedIdRef = useRef<string | null>(view?.selectedId ?? null);

  useEffect(() => {
    const currentId = view?.selectedId ?? null;
    const prevId = prevSelectedIdRef.current;
    prevSelectedIdRef.current = currentId;

    if (prevId !== null && currentId === null) {
      const targetBtn = rowSelectButtonRefs.current.get(prevId);
      if (targetBtn) {
        targetBtn.focus();
      }
    }
  }, [view?.selectedId]);

  if (!view) return null;

  const columns = CASE_COLUMNS.filter(column => ['label', 'responsible'].includes(column.key) || view.snapshot.cases.some(row => row[column.key].known));
  const cards = view.snapshot.cards.filter(card => card.known);

  return (
    <div className="manager-overview-root">
      {/* Snapshot Header with time and readable scope */}
      <header className="p2-header">
        <div className="p2-header-title-row">
          <h2 className="p2-title">{view.header.title}</h2>
          <div className="p2-header-meta">
            <span className="p2-meta-item">{view.header.asOfLabel}</span>
            <span className="p2-meta-item">· 範圍：{view.header.scopeLabel}</span>
          </div>
        </div>
        {view.header.scope.length > 0 && (
          <div className="p2-scope-tags">
            {view.header.scope.map((s) => (
              <span key={s.key} className="p2-scope-tag">
                {s.label}：{s.value}
              </span>
            ))}
          </div>
        )}
      </header>
      {filters}

      {/* Filter mismatch warning */}
      {view.header.filterMismatch && (
        <div className="p2-banner-mismatch" role="status">
          {view.header.filterMismatch}
        </div>
      )}

      <p className="overview-table-note" role="status">
        {view.snapshot.state.states.some(state => !['complete_empty', 'filtered_empty'].includes(state)) ? '統計與來源資料尚未完整。' : '目前沒有符合條件的案件。'}{' '}
        <button type="button" className="p2-btn-health-link" onClick={() => onSourceHealthLink ? onSourceHealthLink('sources') : onNavigate?.('sources')}>查看來源健康</button>
      </p>

      {/* Overview Layout: Main Content + Side Panel */}
      <div className={`manager-overview-layout${view.drawer.open ? " has-selection" : ""}`}>
        <div className="manager-overview-main">
          {/* Actionable Unfinished Cases FIRST */}
          <section
            className="p2-section p2-cases-section"
            aria-labelledby={`${baseId}-cases-heading`}
          >
            <div className="p2-section-header">
              <h3 id={`${baseId}-cases-heading`} className="p2-section-title">
                未完成案件
              </h3>

            </div>

            {view.snapshot.cases.length === 0 ? (
              <div className="p2-empty-state" role="status">
                <p>
                  {view.snapshot.casesEmptyLabel ?? '案件資料尚未提供。'}
                </p>
              </div>
            ) : (
              <div className="p2-table-container">
                <div
                  className="p2-table-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="未完成案件表格，可左右捲動"
                >
                  <table className="p2-table p2-cases-table is-dense">
                    <caption className="p2-sr-only">未完成案件清單</caption>
                    <thead>
                      <tr>
                        {columns.map(column => <th scope="col" key={column.key}>{column.label}</th>)}
                        <th scope="col">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {view.snapshot.cases.map((caseRow: CaseRow) => {
                        const isSelected = view.selectedId === caseRow.id;

                        return (
                          <tr
                            key={caseRow.id}
                            className={`p2-row ${isSelected ? 'is-selected' : ''}`}
                            onClick={() =>
                              onSelect?.(isSelected ? null : caseRow.id)
                            }
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.repeat) return;
                              if (
                                e.target === e.currentTarget &&
                                (e.key === 'Enter' || e.key === ' ')
                              ) {
                                e.preventDefault();
                                onSelect?.(isSelected ? null : caseRow.id);
                              }
                            }}
                          >
                            {columns.map(column => <td key={column.key}>{renderFact(caseRow[column.key])}</td>)}
                            <td>
                              <div className="p2-toolbar-left">
                                {caseRow.entry && (
                                  <button
                                    type="button"
                                    className="p2-btn-entry"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onNavigate?.(caseRow.entry!.route);
                                    }}
                                    aria-label={`${caseRow.entry.label}：${caseRow.label.text}`}
                                  >
                                    {caseRow.entry.label} →
                                  </button>
                                )}
                                <button
                                  type="button"
                                  ref={(el) => {
                                    if (el) {
                                      rowSelectButtonRefs.current.set(
                                        caseRow.id,
                                        el
                                      );
                                    } else {
                                      rowSelectButtonRefs.current.delete(
                                        caseRow.id
                                      );
                                    }
                                  }}
                                  className="p2-btn-select"
                                  aria-expanded={isSelected}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onSelect?.(isSelected ? null : caseRow.id);
                                  }}
                                  aria-label={
                                    caseRow.label.text &&
                                    caseRow.label.text !== '—'
                                      ? `選取案件詳情：${caseRow.label.text}`
                                      : '選取案件詳情'
                                  }
                                >
                                  {isSelected ? '收合' : '詳情'}
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>

          {/* Cards labelled with their unit. Activates onDrilldown(card.drilldown) unchanged. */}
          {cards.length > 0 && (
            <section
              className="p2-section p2-cards-section"
              aria-labelledby={`${baseId}-cards-heading`}
            >
              <h3 id={`${baseId}-cards-heading`} className="p2-section-title">
                快照摘要
              </h3>
              <div className="p2-cards-grid">
                {cards.map((card) => (
                  <div
                    key={card.id}
                    className={`p2-card ${!card.known ? 'is-unavailable' : ''}`}
                    tabIndex={0}
                    role="button"
                    aria-label={`${card.label}，${
                      card.known ? card.valueText : '暫不可用'
                    }，單位：${card.unitLabel}`}
                    onClick={() => onDrilldown?.(card.drilldown)}
                    onKeyDown={(e) => {
                      if (e.repeat) return;
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onDrilldown?.(card.drilldown);
                      }
                    }}
                  >
                    <div className="p2-card-header">
                      <span className="p2-card-title">{card.label}</span>
                      <span className="p2-card-unit">{card.unitLabel}</span>
                    </div>
                    <div className="p2-card-body">
                      <div className="p2-card-value-row">
                        <span className="p2-card-value">{card.valueText}</span>
                        <span className="p2-card-state">{card.stateLabel}</span>
                      </div>

                    </div>
                    <div className="p2-card-footer">
                      <span className="p2-card-asof">{card.asOfLabel}</span>
                      <span
                        className="p2-card-drilldown-hint"
                        aria-hidden="true"
                      >
                        查看清單 →
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

        </div>

        {view.drawer.open && <div className="manager-overview-side">
          {/* Selection-only Drawer */}
          {view.drawer.open && (view.drawer.case || view.drawer.unresolved) && (
            <aside
              className="p2-drawer manager-overview-drawer"
              role="region"
              aria-label="詳細資訊抽屜"
            >
              <div className="p2-drawer-header">
                <h3 className="p2-drawer-title">
                  {view.drawer.case ? '案件詳情' : '未歸屬資料詳情'}
                </h3>
                <button
                  type="button"
                  className="p2-drawer-close-btn"
                  onClick={() => onSelect?.(null)}
                  aria-label="關閉詳情抽屜"
                >
                  關閉
                </button>
              </div>

              <div className="p2-drawer-body">
                {view.drawer.case && (
                  <>
                    <div className="p2-drawer-section">
                      <h4 className="p2-drawer-section-title">確認單版本</h4>
                      <dl className="p2-dl">
                        <div>
                          <dt>確認單列狀態</dt>
                          <dd>
                            <span>{view.drawer.case.rowKeysText}</span>
                            {view.drawer.case.rowKeysStateLabel && (
                              <small className="p2-cell-statelabel">
                                （{view.drawer.case.rowKeysStateLabel}）
                              </small>
                            )}
                          </dd>
                        </div>
                        {view.drawer.case.rowKeysReason && (
                          <div>
                            <dt>說明</dt>
                            <dd>
                              <span className="p2-amount-reason">
                                確認單版本資料尚待核對。
                              </span>
                            </dd>
                          </div>
                        )}
                      </dl>
                      {view.drawer.case.rowKeys &&
                        view.drawer.case.rowKeys.length > 0 && (
                          <ul className="p2-rowkeys-list">
                            {view.drawer.case.rowKeys.map((k) => (
                              <li key={k}>
                                <code>{k}</code>
                              </li>
                            ))}
                          </ul>
                        )}
                    </div>

                    <div className="p2-drawer-section">
                      <h4 className="p2-drawer-section-title">
                        案件執行與對應
                      </h4>
                      <dl className="p2-dl">
                        {view.drawer.case.pmId && (
                          <div>
                            <dt>PM 代碼</dt>
                            <dd>
                              <code>{view.drawer.case.pmId}</code>
                            </dd>
                          </div>
                        )}
                        {view.drawer.case.executionStatus && (
                          <div>
                            <dt>執行狀態</dt>
                            <dd>{{in_progress:'進行中',completed:'已完成',paused:'暫停中',pending:'待處理'}[view.drawer.case.executionStatus] || '執行狀態尚待核對'}</dd>
                          </div>
                        )}
                        <div>
                          <dt>對應狀態</dt>
                          <dd>
                            <span className="p2-badge p2-badge-verification">
                              {view.drawer.case.mappingLabel}
                            </span>
                          </dd>
                        </div>
                        {view.drawer.case.formula && (
                          <div>
                            <dt>版本規則</dt>
                            <dd>確認單版本各自保留。</dd>
                          </div>
                        )}
                      </dl>
                    </div>


                    <div className="p2-drawer-section">
                      <h4 className="p2-drawer-section-title">合約金額</h4>
                      <dl className="p2-dl">
                        <div>
                          <dt>顯示狀態</dt>
                          <dd>
                            <span className="p2-amount-withheld">
                              {view.drawer.case.amounts.text}
                            </span>
                          </dd>
                        </div>
                        <div>
                          <dt>未核准原因</dt>
                          <dd>
                            <span className="p2-amount-reason">
                              合約金額尚未核准顯示。
                            </span>
                          </dd>
                        </div>
                      </dl>
                    </div>
                  </>
                )}

                {view.drawer.unresolved && (
                  <div className="p2-drawer-section">
                    <h4 className="p2-drawer-section-title">
                      未歸屬資料脈絡
                    </h4>
                    <dl className="p2-dl">
                      <div>
                        <dt>來源列代碼</dt>
                        <dd>
                          <code>{view.drawer.unresolved.rowKey}</code>
                        </dd>
                      </div>
                      <div>
                        <dt>對應狀態</dt>
                        <dd>
                          <span className="p2-badge p2-badge-verification">
                            {view.drawer.unresolved.mappingLabel}
                          </span>
                        </dd>
                      </div>
                    </dl>
                  </div>
                )}
              </div>
            </aside>
          )}
        </div>}
      </div>
    </div>
  );
}
