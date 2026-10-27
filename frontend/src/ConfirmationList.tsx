import { useRef, useEffect, useState, useId } from 'react';
import type {
  ConfirmationListView,
  SortSpec,
  FilterSet,
  ConfirmationListRow,
} from './confirmationListView.ts';
import './p2-lists.css';
import './ConfirmationList.css';

export interface ConfirmationListCallbacks {
  onSelect?: (key: string | null) => void;
  onSort?: (sort: SortSpec) => void;
  onNavigate?: (route: string) => void;
  onBack?: () => void;
  onPage?: (cursor: string | null) => void;
  onSearch?: (search: string) => void;
  onFilterChange?: (filters: FilterSet) => void;
  onColumnToggle?: (columnKey: string) => void;
  onResetFilters?: () => void;
}

export type ConfirmationListProps = (
  | ConfirmationListView
  | { view: ConfirmationListView }
) & ConfirmationListCallbacks;

export function ConfirmationList(props: ConfirmationListProps) {
  const view: ConfirmationListView =
    'header' in props && 'table' in props
      ? props
      : (props as { view: ConfirmationListView }).view;

  const {
    onSelect,
    onSort,
    onNavigate,
    onPage,
    onSearch,
    onFilterChange,
    onColumnToggle,
    onResetFilters,
  } = props;

  const baseId = useId();
  const [chooserOpen, setChooserOpen] = useState(false);
  const rowSelectButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const prevSelectedKeyRef = useRef<string | null>(
    view?.drawer?.open && view.drawer.row ? view.drawer.row.key : null
  );

  const hasActiveAdvanced = Boolean(
    view?.controls?.filters?.admission ||
    view?.controls?.filters?.deadline_from ||
    view?.controls?.filters?.deadline_to
  );
  const [advancedOpen, setAdvancedOpen] = useState(hasActiveAdvanced);

  useEffect(() => {
    if (hasActiveAdvanced) {
      setAdvancedOpen(true);
    }
  }, [hasActiveAdvanced]);

  useEffect(() => {
    const currentKey =
      view?.drawer?.open && view.drawer.row ? view.drawer.row.key : null;
    const prevKey = prevSelectedKeyRef.current;
    prevSelectedKeyRef.current = currentKey;

    if (prevKey !== null && currentKey === null) {
      const targetBtn = rowSelectButtonRefs.current.get(prevKey);
      if (targetBtn) {
        targetBtn.focus();
      }
    }
  }, [view?.drawer?.open, view?.drawer?.row]);

  if (!view) return null;

  const visibleColumns = view.columns.filter((c) => c.visible);
  const stickyCol1 = view.table.stickyColumns[0] ?? 'case_number';
  const stickyCol2 = view.table.stickyColumns[1] ?? 'project_name';

  const handleSortClick = (colKey: string, currentDir: 'asc' | 'desc' | null) => {
    if (currentDir === 'asc') {
      onSort?.({ key: colKey, dir: 'desc' });
    } else if (currentDir === 'desc') {
      onSort?.(null);
    } else {
      onSort?.({ key: colKey, dir: 'asc' });
    }
  };

  const handleFilterChange = (filterKey: string, value: string) => {
    if (!onFilterChange) return;
    const nextFilters: Record<string, string> = {};
    for (const [k, v] of Object.entries(view.controls.filters)) {
      if (k !== filterKey && typeof v === 'string' && v.trim()) {
        nextFilters[k] = v;
      }
    }
    if (value && value.trim()) {
      nextFilters[filterKey] = value;
    }
    onFilterChange(nextFilters);
  };

  const handleSearchChange = (value: string) => {
    if (onSearch) {
      onSearch(value);
    } else if (onFilterChange) {
      handleFilterChange('search', value);
    }
  };

  const hasActiveFilters = Boolean(
    view.controls.filters.search ||
    view.controls.filters.source_version ||
    view.controls.filters.pm ||
    view.controls.filters.admission ||
    view.controls.filters.deadline_from ||
    view.controls.filters.deadline_to
  );

  return (
    <div className="confirmation-list-root">
      {/* Header */}
      <header className="p2-header">
        <div className="p2-header-title-row">
          <h2 className="p2-title">{view.header.title}</h2>
          <div className="p2-header-meta">
            {!view.header.asOf.reason && <span className="p2-meta-item">資料日期：{view.header.asOf.label}</span>}
            {!view.header.snapshot.reason && <span className="p2-meta-item">保留資料：{view.header.snapshot.label}</span>}
          </div>
        </div>
      </header>

      {view.pageState && <p className="overview-table-note" role="status">
        {view.pageState.states.some(state => state === 'forbidden') ? '沒有權限檢視工程確認單。' : view.pageState.states.some(state => state === 'loading') ? '確認單讀取中…' : view.pageState.states.some(state => state === 'complete_empty') ? '目前沒有工程確認單。' : view.pageState.states.some(state => state === 'filtered_empty') ? '沒有符合條件的確認單。' : view.pageState.states.some(state => state === 'stale') ? '資料待更新，目前顯示保留資料。' : view.pageState.states.some(state => state === 'read_failed') ? '更新失敗，目前顯示保留資料。' : '確認單資料尚未完整，僅顯示已載入內容。'}
      </p>}

      {/* Controls & Toolbar with Progressive Disclosure */}
      <div className="p2-toolbar" role="region" aria-label="清單篩選與欄位控制">
        {/* Primary Filter & Action Bar */}
        <div className="p2-toolbar-row-primary">
          <div className="p2-toolbar-primary-left">
            {/* Search box (Primary action anchor) */}
            <div className="p2-search-box">
              <input
                id={`${baseId}-search`}
                type="search"
                className="p2-search-input"
                value={view.controls.filters.search ?? ''}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="搜尋確認單…"
                aria-label="搜尋工程確認單"
              />
              {view.controls.filters.search ? (
                <button
                  type="button"
                  className="p2-search-clear"
                  onClick={() => handleSearchChange('')}
                  aria-label="清除搜尋"
                >
                  ×
                </button>
              ) : null}
            </div>

            {/* Quick Filter: Source Version */}
            <div className="p2-filter-field-inline">
              <label
                htmlFor={`${baseId}-filter-source-version`}
                className="p2-filter-label"
              >
                版本
              </label>
              <input
                id={`${baseId}-filter-source-version`}
                name="source_version"
                type="text"
                className="p2-filter-input"
                value={view.controls.filters.source_version ?? ''}
                onChange={(e) =>
                  handleFilterChange('source_version', e.target.value)
                }
                placeholder="確認單版本"
                aria-label="篩選確認單版本"
              />
            </div>

            {/* Quick Filter: PM */}
            <div className="p2-filter-field-inline">
              <label htmlFor={`${baseId}-filter-pm`} className="p2-filter-label">
                負責人
              </label>
              <input
                id={`${baseId}-filter-pm`}
                name="pm"
                type="text"
                className="p2-filter-input"
                value={view.controls.filters.pm ?? ''}
                onChange={(e) => handleFilterChange('pm', e.target.value)}
                placeholder="案件負責人"
                aria-label="篩選案件負責人"
              />
            </div>

            {/* Progressive Disclosure Toggle: 進階篩選 */}
            <button
              type="button"
              className={`p2-btn-advanced-toggle ${advancedOpen ? 'is-active' : ''}`}
              onClick={() => setAdvancedOpen(!advancedOpen)}
              aria-expanded={advancedOpen}
              aria-controls={`${baseId}-advanced-panel`}
            >
              <span>進階篩選</span>
              {hasActiveAdvanced && <span className="p2-filter-active-dot" aria-hidden="true" />}
            </button>
          </div>

          <div className="p2-toolbar-primary-right">
            {/* Reset Filters button */}
            <button
              type="button"
              className="p2-btn-reset-filters"
              onClick={() => {
                if (onFilterChange) {
                  onFilterChange(view.controls.resetFilters.filters);
                } else if (onResetFilters) {
                  onResetFilters();
                }
              }}
              disabled={!hasActiveFilters}
              aria-label="重設篩選條件"
            >
              重設篩選
            </button>

            {/* Column Chooser */}
            <div className="p2-column-chooser-wrapper">
              <button
                id={`${baseId}-chooser-btn`}
                type="button"
                className="p2-btn-chooser"
                aria-expanded={chooserOpen}
                aria-controls={`${baseId}-chooser-panel`}
                onClick={() => setChooserOpen(!chooserOpen)}
              >
                欄位設定
              </button>
              {chooserOpen && (
                <div
                  id={`${baseId}-chooser-panel`}
                  className="p2-column-chooser-panel"
                  role="region"
                  aria-label="欄位顯示設定"
                >
                  <div className="p2-chooser-title">顯示欄位</div>
                  <div className="p2-chooser-list">
                    {view.columns.map((col) => (
                      <label className="p2-chooser-item" key={col.key}>
                        <input
                          type="checkbox"
                          checked={col.visible}
                          onChange={() => onColumnToggle?.(col.key)}
                        />
                        <span>
                          {col.key === 'source_status'
                            ? '來源讀取狀態'
                            : col.label}
                        </span>
                        {col.technical ? (
                          <span className="p2-badge-tech">
                            技術欄位（非預設）
                          </span>
                        ) : !col.default ? (
                          <span className="p2-badge-tech">非預設</span>
                        ) : null}
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Secondary / Advanced Filters (Disclosed progressively) */}
        {advancedOpen && (
          <div
            id={`${baseId}-advanced-panel`}
            className="p2-toolbar-row-advanced"
          >
            {/* Admission filter */}
            <div className="p2-filter-field-inline">
              <label
                htmlFor={`${baseId}-filter-admission`}
                className="p2-filter-label"
              >
                准入狀態
              </label>
              <input
                id={`${baseId}-filter-admission`}
                name="admission"
                type="text"
                className="p2-filter-input"
                value={view.controls.filters.admission ?? ''}
                onChange={(e) => handleFilterChange('admission', e.target.value)}
                placeholder="准入狀態"
                aria-label="篩選准入狀態"
              />
            </div>

            {/* Deadline filter control (disabled with reason) */}
            <div
              className="p2-deadline-filter-group"

            >
              <span className="p2-deadline-filter-label">有效期限（停用）</span>
              <input
                id={`${baseId}-deadline-from`}
                type="text"
                className="p2-deadline-input"
                disabled
                aria-disabled="true"
                value={view.controls.filters.deadline_from ?? ''}
                placeholder="起日"
                aria-label="期限起日（已停用）"
              />
              <span aria-hidden="true">~</span>
              <input
                id={`${baseId}-deadline-to`}
                type="text"
                className="p2-deadline-input"
                disabled
                aria-disabled="true"
                value={view.controls.filters.deadline_to ?? ''}
                placeholder="迄日"
                aria-label="期限迄日（已停用）"
              />
              <span className="p2-deadline-reason" role="note">
                期限來源尚未確認。
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Main Table and Drawer Layout */}
      <div className="confirmation-list-layout">
        <div className="p2-main-content">
          <div className="p2-table-container">
            <div
              className="p2-table-scroll"
              tabIndex={0}
              role="region"
              aria-label="工程確認單清單表格，可左右捲動"
            >
              <table className="p2-table confirmation-list-table is-dense">
                <caption className="p2-sr-only">工程確認單資料清單</caption>
                <thead>
                  <tr>
                    {visibleColumns.map((col) => {
                      const isSorted = view.controls.sort?.key === col.key;
                      const currentDir = isSorted
                        ? view.controls.sort?.dir ?? null
                        : null;
                      const ariaSort: 'ascending' | 'descending' | 'none' =
                        currentDir === 'asc'
                          ? 'ascending'
                          : currentDir === 'desc'
                          ? 'descending'
                          : 'none';

                      const isSticky1 = col.key === stickyCol1;
                      const isSticky2 = col.key === stickyCol2;
                      const stickyClass = isSticky1
                        ? 'p2-col-sticky-1'
                        : isSticky2
                        ? 'p2-col-sticky-2'
                        : '';

                      return (
                        <th
                          key={col.key}
                          scope="col"
                          aria-sort={col.sortable ? ariaSort : undefined}
                          className={stickyClass}
                        >
                          {col.sortable ? (
                            <button
                              type="button"
                              className="p2-sort-btn"
                              onClick={() => handleSortClick(col.key, currentDir)}
                              aria-label={`依${
                                col.key === 'source_status'
                                  ? '來源讀取狀態'
                                  : col.label
                              }排序`}
                            >
                              <span>
                                {col.key === 'source_status'
                                  ? '來源讀取狀態'
                                  : col.label}
                              </span>
                              <span
                                className="p2-sort-icon"
                                aria-hidden="true"
                              >
                                {currentDir === 'asc'
                                  ? ' ↑'
                                  : currentDir === 'desc'
                                  ? ' ↓'
                                  : ' ↕'}
                              </span>
                            </button>
                          ) : (
                            <span
                              className="p2-col-unsortable"

                            >
                              {col.key === 'source_status'
                                ? '來源讀取狀態'
                                : col.label}
                            </span>
                          )}
                        </th>
                      );
                    })}
                    <th scope="col">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {view.table.rows.length === 0 ? (
                    <tr>
                      <td
                        colSpan={visibleColumns.length + 1}
                        className="p2-empty-cell"
                      >
                        {view.pageStateLabel === '狀態未知' ? '確認單清單尚未提供。' : view.pageStateLabel ?? '確認單資料尚未提供。'}
                      </td>
                    </tr>
                  ) : (
                    view.table.rows.map((row: ConfirmationListRow) => {
                      const isSelected =
                        view.drawer.open && view.drawer.row?.key === row.key;

                      return (
                        <tr
                          key={row.key}
                          className={`p2-row ${isSelected ? 'is-selected' : ''}`}
                          onClick={() => onSelect?.(isSelected ? null : row.key)}
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.repeat) return;
                            if (
                              e.target === e.currentTarget &&
                              (e.key === 'Enter' || e.key === ' ')
                            ) {
                              e.preventDefault();
                              onSelect?.(isSelected ? null : row.key);
                            }
                          }}
                        >
                          {visibleColumns.map((col) => {
                            const isSticky1 = col.key === stickyCol1;
                            const isSticky2 = col.key === stickyCol2;
                            const stickyClass = isSticky1
                              ? 'p2-col-sticky-1'
                              : isSticky2
                              ? 'p2-col-sticky-2'
                              : '';

                            const cell = row.cells[col.key];

                            // Row title column: activates onNavigate (case detail)
                            if (col.key === 'project_name') {
                              return (
                                <td key={col.key} className={stickyClass}>
                                  <button
                                    type="button"
                                    className="p2-row-title-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onNavigate?.(row.key);
                                    }}
                                    aria-label={
                                      cell?.label && cell.label !== '—'
                                        ? `查看案件詳情：${cell.label}`
                                        : '查看案件詳情'
                                    }
                                  >
                                    <strong>{cell?.label ?? '—'}</strong>
                                  </button>

                                </td>
                              );
                            }

                            if (col.key === 'case_number') {
                              return (
                                <td key={col.key} className={stickyClass}>
                                  <strong className="p2-cell-text">
                                    {cell?.label ?? '—'}
                                  </strong>
                                </td>
                              );
                            }

                            if (col.key === 'source_status') {
                              return (
                                <td key={col.key} className={stickyClass}>
                                  <span className="p2-badge p2-badge-status">
                                    {row.sourceStatusLabel}
                                  </span>
                                </td>
                              );
                            }

                            return (
                              <td key={col.key} className={stickyClass}>
                                <span
                                  className={
                                    !cell || cell.label === '—'
                                      ? 'p2-cell-unknown'
                                      : 'p2-cell-text'
                                  }

                                >
                                  {cell?.label ?? '—'}
                                </span>
                              </td>
                            );
                          })}

                          {/* Action / Selection column */}
                          <td>
                            <button
                              type="button"
                              ref={(el) => {
                                if (el) {
                                  rowSelectButtonRefs.current.set(row.key, el);
                                } else {
                                  rowSelectButtonRefs.current.delete(row.key);
                                }
                              }}
                              className="p2-btn-select"
                              aria-expanded={isSelected}
                              onClick={(e) => {
                                e.stopPropagation();
                                onSelect?.(isSelected ? null : row.key);
                              }}
                              aria-label={
                                row.cells.case_number?.label &&
                                row.cells.case_number.label !== '—'
                                  ? `選取來源資訊：${row.cells.case_number.label}`
                                  : '選取來源資訊'
                              }
                            >
                              {isSelected ? '收合' : '選取'}
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Table Footer with separate matching, loaded and authorizedSource totals */}
            <footer
              className="p2-table-footer"
              role="region"
              aria-label="清單資料統計"
            >
              <div className="p2-footer-totals">
                {!view.footer.matching.reason && <span>符合條件 {view.footer.matching.label} 筆</span>}
                {!view.footer.loaded.reason && <span>已載入筆數：{view.footer.loaded.label}</span>}
                {!view.footer.authorizedSource.reason && <span>已授權來源 {view.footer.authorizedSource.label} 筆</span>}
              </div>

              {/* Server-cursor Next/Prev pagination */}
              <nav className="p2-pagination" aria-label="分頁導覽">
                <button
                  type="button"
                  className="p2-page-btn"
                  disabled={!view.pagination.previous.enabled}
                  onClick={() => onPage?.(view.pagination.previous.cursor)}

                  aria-label="上一頁"
                >
                  上一頁
                </button>
                <button
                  type="button"
                  className="p2-page-btn"
                  disabled={!view.pagination.next.enabled}
                  onClick={() => onPage?.(view.pagination.next.cursor)}

                  aria-label="下一頁"
                >
                  下一頁
                </button>

              </nav>
            </footer>
          </div>
        </div>

        {/* Selection-only Source Drawer */}
        {view.drawer.open && view.drawer.detail && (
          <aside
            className="p2-drawer confirmation-source-drawer"
            role="region"
            aria-label={`來源詳情：${
              view.drawer.row?.cells.case_number?.label ??
              view.drawer.detail.recordId
            }`}
          >
            <div className="p2-drawer-header">
              <div>
                <h3 className="p2-drawer-title">來源資料脈絡</h3>
                <span className="p2-meta-item">
                  {view.drawer.row?.cells.case_number?.label ?? '—'} ·{' '}
                  {view.drawer.row?.cells.project_name?.label ?? '—'}
                </span>
              </div>
              <button
                type="button"
                className="p2-drawer-close-btn"
                onClick={() => onSelect?.(null)}
                aria-label="關閉來源詳情抽屜"
              >
                關閉
              </button>
            </div>

            <div className="p2-drawer-body">
              {/* Technical IDs appear ONLY here in the drawer */}
              <div className="p2-drawer-section">
                <h4 className="p2-drawer-section-title">原生識別代碼</h4>
                <dl className="p2-dl">
                  <div>
                    <dt>來源記錄 ID</dt>
                    <dd>
                      <code>{view.drawer.detail.recordId}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>來源資料庫代碼</dt>
                    <dd>
                      <code>{view.drawer.detail.sourceContext.baseToken}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>來源表格代碼</dt>
                    <dd>
                      <code>{view.drawer.detail.sourceContext.tableId}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>案件 ID</dt>
                    <dd>
                      {view.drawer.detail.projectId ? (
                        <code>{view.drawer.detail.projectId}</code>
                      ) : (
                        '—'
                      )}
                    </dd>
                  </div>
                </dl>
              </div>

              {/* Withheld amounts from view model */}
              <div className="p2-drawer-section">
                <h4 className="p2-drawer-section-title">合約金額</h4>
                <dl className="p2-dl">
                  <div>
                    <dt>顯示狀態</dt>
                    <dd>
                      <span className="p2-amount-withheld">
                        {view.amounts.label}
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

              {/* Row Status & Metadata */}
              {view.drawer.row && (
                <div className="p2-drawer-section">
                  <h4 className="p2-drawer-section-title">資料保留與對應狀態</h4>
                  <dl className="p2-dl">
                    <div>
                      <dt>來源狀態</dt>
                      <dd>
                        <span className="p2-badge p2-badge-status">
                          {view.drawer.row.sourceStatusLabel}
                        </span>
                      </dd>
                    </div>
                    <div>
                      <dt>保留讀取</dt>
                      <dd>
                        <span className="p2-badge p2-badge-retention">
                          {view.drawer.row.retentionLabel}
                        </span>
                      </dd>
                    </div>
                    <div>
                      <dt>案件連結</dt>
                      <dd>
                        <span
                          className={`p2-badge ${
                            view.drawer.row.caseLink.state === 'unresolved'
                              ? 'p2-badge-unresolved'
                              : 'p2-badge-verification'
                          }`}
                        >
                          {view.drawer.row.caseLink.label}
                        </span>
                        {view.drawer.row.caseLink.reason && (
                          <small className="p2-amount-reason">
                            （案件對應尚待核對。）
                          </small>
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>准入狀態</dt>
                      <dd>
                        {view.drawer.row.cells.admission_state?.label ?? '—'}
                      </dd>
                    </div>
                    <div>
                      <dt>流程摘要</dt>
                      <dd>
                        {view.drawer.row.cells.workflow_summary?.label ?? '—'}
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
  );
}
