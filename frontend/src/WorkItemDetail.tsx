import { useRef, useEffect } from 'react';
import type {
  WorkItemView,
  WorkItemTab,
  Cell,
  Link,
} from './workItemDetailView.ts';
import { WORK_ITEM_TABS, WORK_ITEM_LABELS } from './workItemDetailView.ts';
import './p2-detail.css';

export interface WorkItemDetailProps {
  view: WorkItemView;
  onSelect?: (key: string | null) => void;
  onTabChange?: (tab: WorkItemTab) => void;
  onSort?: (direction: 'asc' | 'desc') => void;
  onHistoryExpand?: (expanded: boolean) => void;
  onNavigate?: (target: Link['target'] | {view: 'contract'; key: string} | {view: 'confirmation'; key: string}) => void;
  onBack?: () => void;
}

function renderCell(cell: Cell) {
  if (cell.state === 'unknown') {
    return (
      <span className="p2-cell-unknown" title={cell.reason}>
        {cell.text}
      </span>
    );
  }
  if (cell.state === 'withheld') {
    return (
      <span className="p2-cell-withheld" title={cell.reason}>
        {cell.text}
      </span>
    );
  }
  return <span className="p2-cell-text">{cell.text}</span>;
}

export function WorkItemDetail({
  view,
  onSelect,
  onTabChange,
  onSort,
  onHistoryExpand,
  onNavigate,
  onBack,
}: WorkItemDetailProps) {
  const rowSelectButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const tabButtonRefs = useRef<Map<WorkItemTab, HTMLButtonElement>>(new Map());
  const prevDrawerKeyRef = useRef<string | null>(view.drawer.model?.key ?? null);

  useEffect(() => {
    const currentKey = view.drawer.model?.key ?? null;
    const prevKey = prevDrawerKeyRef.current;
    prevDrawerKeyRef.current = currentKey;

    if (prevKey !== null && currentKey === null) {
      const btn = rowSelectButtonRefs.current.get(prevKey);
      btn?.focus();
    }
  }, [view.drawer.open, view.drawer.model]);

  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, currentTab: WorkItemTab) => {
    const tabs = WORK_ITEM_TABS;
    const currentIndex = tabs.indexOf(currentTab);
    if (currentIndex === -1) return;

    let targetIndex: number | null = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      targetIndex = (currentIndex + 1) % tabs.length;
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      targetIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    } else if (e.key === 'Home') {
      targetIndex = 0;
    } else if (e.key === 'End') {
      targetIndex = tabs.length - 1;
    }

    if (targetIndex !== null) {
      e.preventDefault();
      const nextTab = tabs[targetIndex];
      const targetBtn = tabButtonRefs.current.get(nextTab);
      targetBtn?.focus();
      onTabChange?.(nextTab);
    }
  };

  // Page-level non-ready / state view
  if (!view.hasContent) {
    return (
      <div className="p2-detail-root">
        <section
          className={`p2-banner ${view.pageState.states.map(s => `state-${s}`).join(' ')}`}
          role="status"
          aria-live="polite"
          aria-label="工作項資料狀態"
        >
          <div className="p2-banner-header">
            <span className="p2-banner-title">工作項資料狀態</span>
            <span className="p2-badge" data-state={view.pageState.states[0]}>
              {view.pageStateLabel}
            </span>
          </div>
          {view.unknownReason && (
            <p className="p2-banner-reason">{view.unknownReason}</p>
          )}
        </section>
        {onBack && (
          <div>
            <button type="button" className="p2-btn p2-btn-plain" onClick={onBack}>
              返回
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="p2-detail-root">
      {/* 頁面資料狀態橫幅 (Page State Banner) */}
      <section
        className={`p2-banner ${view.pageState.states.map(s => `state-${s}`).join(' ')}`}
        role="status"
        aria-live="polite"
        aria-label="頁面資料狀態"
      >
        <div className="p2-banner-header">
          <span className="p2-banner-title">資料狀態</span>
          <span className="p2-badge" data-state={view.pageState.states[0]}>
            {view.pageStateLabel}
          </span>
        </div>
      </section>

      {/* 路徑導覽 (Breadcrumb including unresolved parent row when present) */}
      <nav className="p2-breadcrumb" aria-label="路徑導覽">
        <ol className="p2-breadcrumb-list">
          {view.breadcrumbs.map((b, bIdx) => (
            <li key={`crumb-path-${bIdx}`} className="p2-breadcrumb-item">
              {/* Confirmations */}
              {b.confirmationUnresolved ? (
                <span className="p2-breadcrumb-unresolved">
                  {WORK_ITEM_LABELS.confirmationUnresolved}
                </span>
              ) : (
                b.confirmations.map((conf, cIdx) => (
                  <span key={`conf-${cIdx}`} className="p2-breadcrumb-item">
                    {cIdx > 0 && <span className="p2-breadcrumb-separator" aria-hidden="true">/</span>}
                    <span className="p2-breadcrumb-text">{conf.text}</span>
                    <span className="p2-badge p2-badge-verification">{conf.verification}</span>
                  </span>
                ))
              )}
              <span className="p2-breadcrumb-separator" aria-hidden="true">/</span>
              {/* Contract Line */}
              {b.contractLineUnresolved ? (
                <span className="p2-breadcrumb-unresolved" title={b.reason ?? undefined}>
                  {WORK_ITEM_LABELS.contractLineUnresolved}
                  {b.reason && <small className="p2-crumb-reason">（{b.reason}）</small>}
                </span>
              ) : (
                <span className="p2-breadcrumb-text">{b.contractLine}</span>
              )}
              <span className="p2-breadcrumb-separator" aria-hidden="true">/</span>
              {/* Work Item */}
              <span className="p2-breadcrumb-current" aria-current="page">
                {b.workItem}
              </span>
              <span className="p2-badge p2-badge-verification">{b.verification}</span>
            </li>
          ))}
        </ol>
      </nav>

      {/* 標頭資訊 (Header) */}
      {view.header && (
        <header className="p2-header">
          <div className="p2-header-title-row">
            <h1 className="p2-header-title">{renderCell(view.header.name)}</h1>
            <span className="p2-badge p2-badge-category">{renderCell(view.header.category)}</span>
            <span className="p2-badge p2-badge-status">{renderCell(view.header.executionState)}</span>
            <button
              type="button"
              ref={el => {
                if (el) rowSelectButtonRefs.current.set('work_item', el);
                else rowSelectButtonRefs.current.delete('work_item');
              }}
              className="p2-btn p2-btn-select p2-btn-sm"
              aria-expanded={view.drawer.open && view.drawer.model?.kind === 'work_item'}
              onClick={() => {
                const isOpen = view.drawer.open && view.drawer.model?.kind === 'work_item';
                onSelect?.(isOpen ? null : 'work_item');
              }}
            >
              {view.header.sourceIdentity}
            </button>
          </div>
          <div className="p2-header-meta">
            <span className="p2-meta-item">{view.asOfLabel}</span>
            <span className="p2-badge">{view.pageStateLabel}</span>
          </div>
        </header>
      )}

      {/* 主體與側欄佈局 (Main Layout) */}
      <div className="p2-layout-with-drawer">
        <div className="p2-primary-column">
          {/* WAI-ARIA 分頁列 (Tabs) */}
          <div
            className="p2-tablist"
            role="tablist"
            aria-label="工作項資訊分頁"
          >
            {view.tabs.map(tab => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                id={`p2-tab-${tab.key}`}
                aria-controls={`p2-tabpanel-${tab.key}`}
                aria-selected={tab.active}
                tabIndex={tab.active ? 0 : -1}
                ref={el => {
                  if (el) tabButtonRefs.current.set(tab.key, el);
                  else tabButtonRefs.current.delete(tab.key);
                }}
                className={`p2-tab ${tab.active ? 'is-active' : ''}`}
                onClick={() => onTabChange?.(tab.key)}
                onKeyDown={e => handleTabKeyDown(e, tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab 1: 工作內容 (Work Content) */}
          <div
            role="tabpanel"
            id="p2-tabpanel-work_content"
            aria-labelledby="p2-tab-work_content"
            tabIndex={0}
            className="p2-tabpanel"
            hidden={view.activeTab !== 'work_content'}
          >
            <section className="p2-card" aria-label="工作內容主體">
              <div className="p2-card-header">
                <h2 className="p2-section-title">工作內容</h2>
                <span className="p2-badge">{view.workContent.state.label}</span>
              </div>
              <dl className="p2-def-grid">
                <div className="p2-def-item">
                  <dt>數量</dt>
                  <dd>{renderCell(view.workContent.quantity)}</dd>
                </div>
                <div className="p2-def-item">
                  <dt>單位</dt>
                  <dd>{renderCell(view.workContent.unit)}</dd>
                </div>
                <div className="p2-def-item">
                  <dt>金額</dt>
                  <dd>{renderCell(view.workContent.amounts)}</dd>
                </div>
              </dl>
            </section>

            {/* 計畫與實際比較 (Plan / Actual unavailable) */}
            <section className="p2-card" aria-label="計畫與實際比較">
              <div className="p2-card-header">
                <h2 className="p2-section-title">計畫／實際比較</h2>
                <span className="p2-badge">{view.planActual.state.label}</span>
              </div>
              <p className="p2-banner-note">
                狀態：<span className="p2-cell-unknown">{view.planActual.label}</span>
              </p>
              <p className="p2-banner-reason">{view.planActual.reason}</p>
            </section>

            {/* 上層合約項目 (Parents) */}
            <section className="p2-card" aria-label="上層合約項目清單">
              <div className="p2-card-header">
                <h2 className="p2-section-title">上層合約項目</h2>
                <span className="p2-badge">{view.parents.state.label}</span>
              </div>
              {view.parents.rows.length === 0 && view.parents.unresolved.length === 0 ? (
                <p className="p2-table-empty">
                  {view.parents.emptyRow ?? view.parents.state.label}
                </p>
              ) : (
                <div className="p2-table-wrapper" tabIndex={0} role="region" aria-label="上層合約項目表格">
                  <table className="p2-table">
                    <caption className="p2-sr-only">上層合約項目清單</caption>
                    <thead>
                      <tr>
                        <th scope="col">合約項目名稱</th>
                        <th scope="col">項目編號</th>
                        <th scope="col">對應確認單</th>
                        <th scope="col">驗證</th>
                        <th scope="col">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {view.parents.rows.map(p => {
                        const isSelected = view.drawer.open && view.drawer.model?.key === p.key;
                        return (
                          <tr
                            key={p.key}
                            data-key={p.key}
                            aria-selected={isSelected}
                            className={`p2-tr ${isSelected ? 'is-selected' : ''}`}
                            onClick={() => onSelect?.(isSelected ? null : p.key)}
                          >
                            <td>{renderCell(p.title)}</td>
                            <td>{renderCell(p.itemNumber)}</td>
                            <td>
                              {p.confirmations.map((c, ci) => (
                                <span key={`parent-conf-${ci}`}>
                                  {ci > 0 && '、'}
                                  {c.text}
                                </span>
                              ))}
                            </td>
                            <td>
                              <span className="p2-badge p2-badge-verification">{p.verification}</span>
                            </td>
                            <td>
                              <button
                                type="button"
                                ref={el => {
                                  if (el) rowSelectButtonRefs.current.set(p.key, el);
                                  else rowSelectButtonRefs.current.delete(p.key);
                                }}
                                className="p2-btn p2-btn-sm p2-btn-select"
                                aria-expanded={isSelected}
                                onClick={e => {
                                  e.stopPropagation();
                                  onSelect?.(isSelected ? null : p.key);
                                }}
                              >
                                {isSelected ? '收合' : '詳情'}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                      {view.parents.unresolved.map((u, ui) => (
                        <tr key={`parent-unresolved-${ui}`} className="p2-tr">
                          <td colSpan={5}>
                            <span className="p2-unresolved-label">{u.label}</span>
                            <span className="p2-crumb-reason">（{u.reason}）</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>

          {/* Tab 2: 工單 (Work Orders unlocated with Source Health link) */}
          <div
            role="tabpanel"
            id="p2-tabpanel-work_orders"
            aria-labelledby="p2-tab-work_orders"
            tabIndex={0}
            className="p2-tabpanel"
            hidden={view.activeTab !== 'work_orders'}
          >
            <section className="p2-card" aria-label="工單資訊">
              <div className="p2-card-header">
                <div className="p2-card-header-left">
                  <h2 className="p2-section-title">工單</h2>
                  <span className="p2-badge">{view.workOrders.state.label}</span>
                  <span className="p2-badge p2-badge-verification">{view.workOrders.verification}</span>
                </div>
              </div>
              <p className="p2-banner-note">{view.workOrders.emptyRow}</p>
              <p className="p2-banner-reason">{view.workOrders.reason}</p>
              {view.workOrders.sourceHealthLink && (
                <div className="p2-link-container">
                  <button
                    type="button"
                    className="p2-btn p2-btn-secondary"
                    onClick={() => onNavigate?.(view.workOrders.sourceHealthLink!.target)}
                  >
                    {view.workOrders.sourceHealthLink.label}
                  </button>
                </div>
              )}
            </section>
          </div>

          {/* Tab 3: 工作流程節點／SOP (Workflow Nodes / SOP) */}
          <div
            role="tabpanel"
            id="p2-tabpanel-nodes"
            aria-labelledby="p2-tab-nodes"
            tabIndex={0}
            className="p2-tabpanel"
            hidden={view.activeTab !== 'nodes'}
          >
            <section className="p2-card" aria-label="工作流程節點與 SOP">
              <div className="p2-card-header">
                <h2 className="p2-section-title">工作流程節點／SOP</h2>
                <span className="p2-badge">{view.nodes.state.label}</span>
              </div>
              <div className="p2-table-wrapper" tabIndex={0} role="region" aria-label="工作流程節點表格">
                <table className="p2-table">
                  <caption className="p2-sr-only">工作流程節點與 SOP 清單</caption>
                  <thead>
                    <tr>
                      <th scope="col">節點名稱</th>
                      <th scope="col">任務標題</th>
                      <th scope="col">狀態</th>
                      <th scope="col">完成時間</th>
                      <th scope="col">必要性</th>
                      <th scope="col">負責人</th>
                      <th scope="col">輪次</th>
                      <th scope="col">驗證</th>
                      <th scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.nodes.rows.length === 0 ? (
                      <tr>
                        <td colSpan={9} className="p2-table-empty">
                          {view.nodes.emptyRow ?? view.nodes.state.label}
                        </td>
                      </tr>
                    ) : (
                      view.nodes.rows.map(row => {
                        const isSelected = view.drawer.open && view.drawer.model?.key === row.key;
                        return (
                          <tr
                            key={row.key}
                            data-key={row.key}
                            aria-selected={isSelected}
                            className={`p2-tr ${isSelected ? 'is-selected' : ''}`}
                            onClick={() => onSelect?.(isSelected ? null : row.key)}
                          >
                            <td>
                              <div>{renderCell(row.nodeName)}</div>
                              {row.operationNote && (
                                <div className="p2-banner-reason">{row.operationNote}</div>
                              )}
                              {row.reworkRounds.length > 0 && (
                                <div className="p2-rework-section">
                                  <ul className="p2-rework-list">
                                    {row.reworkRounds.map((rnd, ri) => (
                                      <li key={`${row.key}-rework-${ri}`} className="p2-rework-item">
                                        <span className="p2-rework-badge">{rnd.label}</span>
                                        <span>狀態：{renderCell(rnd.status)}</span>
                                        <span>輸出：{renderCell(rnd.output)}</span>
                                        <span>完成：{renderCell(rnd.completedAt)}</span>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                            </td>
                            <td>{renderCell(row.taskTitle)}</td>
                            <td>{renderCell(row.status)}</td>
                            <td>{renderCell(row.completedAt)}</td>
                            <td>{renderCell(row.required)}</td>
                            <td>{renderCell(row.responsible)}</td>
                            <td>{renderCell(row.round)}</td>
                            <td>
                              <span className="p2-badge p2-badge-verification">{row.verification}</span>
                            </td>
                            <td>
                              <button
                                type="button"
                                ref={el => {
                                  if (el) rowSelectButtonRefs.current.set(row.key, el);
                                  else rowSelectButtonRefs.current.delete(row.key);
                                }}
                                className="p2-btn p2-btn-sm p2-btn-select"
                                aria-expanded={isSelected}
                                onClick={e => {
                                  e.stopPropagation();
                                  onSelect?.(isSelected ? null : row.key);
                                }}
                              >
                                {isSelected ? '收合' : '詳情'}
                              </button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          {/* Tab 4: 交付物 (Deliverables - evidence rows marked evidence-only) */}
          <div
            role="tabpanel"
            id="p2-tabpanel-deliverables"
            aria-labelledby="p2-tab-deliverables"
            tabIndex={0}
            className="p2-tabpanel"
            hidden={view.activeTab !== 'deliverables'}
          >
            <section className="p2-card" aria-label="交付物清單">
              <div className="p2-card-header">
                <h2 className="p2-section-title">交付物</h2>
                <span className="p2-badge">{view.deliverables.state.label}</span>
              </div>
              <div className="p2-table-wrapper" tabIndex={0} role="region" aria-label="交付物表格">
                <table className="p2-table">
                  <caption className="p2-sr-only">交付物清單</caption>
                  <thead>
                    <tr>
                      <th scope="col">交付物名稱</th>
                      <th
                        scope="col"
                        aria-sort={view.deliverables.sortDir === 'desc' ? 'descending' : 'ascending'}
                        className="p2-th-sortable"
                      >
                        <button
                          type="button"
                          className="p2-sort-btn"
                          onClick={() => onSort?.(view.deliverables.sortDir === 'desc' ? 'asc' : 'desc')}
                          aria-label="依日期排序"
                        >
                          <span>建立日期</span>
                          <span className="p2-sort-icon" aria-hidden="true">
                            {view.deliverables.sortDir === 'desc' ? ' ↓' : ' ↑'}
                          </span>
                        </button>
                      </th>
                      <th scope="col">方向</th>
                      <th scope="col">版本</th>
                      <th scope="col">關聯範圍</th>
                      <th scope="col">標記</th>
                      <th scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.deliverables.rows.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="p2-table-empty">
                          {view.deliverables.emptyRow ?? view.deliverables.state.label}
                        </td>
                      </tr>
                    ) : (
                      view.deliverables.rows.map(row => {
                        const isSelected = view.drawer.open && view.drawer.model?.key === row.key;
                        return (
                          <tr
                            key={row.key}
                            data-key={row.key}
                            aria-selected={isSelected}
                            className={`p2-tr ${isSelected ? 'is-selected' : ''}`}
                            onClick={() => onSelect?.(isSelected ? null : row.key)}
                          >
                            <td>{renderCell(row.name)}</td>
                            <td>{renderCell(row.date)}</td>
                            <td>{renderCell(row.direction)}</td>
                            <td>{renderCell(row.version)}</td>
                            <td>{row.scope}</td>
                            <td>
                              <span className="p2-badge p2-badge-evidence" title={row.note}>
                                {WORK_ITEM_LABELS.evidenceOnly}
                              </span>
                            </td>
                            <td>
                              <button
                                type="button"
                                ref={el => {
                                  if (el) rowSelectButtonRefs.current.set(row.key, el);
                                  else rowSelectButtonRefs.current.delete(row.key);
                                }}
                                className="p2-btn p2-btn-sm p2-btn-select"
                                aria-expanded={isSelected}
                                onClick={e => {
                                  e.stopPropagation();
                                  onSelect?.(isSelected ? null : row.key);
                                }}
                              >
                                {isSelected ? '收合' : '詳情'}
                              </button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          {/* Tab 5: 歷程 (History) */}
          <div
            role="tabpanel"
            id="p2-tabpanel-history"
            aria-labelledby="p2-tab-history"
            tabIndex={0}
            className="p2-tabpanel"
            hidden={view.activeTab !== 'history'}
          >
            <section className="p2-card" aria-label="重工歷程">
              <div className="p2-card-header">
                <h2 className="p2-section-title">重工輪次歷程</h2>
                <span className="p2-badge">{view.history.state.label}</span>
              </div>
              {view.history.rounds.length === 0 ? (
                <p className="p2-table-empty">尚無重工輪次紀錄</p>
              ) : (
                <div className="p2-table-wrapper" tabIndex={0} role="region" aria-label="重工輪次歷程表格">
                  <table className="p2-table">
                    <caption className="p2-sr-only">重工輪次歷程清單</caption>
                    <thead>
                      <tr>
                        <th scope="col">節點名稱</th>
                        <th scope="col">輪次說明</th>
                        <th scope="col">狀態</th>
                        <th scope="col">輸出</th>
                        <th scope="col">完成時間</th>
                      </tr>
                    </thead>
                    <tbody>
                      {view.history.rounds.map(r => (
                        <tr key={r.key} className="p2-tr">
                          <td>{renderCell(r.nodeName)}</td>
                          <td><span className="p2-rework-badge">{r.label}</span></td>
                          <td>{renderCell(r.status)}</td>
                          <td>{renderCell(r.output)}</td>
                          <td>{renderCell(r.completedAt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {/* 已完成歷程收合區塊 */}
            <section className="p2-card" aria-label="已完成歷程">
              <div className="p2-card-header">
                <h2 className="p2-section-title">已完成歷程</h2>
                <button
                  type="button"
                  className="p2-btn p2-btn-secondary p2-btn-sm"
                  aria-expanded={view.history.completedExpanded}
                  onClick={() => onHistoryExpand?.(!view.history.completedExpanded)}
                >
                  {view.history.completedExpanded ? '收合已完成歷程' : '展開已完成歷程'}
                </button>
              </div>
              {view.history.completedExpanded && (
                <div>
                  {!view.history.completed || view.history.completed.length === 0 ? (
                    <p className="p2-table-empty">尚無已完成任務歷程</p>
                  ) : (
                    <div className="p2-table-wrapper" tabIndex={0} role="region" aria-label="已完成任務表格">
                      <table className="p2-table">
                        <caption className="p2-sr-only">已完成任務歷程清單</caption>
                        <thead>
                          <tr>
                            <th scope="col">節點名稱</th>
                            <th scope="col">任務標題</th>
                            <th scope="col">完成時間</th>
                          </tr>
                        </thead>
                        <tbody>
                          {view.history.completed.map(c => (
                            <tr key={c.key} className="p2-tr">
                              <td>{renderCell(c.nodeName)}</td>
                              <td>{renderCell(c.taskTitle)}</td>
                              <td>{renderCell(c.completedAt)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </section>
          </div>

          {/* 案件日報 (Case Daily Reports: link-only entry with no count) */}
          <section className="p2-card" aria-label="案件日報連結">
            <div className="p2-card-header">
              <h2 className="p2-section-title">{view.caseDailyReports.label}</h2>
            </div>
            <p className="p2-banner-note">{view.caseDailyReports.note}</p>
            {view.caseDailyReports.link && (
              <div className="p2-link-container">
                <button
                  type="button"
                  className="p2-btn p2-btn-secondary"
                  onClick={() => onNavigate?.(view.caseDailyReports.link!.target)}
                >
                  {view.caseDailyReports.link.label}
                </button>
              </div>
            )}
          </section>
        </div>

        {/* 側邊資訊區 (Side Area with distinct dates) */}
        <aside className="p2-side-column" aria-label="工作項側邊資訊">
          <div className="p2-side-area">
            <div className="p2-card-header">
              <h2 className="p2-section-title">側邊資訊</h2>
              <span className="p2-badge">{view.side.state.label}</span>
            </div>

            <div className="p2-def-item">
              <dt>負責人</dt>
              <dd>{renderCell(view.side.responsibleCell)}</dd>
            </div>

            <div className="p2-def-item">
              <dt>作業範圍</dt>
              <dd>{renderCell(view.side.operationScope)}</dd>
            </div>

            <div className="p2-side-section">
              <h3 className="p2-subheading">期程資訊</h3>
              <ul className="p2-side-dates-list">
                <li className="p2-side-date-item">
                  <span className="p2-side-date-label">正式期限</span>
                  <span className="p2-side-date-value">{renderCell(view.side.dates.effectiveDue)}</span>
                </li>
                <li className="p2-side-date-item">
                  <span className="p2-side-date-label">申請日期</span>
                  <span className="p2-side-date-value">{renderCell(view.side.dates.pendingDue)}</span>
                </li>
                <li className="p2-side-date-item">
                  <span className="p2-side-date-label">預估日期</span>
                  <span className="p2-side-date-value">{renderCell(view.side.dates.estimatedDue)}</span>
                </li>
                <li className="p2-side-date-item">
                  <span className="p2-side-date-label">來源更新時間</span>
                  <span className="p2-side-date-value">{renderCell(view.side.dates.sourceUpdatedAt)}</span>
                </li>
              </ul>
            </div>

            {view.side.warnings.length > 0 && (
              <div className="p2-side-section">
                <h3 className="p2-subheading">警示事項</h3>
                <ul className="p2-warnings-list">
                  {view.side.warnings.map((w, wi) => (
                    <li key={`side-warning-${wi}`} className="p2-warning-item">
                      <span className="p2-warning-icon" aria-hidden="true">⚠️</span>
                      <span className="p2-warning-text">{w}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </aside>

        {/* 原生詳情抽屜 (Selection-only Details Drawer) */}
        {view.drawer.open && view.drawer.model && (
          <aside
            className="p2-drawer"
            role="region"
            aria-label={`原生詳情抽屜：${view.drawer.model.kind}`}
          >
            <div className="p2-drawer-header">
              <h3 className="p2-drawer-title">
                {view.drawer.model.kind === 'work_item'
                  ? '工作項原生詳情'
                  : view.drawer.model.kind === 'parent'
                  ? '合約項目原生詳情'
                  : view.drawer.model.kind === 'node'
                  ? '節點原生詳情'
                  : '交付物原生詳情'}
              </h3>
              <button
                type="button"
                className="p2-btn p2-btn-sm p2-btn-close"
                onClick={() => {
                  const keyToRestore = view.drawer.model?.key;
                  onSelect?.(null);
                  if (keyToRestore) {
                    rowSelectButtonRefs.current.get(keyToRestore)?.focus();
                  }
                }}
                aria-label="關閉原生詳情抽屜"
              >
                關閉
              </button>
            </div>
            <div className="p2-drawer-body">
              <div className="p2-drawer-section">
                <h4 className="p2-drawer-section-title">原生識別（僅限抽屜）</h4>
                <dl className="p2-drawer-def">
                  {view.drawer.model.fields.map((f, i) => (
                    <div key={`d-field-${i}-${f.label}`}>
                      <dt>{f.label}</dt>
                      <dd><code>{f.value}</code></dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
