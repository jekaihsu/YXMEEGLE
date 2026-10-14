import { useRef, useEffect } from 'react';
import type {
  ContractDetailView,
  NavTarget,
  Cell,
} from './contractDetailView.ts';
import { CONTRACT_LABELS } from './contractDetailView.ts';
import './p2-detail.css';

export interface ContractDetailProps {
  view: ContractDetailView;
  onSelect?: (key: string | null) => void;
  onSort?: (column: string) => void;
  onNavigate?: (target: NavTarget) => void;
  onBack?: () => void;
}

function renderCell(cell: Cell) {
  if (cell.kind === 'unknown') {
    return (
      <span className="p2-cell-unknown" title={cell.reason}>
        {cell.text}
      </span>
    );
  }
  if (cell.kind === 'withheld') {
    return (
      <span className="p2-cell-withheld" title={cell.reason}>
        {cell.text}
      </span>
    );
  }
  return <span className="p2-cell-text">{cell.text}</span>;
}

export function ContractDetail({
  view,
  onSelect,
  onSort,
  onNavigate,
  onBack,
}: ContractDetailProps) {
  const rowSelectButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const prevDrawerKeyRef = useRef<string | null>(view.drawer?.identity.sourceKey ?? null);

  useEffect(() => {
    const currentKey = view.drawer?.identity.sourceKey ?? null;
    const prevKey = prevDrawerKeyRef.current;
    prevDrawerKeyRef.current = currentKey;

    if (prevKey !== null && currentKey === null) {
      const btn = rowSelectButtonRefs.current.get(prevKey);
      btn?.focus();
    }
  }, [view.drawer]);

  // Page-level non-ready / state view
  if (view.kind === 'state') {
    return (
      <div className="p2-detail-root">
        <section
          className={`p2-banner ${view.page.states.map(s => `state-${s}`).join(' ')}`}
          role="status"
          aria-live="polite"
          aria-label="合約明細資料狀態"
        >
          <div className="p2-banner-header">
            <span className="p2-banner-title">合約明細資料狀態</span>
            <span className="p2-badge" data-state={view.page.states[0]}>
              {view.page.label}
            </span>
          </div>
          {view.page.note && <p className="p2-banner-note">{view.page.note}</p>}
          {view.page.reason && <p className="p2-banner-reason">{view.page.reason}</p>}
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

  const currentEntry = view.directory?.entries.find(e => e.selected);
  const mainKey = currentEntry?.navKey ?? null;

  return (
    <div className="p2-detail-root">
      {/* 頁面資料狀態橫幅 (Page State Banner) */}
      <section
        className={`p2-banner ${view.page.states.map(s => `state-${s}`).join(' ')}`}
        role="status"
        aria-live="polite"
        aria-label="頁面資料狀態"
      >
        <div className="p2-banner-header">
          <span className="p2-banner-title">資料狀態</span>
          <span className="p2-badge" data-state={view.page.states[0]}>
            {view.page.label}
          </span>
        </div>
        {view.page.note && <p className="p2-banner-note">{view.page.note}</p>}
      </section>

      {/* 路徑導覽 (Breadcrumb) */}
      <nav className="p2-breadcrumb" aria-label="路徑導覽">
        <ol className="p2-breadcrumb-list">
          {view.breadcrumb.map((crumb, idx) => {
            const isLast = idx === view.breadcrumb.length - 1;
            return (
              <li key={`crumb-${idx}-${crumb.label}`} className="p2-breadcrumb-item">
                {idx > 0 && <span className="p2-breadcrumb-separator" aria-hidden="true">/</span>}
                {crumb.nav ? (
                  <button
                    type="button"
                    className="p2-breadcrumb-link"
                    onClick={() => onNavigate?.(crumb.nav!)}
                    aria-label={`導向 ${crumb.label}`}
                  >
                    {crumb.label}
                  </button>
                ) : (
                  <span
                    className={`p2-breadcrumb-text ${isLast ? 'p2-breadcrumb-current' : ''} ${
                      crumb.kind === 'unresolved' ? 'p2-breadcrumb-unresolved' : ''
                    }`}
                    aria-current={isLast ? 'page' : undefined}
                  >
                    {crumb.label}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      </nav>

      {/* 標頭資訊 (Header) */}
      {view.header && (
        <header className="p2-header">
          <div className="p2-header-title-row">
            <h1 className="p2-header-title">
              {view.header.title.kind === 'text' ? view.header.title.text : renderCell(view.header.title)}
            </h1>
            {view.header.lineNumber.kind === 'text' && (
              <span className="p2-line-number-badge">{view.header.lineNumber.text}</span>
            )}
            <span className="p2-badge p2-badge-source">{view.header.versionLabel}</span>
            <span className="p2-badge p2-badge-verification">{view.header.edgeLabel}</span>
          </div>
          <div className="p2-header-meta">
            <span className="p2-meta-item">{view.header.sourceLabel}</span>
            <span className="p2-meta-item">
              來源更新時間：{renderCell(view.header.sourceUpdated)}
            </span>
          </div>
        </header>
      )}

      {/* 主體與側欄佈局 (Main Layout) */}
      <div className="p2-main-layout">
        {/* 同確認單合約明細目錄 (Sibling Directory) */}
        {view.directory && (
          <aside className="p2-sibling-directory" aria-label="同確認單合約明細清單">
            <div className="p2-card-header">
              <h2 className="p2-section-title">同確認單明細</h2>
              <span className="p2-badge">{view.directory.state.label}</span>
            </div>
            {view.directory.note && (
              <p className="p2-directory-note">{view.directory.note}</p>
            )}
            <ul className="p2-sibling-list">
              {view.directory.entries.map((entry, idx) => {
                const entryKey = entry.navKey ?? `unlocated-sibling-${idx}`;
                return (
                  <li
                    key={entryKey}
                    className={`p2-sibling-item ${entry.selected ? 'is-selected' : ''}`}
                    aria-current={entry.selected ? 'true' : undefined}
                  >
                    {entry.selected ? (
                      <div className="p2-sibling-current">
                        <span className="p2-sibling-num">{renderCell(entry.lineNumber)}</span>
                        <span className="p2-sibling-name">{renderCell(entry.name)}</span>
                        <span className="p2-badge p2-badge-current">{CONTRACT_LABELS.selectedCurrent}</span>
                      </div>
                    ) : entry.nav ? (
                      <button
                        type="button"
                        className="p2-sibling-link"
                        onClick={() => onNavigate?.(entry.nav!)}
                        aria-label={`前往合約明細 ${entry.name.kind === 'text' ? entry.name.text : ''}`}
                      >
                        <span className="p2-sibling-num">{renderCell(entry.lineNumber)}</span>
                        <span className="p2-sibling-name">{renderCell(entry.name)}</span>
                      </button>
                    ) : (
                      <div className="p2-sibling-unresolved">
                        <span className="p2-sibling-num">{renderCell(entry.lineNumber)}</span>
                        <span className="p2-sibling-name">{renderCell(entry.name)}</span>
                        {entry.unresolvedLabel && (
                          <span className="p2-unresolved-label">{entry.unresolvedLabel}</span>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </aside>
        )}

        {/* 主內容區與抽屜 (Content Area with Drawer) */}
        <div className="p2-layout-with-drawer">
          <div className="p2-primary-column">
            {/* 合約明細主體區塊 (Main Line Block) */}
            {view.main && (
              <section className="p2-card p2-main-block" aria-label="合約明細主體資訊">
                <div className="p2-card-header">
                  <div className="p2-card-header-left">
                    <h2 className="p2-section-title">明細主體</h2>
                    <span className="p2-badge">{view.main.state.label}</span>
                  </div>
                  {mainKey && (
                    <button
                      type="button"
                      ref={el => {
                        if (el) rowSelectButtonRefs.current.set(mainKey, el);
                        else rowSelectButtonRefs.current.delete(mainKey);
                      }}
                      className="p2-btn p2-btn-select p2-btn-sm"
                      aria-expanded={view.drawer?.identity.sourceKey === mainKey}
                      onClick={() => {
                        const isSel = view.drawer?.identity.sourceKey === mainKey;
                        onSelect?.(isSel ? null : mainKey);
                      }}
                    >
                      {view.drawer?.identity.sourceKey === mainKey ? '收合原生明細' : '檢視原生明細'}
                    </button>
                  )}
                </div>
                <dl className="p2-def-grid">
                  <div className="p2-def-item">
                    <dt>項次代碼</dt>
                    <dd>{renderCell(view.main.lineNumber)}</dd>
                  </div>
                  <div className="p2-def-item">
                    <dt>名稱</dt>
                    <dd>{renderCell(view.main.name)}</dd>
                  </div>
                  <div className="p2-def-item">
                    <dt>{CONTRACT_LABELS.columns.quantity}</dt>
                    <dd>{renderCell(view.main.quantity)}</dd>
                  </div>
                  <div className="p2-def-item">
                    <dt>{CONTRACT_LABELS.columns.unit}</dt>
                    <dd>{renderCell(view.main.unit)}</dd>
                  </div>
                  <div className="p2-def-item">
                    <dt>原始金額</dt>
                    <dd>{renderCell(view.main.originalAmount)}</dd>
                  </div>
                  <div className="p2-def-item">
                    <dt>現行修訂金額</dt>
                    <dd>{renderCell(view.main.currentRevisedAmount)}</dd>
                  </div>
                  <div className="p2-def-item">
                    <dt>修訂原因</dt>
                    <dd>{renderCell(view.main.revisionReason)}</dd>
                  </div>
                  <div className="p2-def-item">
                    <dt>版本</dt>
                    <dd><span className="p2-badge">{view.main.versionLabel}</span></dd>
                  </div>
                </dl>
              </section>
            )}

            {/* 下游工項清單表格 (Child Work Items Table) */}
            {view.workItems && (
              <section className="p2-card p2-work-items-section" aria-label="下游工項清單">
                <div className="p2-card-header">
                  <div className="p2-card-header-left">
                    <h2 className="p2-section-title">下游工項</h2>
                    <span className="p2-badge">{view.workItems.state.label}</span>
                    <span className="p2-badge p2-badge-verification">{view.workItems.edgeLabel}</span>
                  </div>
                  <p className="p2-order-disclosure">{view.workItems.orderDisclosure}</p>
                </div>

                <div className="p2-table-wrapper" tabIndex={0} role="region" aria-label="工項清單表格">
                  <table className="p2-table">
                    <caption className="p2-sr-only">下游工項清單</caption>
                    <thead>
                      <tr>
                        <th scope="col">{CONTRACT_LABELS.columns.name}</th>
                        <th
                          scope="col"
                          aria-sort={
                            view.workItems.sort?.key === 'category'
                              ? view.workItems.sort.dir === 'asc'
                                ? 'ascending'
                                : 'descending'
                              : 'none'
                          }
                          className="p2-th-sortable"
                        >
                          <button
                            type="button"
                            className="p2-sort-btn"
                            onClick={() => onSort?.('category')}
                            aria-label={`依${CONTRACT_LABELS.columns.category}排序`}
                          >
                            <span>{CONTRACT_LABELS.columns.category}</span>
                            <span className="p2-sort-icon" aria-hidden="true">
                              {view.workItems.sort?.key === 'category'
                                ? view.workItems.sort.dir === 'asc'
                                  ? ' ↑'
                                  : ' ↓'
                                : ' ↕'}
                            </span>
                          </button>
                        </th>
                        <th scope="col">{CONTRACT_LABELS.columns.quantity}</th>
                        <th scope="col">{CONTRACT_LABELS.columns.unit}</th>
                        <th scope="col">{CONTRACT_LABELS.columns.state}</th>
                        <th scope="col">{CONTRACT_LABELS.columns.person}</th>
                        <th scope="col">{CONTRACT_LABELS.columns.deliverables}</th>
                        <th scope="col">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {view.workItems.rows.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="p2-table-empty">
                            {view.workItems.emptyMessage ?? view.workItems.state.label}
                          </td>
                        </tr>
                      ) : (
                        view.workItems.rows.map(row => {
                          const isSelected = view.drawer?.identity.sourceKey === row.navKey;
                          return (
                            <tr
                              key={row.navKey}
                              data-key={row.navKey}
                              aria-selected={isSelected}
                              className={`p2-tr ${isSelected ? 'is-selected' : ''}`}
                              onClick={() => onSelect?.(isSelected ? null : row.navKey)}
                            >
                              <td>
                                <button
                                  type="button"
                                  className="p2-cell-link"
                                  onClick={e => {
                                    e.stopPropagation();
                                    onNavigate?.(row.nav);
                                  }}
                                  aria-label={`前往工項 ${row.name.kind === 'text' ? row.name.text : row.navKey}`}
                                >
                                  {renderCell(row.name)}
                                </button>
                              </td>
                              <td>{renderCell(row.category)}</td>
                              <td>{renderCell(row.quantity)}</td>
                              <td>{renderCell(row.unit)}</td>
                              <td>{renderCell(row.state)}</td>
                              <td>{renderCell(row.person)}</td>
                              <td>{renderCell(row.deliverables)}</td>
                              <td>
                                <div className="p2-row-actions">
                                  <button
                                    type="button"
                                    ref={el => {
                                      if (el) rowSelectButtonRefs.current.set(row.navKey, el);
                                      else rowSelectButtonRefs.current.delete(row.navKey);
                                    }}
                                    className="p2-btn p2-btn-sm p2-btn-select"
                                    aria-expanded={isSelected}
                                    onClick={e => {
                                      e.stopPropagation();
                                      onSelect?.(isSelected ? null : row.navKey);
                                    }}
                                  >
                                    {isSelected ? '收合' : '詳情'}
                                  </button>
                                  <button
                                    type="button"
                                    className="p2-btn p2-btn-sm p2-btn-primary"
                                    onClick={e => {
                                      e.stopPropagation();
                                      onNavigate?.(row.nav);
                                    }}
                                  >
                                    開啟
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* 版本歷程 (Version History) */}
            {view.versionHistory && (
              <section className="p2-card p2-version-history-section" aria-label="版本歷程">
                <div className="p2-card-header">
                  <h2 className="p2-section-title">版本歷程</h2>
                  <span className="p2-badge">{view.versionHistory.state.label}</span>
                </div>
                <div className="p2-version-meta">
                  <div className="p2-version-meta-item">
                    <span className="p2-meta-label">現行版本：</span>
                    <span className="p2-badge">{view.versionHistory.currentVersionLabel}</span>
                  </div>
                  <div className="p2-version-meta-item">
                    <span className="p2-meta-label">{CONTRACT_LABELS.effectiveVersion}：</span>
                    <span>{renderCell(view.versionHistory.effectiveVersion)}</span>
                  </div>
                  <div className="p2-version-meta-item">
                    <span className="p2-meta-label">正式修訂：</span>
                    <span className="p2-badge">{view.versionHistory.formalRevisions.label}</span>
                  </div>
                </div>

                {view.versionHistory.observations.length > 0 && (
                  <div className="p2-observations-list">
                    <h3 className="p2-subheading">觀測紀錄</h3>
                    {view.versionHistory.observations.map((obs, idx) => (
                      <div key={`obs-${idx}-${obs.versionLabel}`} className="p2-observation-card">
                        <div className="p2-observation-header">
                          <span className="p2-badge p2-badge-obs">{obs.label}</span>
                          <span className="p2-observation-version">{obs.versionLabel}</span>
                        </div>
                        <dl className="p2-def-grid p2-def-grid-sm">
                          <div className="p2-def-item">
                            <dt>原始金額</dt>
                            <dd>{renderCell(obs.line.originalAmount)}</dd>
                          </div>
                          <div className="p2-def-item">
                            <dt>現行修訂金額</dt>
                            <dd>{renderCell(obs.line.currentRevisedAmount)}</dd>
                          </div>
                          <div className="p2-def-item">
                            <dt>修訂原因</dt>
                            <dd>{renderCell(obs.line.revisionReason)}</dd>
                          </div>
                        </dl>
                        {obs.sourceFields.length > 0 && (
                          <div className="p2-source-fields">
                            <h4 className="p2-field-heading">原生欄位觀測</h4>
                            <ul className="p2-field-list">
                              {obs.sourceFields.map((f, fIdx) => (
                                <li key={`obs-field-${fIdx}-${f.field}`} className="p2-field-item">
                                  <span className="p2-field-name">{f.field}：</span>
                                  <span className="p2-field-val">{f.value}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            {/* 關聯與警示摘要 (Summary & Warnings) */}
            {view.summary && (
              <section className="p2-card p2-summary-section" aria-label="關聯與警示摘要">
                <div className="p2-card-header">
                  <h2 className="p2-section-title">關聯與警示</h2>
                  <span className="p2-badge">{view.summary.relationship.label}</span>
                </div>
                {view.summary.warnings.length > 0 && (
                  <ul className="p2-warnings-list">
                    {view.summary.warnings.map(w => (
                      <li key={w.code} className="p2-warning-item">
                        <span className="p2-warning-icon" aria-hidden="true">⚠️</span>
                        <span className="p2-warning-text">{w.label}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
          </div>

          {/* 原生詳情抽屜 (Selection-only Details Drawer) */}
          {view.drawer && (
            <aside
              className="p2-drawer"
              role="region"
              aria-label={
                view.drawer.kind === 'contract_line'
                  ? '合約明細原生詳情抽屜'
                  : '工項原生詳情抽屜'
              }
            >
              <div className="p2-drawer-header">
                <h3 className="p2-drawer-title">
                  {view.drawer.kind === 'contract_line' ? '合約明細原生資訊' : '工項原生資訊'}
                </h3>
                <button
                  type="button"
                  className="p2-btn p2-btn-sm p2-btn-close"
                  onClick={() => {
                    const keyToRestore = view.drawer?.identity.sourceKey;
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
                    <div>
                      <dt>來源鍵</dt>
                      <dd><code>{view.drawer.identity.sourceKey}</code></dd>
                    </div>
                    <div>
                      <dt>Base</dt>
                      <dd><code>{view.drawer.identity.base}</code></dd>
                    </div>
                    <div>
                      <dt>Table</dt>
                      <dd><code>{view.drawer.identity.table}</code></dd>
                    </div>
                    <div>
                      <dt>Record ID</dt>
                      <dd><code>{view.drawer.identity.recordId}</code></dd>
                    </div>
                    {view.drawer.identity.version && (
                      <div>
                        <dt>版本</dt>
                        <dd><code>{view.drawer.identity.version}</code></dd>
                      </div>
                    )}
                  </dl>
                </div>

                <div className="p2-drawer-section">
                  <h4 className="p2-drawer-section-title">關聯驗證與金額規則</h4>
                  <p className="p2-drawer-text">
                    關聯驗證：<span className="p2-badge">{view.drawer.edgeVerification}</span>
                  </p>
                  <p className="p2-drawer-text p2-drawer-alert">{view.drawer.amountNote}</p>
                  {view.drawer.relationship && (
                    <p className="p2-drawer-text">關聯計數：{view.drawer.relationship.label}</p>
                  )}
                  {view.drawer.mapping && (
                    <p className="p2-drawer-text">對應狀態：{view.drawer.mapping.label}</p>
                  )}
                </div>

                {view.drawer.sourceFields.length > 0 && (
                  <div className="p2-drawer-section">
                    <h4 className="p2-drawer-section-title">已授權原生欄位</h4>
                    <ul className="p2-drawer-fields-list">
                      {view.drawer.sourceFields.map((f, i) => (
                        <li key={`df-${i}-${f.field}`} className="p2-drawer-field-item">
                          <span className="p2-df-name">{f.field}</span>
                          <span className="p2-df-val">{f.value}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {view.drawer.warnings.length > 0 && (
                  <div className="p2-drawer-section">
                    <h4 className="p2-drawer-section-title">警示事項</h4>
                    <ul className="p2-warnings-list">
                      {view.drawer.warnings.map(w => (
                        <li key={`dw-${w.code}`} className="p2-warning-item">
                          <span className="p2-warning-icon" aria-hidden="true">⚠️</span>
                          <span className="p2-warning-text">{w.label}</span>
                        </li>
                      ))}
                    </ul>
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
