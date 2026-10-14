import { useRef, useEffect, useId } from 'react';
import type {
  ManagerOverviewView,
  Drilldown,
  OverviewSort,
  FactCell,
  CaseRow,
  UnresolvedRowView,
} from './managerOverviewView.ts';
import './p2-lists.css';

export interface ManagerOverviewCallbacks {
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
  if (!cell.known) {
    return (
      <span className="p2-cell-unknown" title={cell.reason ?? undefined}>
        <span className="p2-dash">{cell.text}</span>
        {cell.stateLabel && (
          <small className="p2-cell-statelabel">（{cell.stateLabel}）</small>
        )}
        {cell.reason && <span className="p2-sr-only">：{cell.reason}</span>}
      </span>
    );
  }
  return (
    <span className="p2-cell-text" title={cell.reason ?? undefined}>
      {cell.text}
      {cell.stateLabel && (
        <small className="p2-cell-statelabel">（{cell.stateLabel}）</small>
      )}
    </span>
  );
}

export function ManagerOverview(props: ManagerOverviewProps) {
  const view: ManagerOverviewView =
    'header' in props && 'snapshot' in props
      ? props
      : (props as { view: ManagerOverviewView }).view;

  const {
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

  const snapshotStateClass = view.snapshot.state.states.join(' ');

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

      {/* Filter mismatch warning */}
      {view.header.filterMismatch && (
        <div className="p2-banner-mismatch" role="status">
          {view.header.filterMismatch}
        </div>
      )}

      {/* Snapshot state banner */}
      <section
        className={`p2-banner state-${snapshotStateClass}`}
        role="status"
        aria-live="polite"
        aria-label="快照資料狀態"
      >
        <div className="p2-banner-header">
          <span className="p2-banner-title">快照資料狀態</span>
          <span className="p2-badge">{view.snapshot.stateLabel}</span>
        </div>
        {view.snapshot.reason && (
          <p className="p2-banner-reason">{view.snapshot.reason}</p>
        )}
      </section>

      {/* Overview Layout: Main Content + Side Panel */}
      <div className="manager-overview-layout">
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
                  {view.snapshot.casesEmptyLabel ??
                    (view.snapshot.reason
                      ? `${view.snapshot.stateLabel}：${view.snapshot.reason}`
                      : view.snapshot.stateLabel)}
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
                        <th scope="col">案件名稱</th>
                        <th scope="col">未完成狀態</th>
                        <th scope="col">可行動</th>
                        <th scope="col">負責人</th>
                        <th scope="col">目前階段</th>
                        <th scope="col">有效期限</th>
                        <th scope="col">受阻</th>
                        <th scope="col">待決策</th>
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
                            <td>{renderFact(caseRow.label)}</td>
                            <td>{renderFact(caseRow.unfinished)}</td>
                            <td>{renderFact(caseRow.actionable)}</td>
                            <td>{renderFact(caseRow.responsible)}</td>
                            <td>{renderFact(caseRow.currentStage)}</td>
                            <td>{renderFact(caseRow.effectiveDueDate)}</td>
                            <td>{renderFact(caseRow.blocker)}</td>
                            <td>{renderFact(caseRow.pendingDecision)}</td>
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
                                    {caseRow.entry.label}
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
          {view.snapshot.cards.length > 0 && (
            <section
              className="p2-section p2-cards-section"
              aria-labelledby={`${baseId}-cards-heading`}
            >
              <h3 id={`${baseId}-cards-heading`} className="p2-section-title">
                快照摘要
              </h3>
              <div className="p2-cards-grid">
                {view.snapshot.cards.map((card) => (
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
                      {!card.known && (
                        <div className="p2-card-reason" title={card.reason}>
                          <span>{card.reason}</span>
                        </div>
                      )}
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

          {/* Unresolved summary (separate section; no bucket total) */}
          <section
            className="p2-section p2-unresolved-section"
            aria-labelledby={`${baseId}-unresolved-heading`}
          >
            <div className="p2-section-header">
              <h3
                id={`${baseId}-unresolved-heading`}
                className="p2-section-title"
              >
                未歸屬資料
              </h3>
              <div className="p2-unresolved-meta">
                <span className="p2-unresolved-count">
                  數量：
                  <strong>{view.snapshot.unresolved.countText}</strong>
                </span>
                <span className="p2-badge">
                  {view.snapshot.unresolved.stateLabel}
                </span>
              </div>
            </div>

            {!view.snapshot.unresolved.known &&
              view.snapshot.unresolved.reason && (
                <p className="p2-section-reason">
                  {view.snapshot.unresolved.reason}
                </p>
              )}

            {view.snapshot.unresolved.rows.length > 0 && (
              <div className="p2-table-container">
                <div
                  className="p2-table-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="未歸屬資料清單表格"
                >
                  <table className="p2-table is-dense">
                    <caption className="p2-sr-only">未歸屬資料清單</caption>
                    <thead>
                      <tr>
                        <th scope="col">項目名稱</th>
                        <th scope="col">對應狀態</th>
                        <th scope="col">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {view.snapshot.unresolved.rows.map(
                        (urow: UnresolvedRowView) => {
                          const isSelected = view.selectedId === urow.id;

                          return (
                            <tr
                              key={urow.id}
                              className={`p2-row ${
                                isSelected ? 'is-selected' : ''
                              }`}
                              onClick={() =>
                                onSelect?.(isSelected ? null : urow.id)
                              }
                              tabIndex={0}
                              onKeyDown={(e) => {
                                if (e.repeat) return;
                                if (
                                  e.target === e.currentTarget &&
                                  (e.key === 'Enter' || e.key === ' ')
                                ) {
                                  e.preventDefault();
                                  onSelect?.(isSelected ? null : urow.id);
                                }
                              }}
                            >
                              <td>
                                <strong>{urow.label}</strong>
                              </td>
                              <td>
                                <span className="p2-badge p2-badge-verification">
                                  {urow.mappingLabel}
                                </span>
                              </td>
                              <td>
                                <button
                                  type="button"
                                  ref={(el) => {
                                    if (el) {
                                      rowSelectButtonRefs.current.set(
                                        urow.id,
                                        el
                                      );
                                    } else {
                                      rowSelectButtonRefs.current.delete(
                                        urow.id
                                      );
                                    }
                                  }}
                                  className="p2-btn-select"
                                  aria-expanded={isSelected}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onSelect?.(isSelected ? null : urow.id);
                                  }}
                                  aria-label={`選取${urow.label}詳情`}
                                >
                                  {isSelected ? '收合' : '詳情'}
                                </button>
                              </td>
                            </tr>
                          );
                        }
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {view.snapshot.bucketNote && (
              <p className="p2-bucket-policy-note" role="note">
                {view.snapshot.bucketNote}
              </p>
            )}
          </section>

          {/* Weekly activity (separate section; unavailable) */}
          <section
            className="p2-section p2-weekly-section is-unavailable"
            aria-labelledby={`${baseId}-weekly-heading`}
          >
            <div className="p2-section-header">
              <h3 id={`${baseId}-weekly-heading`} className="p2-section-title">
                本期活動
              </h3>
              <span className="p2-badge p2-badge-unavailable">暫不可用</span>
            </div>
            <div className="p2-weekly-body">
              <span className="p2-weekly-state">{view.weekly.stateLabel}</span>
              <p className="p2-weekly-reason">{view.weekly.reason}</p>
              {view.weekly.period && (
                <p className="p2-weekly-period">
                  活動區間：{view.weekly.period.start} ~ {view.weekly.period.end}
                </p>
              )}
            </div>
          </section>
        </div>

        {/* Source Health side panel: state labels only; no source names or counts */}
        <div className="manager-overview-side">
          <aside
            className="p2-side-panel p2-source-health-panel"
            aria-labelledby={`${baseId}-health-heading`}
          >
            <div className="p2-side-header">
              <h3 id={`${baseId}-health-heading`}>來源健康</h3>
              <span className="p2-badge">{view.sourceHealth.stateLabel}</span>
            </div>
            <div className="p2-health-rows">
              {view.sourceHealth.rows.map((hr) => (
                <div key={hr.key} className="p2-health-row">
                  <div className="p2-health-row-header">
                    <span className="p2-health-label">{hr.label}</span>
                    <span className="p2-health-state">{hr.stateLabel}</span>
                  </div>
                  <span className="p2-health-reason" title={hr.reason}>
                    {hr.reason}
                  </span>
                </div>
              ))}
            </div>
            {view.sourceHealth.link && (
              <button
                type="button"
                className="p2-btn-health-link"
                onClick={() => {
                  if (onSourceHealthLink) {
                    onSourceHealthLink(view.sourceHealth.link!.route);
                  } else {
                    onNavigate?.(view.sourceHealth.link!.route);
                  }
                }}
              >
                {view.sourceHealth.link.label}
              </button>
            )}
          </aside>

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
                                {view.drawer.case.rowKeysReason}
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
                            <dd>{view.drawer.case.executionStatus}</dd>
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
                            <dd>{view.drawer.case.formula}</dd>
                          </div>
                        )}
                      </dl>
                    </div>

                    {view.drawer.case.admission && (
                      <div className="p2-drawer-section">
                        <h4 className="p2-drawer-section-title">准入資訊</h4>
                        <dl className="p2-dl">
                          {Object.entries(view.drawer.case.admission).map(
                            ([k, val]) => (
                              <div key={k}>
                                <dt>{k}</dt>
                                <dd>{String(val ?? '—')}</dd>
                              </div>
                            )
                          )}
                        </dl>
                      </div>
                    )}

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
                              {view.drawer.case.amounts.reason}
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
        </div>
      </div>
    </div>
  );
}
