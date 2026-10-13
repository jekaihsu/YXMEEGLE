import {useRef, useEffect} from 'react';
import type {SourceHealthView, SourceRow, SortColumn} from './sourceHealthView.ts';
import './source-health.css';

export interface SourceHealthProps {
  view?: SourceHealthView | null;
  onSelect?: (key: string | null) => void;
  onSort?: (column: SortColumn) => void;
  onRetry?: (handle: unknown) => void;
  currentSort?: {column: SortColumn; direction: 'asc' | 'desc' | 'clear'} | null;
}

function renderCount(val: number | null | undefined): string {
  if (val === null || val === undefined) return '未知';
  return String(val);
}

export function SourceHealth({view, onSelect, onSort, onRetry, currentSort}: SourceHealthProps) {
  const page = view?.page;
  const pageStates = page?.states ?? ['unknown'];
  const pageStatusLabel = page?.statusLabel ?? '狀態未知';
  const pageExplanation = page?.explanation ?? '目前無法確認資料狀態，請聯絡管理員。';

  const diagnostic = view?.diagnostic ?? null;
  const rows = diagnostic?.rows ?? [];
  const selectedKey = diagnostic?.selectedKey ?? null;
  const drawer = diagnostic?.drawer ?? null;
  const summary = diagnostic?.summary ?? null;

  const prevSelectedKeyRef = useRef<string | null>(selectedKey);
  const lastTriggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const prevKey = prevSelectedKeyRef.current;
    prevSelectedKeyRef.current = selectedKey;

    if (prevKey !== null && selectedKey === null) {
      if (lastTriggerRef.current && document.contains(lastTriggerRef.current)) {
        lastTriggerRef.current.focus();
      } else {
        const rowEl = document.querySelector<HTMLElement>(`.source-health-row[data-key="${prevKey}"]`);
        if (rowEl) {
          const selectBtn = rowEl.querySelector<HTMLElement>('.source-health-btn-select');
          if (selectBtn) {
            selectBtn.focus();
          } else {
            rowEl.focus();
          }
        }
      }
    }
  }, [selectedKey]);

  const getAriaSort = (col: SortColumn): 'ascending' | 'descending' | 'none' => {
    if (currentSort && currentSort.column === col) {
      if (currentSort.direction === 'asc') return 'ascending';
      if (currentSort.direction === 'desc') return 'descending';
    }
    return 'none';
  };

  const renderSortHeader = (col: SortColumn, title: string) => {
    const ariaSort = getAriaSort(col);
    return (
      <th key={col} scope="col" aria-sort={ariaSort} className="source-health-th-sortable">
        <button
          type="button"
          className="source-health-sort-btn"
          onClick={() => onSort?.(col)}
          aria-label={`依${title}排序`}
        >
          <span>{title}</span>
          <span className="source-health-sort-icon" aria-hidden="true">
            {ariaSort === 'ascending' ? ' ↑' : ariaSort === 'descending' ? ' ↓' : ' ↕'}
          </span>
        </button>
      </th>
    );
  };

  return (
    <div className="source-health-root">
      {/* 頁面資料狀態橫幅 (Page state banner for every C-STATE value including view.page null) */}
      <section
        className={`source-health-banner ${pageStates.map(s => `state-${s}`).join(' ')}`}
        data-state={pageStates.join(' ')}
        role="status"
        aria-live="polite"
        aria-label="頁面資料狀態"
      >
        <div className="source-health-banner-header">
          <span className="source-health-banner-title">頁面資料狀態</span>
          <span className="source-health-status-badge" data-state={pageStates[0] ?? 'unknown'}>
            {pageStatusLabel}
          </span>
        </div>
        <p className="source-health-banner-explanation">{pageExplanation}</p>
      </section>

      {/* 診斷區塊 (Diagnostic section only when view.diagnostic is non-null) */}
      {diagnostic !== null && (
        <section className="source-health-diagnostic-section" aria-label="來源健康診斷">
          {/* 頂部資訊列 (Header / Summary bar) */}
          <div className="source-health-summary-bar">
            <div className="source-health-summary-title-area">
              <h2 className="source-health-summary-title">來源與資料健康</h2>
              <p className="source-health-summary-subtitle">僅顯示已授權來源資訊</p>
            </div>
            <div className="source-health-summary-meta">
              <div className="source-health-meta-item">
                <span className="source-health-meta-label">最近讀取成功：</span>
                <span className="source-health-meta-value">{summary?.last_success.label ?? '未知'}</span>
              </div>
            </div>
          </div>

          <div className="source-health-layout">
            {/* 主表格區塊 (Table section) */}
            <div className="source-health-table-container">
              <div className="source-health-table-scroll" tabIndex={0} role="region" aria-label="來源資料清單表格">
                <table className="source-health-table">
                  <thead>
                    <tr>
                      {renderSortHeader('name', '來源名稱')}
                      {renderSortHeader('key', '來源代碼')}
                      <th scope="col">版本</th>
                      <th scope="col">讀取狀態</th>
                      <th scope="col">需要注意</th>
                      <th scope="col">對應狀態</th>
                      <th scope="col">載入筆數</th>
                      {renderSortHeader('last_attempt', '最近嘗試')}
                      {renderSortHeader('last_success', '最近成功')}
                      {renderSortHeader('source_updated', '來源更新時間')}
                      <th scope="col">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.length === 0 ? (
                      <tr>
                        <td colSpan={11} className="source-health-empty-cell">
                          尚無符合條件的來源資料
                        </td>
                      </tr>
                    ) : (
                      rows.map(row => {
                        const isSelected = selectedKey !== null && row.key === selectedKey;
                        return (
                          <tr
                            key={row.key}
                            data-key={row.key}
                            tabIndex={0}
                            aria-selected={isSelected}
                            aria-current={isSelected ? 'true' : undefined}
                            className={`source-health-row ${isSelected ? 'is-selected' : ''} ${
                              row.needsAttention ? 'needs-attention' : ''
                            }`}
                            onClick={e => {
                              lastTriggerRef.current = e.currentTarget;
                              onSelect?.(isSelected ? null : row.key);
                            }}
                            onKeyDown={e => {
                              if (e.target !== e.currentTarget) return;
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                lastTriggerRef.current = e.currentTarget;
                                onSelect?.(isSelected ? null : row.key);
                              }
                            }}
                          >
                            <td className="source-health-cell-name">
                              <strong>{row.name ?? '未知'}</strong>
                            </td>
                            <td className="source-health-cell-key">
                              <code>{row.key}</code>
                            </td>
                            <td className="source-health-cell-version">{row.version ?? '未知'}</td>
                            <td className="source-health-cell-status">
                              <span className="source-health-tag" data-attention={row.needsAttention}>
                                {row.statusLabel}
                              </span>
                            </td>
                            <td className="source-health-cell-attention">
                              {row.needsAttention && (
                                <span className="source-health-attention-tag active">
                                  需要注意
                                </span>
                              )}
                            </td>
                            <td className="source-health-cell-stage">
                              <span className="source-health-mapping-tag">{row.mappingLabel}</span>
                            </td>
                            <td className="source-health-cell-count">{renderCount(row.counts.loaded)}</td>
                            <td className="source-health-cell-time">{row.last_attempt.label}</td>
                            <td className="source-health-cell-time">{row.last_success.label}</td>
                            <td className="source-health-cell-time">{row.source_updated.label}</td>
                            <td className="source-health-cell-actions">
                              <div className="source-health-row-actions">
                                <button
                                  type="button"
                                  className="source-health-btn-select"
                                  aria-expanded={isSelected}
                                  onClick={e => {
                                    e.stopPropagation();
                                    lastTriggerRef.current = e.currentTarget;
                                    onSelect?.(isSelected ? null : row.key);
                                  }}
                                  onKeyDown={e => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                      e.preventDefault();
                                      e.stopPropagation();
                                      lastTriggerRef.current = e.currentTarget;
                                      onSelect?.(isSelected ? null : row.key);
                                    }
                                  }}
                                >
                                  {isSelected ? '收合' : '詳情'}
                                </button>
                                {row.retry !== null && (
                                  <button
                                    type="button"
                                    className="source-health-btn-retry"
                                    onClick={e => {
                                      e.stopPropagation();
                                      onRetry?.(row.retry!.handle);
                                    }}
                                    onKeyDown={e => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        e.stopPropagation();
                                        onRetry?.(row.retry!.handle);
                                      }
                                    }}
                                  >
                                    重試
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 詳情抽屜 (Drawer only after selection, below table at <=600px) */}
            {drawer !== null && (
              <aside className="source-health-drawer" aria-label={`來源詳情：${drawer.name ?? drawer.key}`}>
                <div className="source-health-drawer-header">
                  <div className="source-health-drawer-title-group">
                    <h3 className="source-health-drawer-title">{drawer.name ?? drawer.key}</h3>
                    <code className="source-health-drawer-key">{drawer.key}</code>
                  </div>
                  <button
                    type="button"
                    className="source-health-drawer-close-btn"
                    onClick={() => onSelect?.(null)}
                    aria-label="關閉來源詳情抽屜"
                  >
                    關閉
                  </button>
                </div>

                <div className="source-health-drawer-body">
                  {/* 狀態與注意標籤 */}
                  <div className="source-health-drawer-section">
                    <h4 className="source-health-drawer-section-title">資料狀態</h4>
                    <div className="source-health-drawer-badge-group">
                      <span className="source-health-tag" data-attention={drawer.needsAttention}>
                        {drawer.statusLabel}
                      </span>
                      {drawer.needsAttention && (
                        <span className="source-health-attention-tag active">
                          需要注意
                        </span>
                      )}
                    </div>
                  </div>

                  {/* 原生識別代碼 (Identifiers) */}
                  <div className="source-health-drawer-section">
                    <h4 className="source-health-drawer-section-title">原生識別代碼</h4>
                    <dl className="source-health-dl">
                      <div>
                        <dt>Base ID</dt>
                        <dd>{drawer.identifiers.base ?? '未知'}</dd>
                      </div>
                      <div>
                        <dt>Table ID</dt>
                        <dd>{drawer.identifiers.table ?? '未知'}</dd>
                      </div>
                      <div>
                        <dt>View ID</dt>
                        <dd>{drawer.identifiers.view ?? '未知'}</dd>
                      </div>
                      <div>
                        <dt>截止規則</dt>
                        <dd>{drawer.cutoffRule ?? '未知'}</dd>
                      </div>
                    </dl>
                  </div>

                  {/* 各範圍筆數 (Scoped Counts: unknown is never 0) */}
                  <div className="source-health-drawer-section">
                    <h4 className="source-health-drawer-section-title">資料範圍筆數</h4>
                    <dl className="source-health-dl">
                      <div>
                        <dt>全表總數</dt>
                        <dd>{renderCount(drawer.counts.whole_table)}</dd>
                      </div>
                      <div>
                        <dt>檢視筆數</dt>
                        <dd>{renderCount(drawer.counts.view)}</dd>
                      </div>
                      <div>
                        <dt>載入筆數</dt>
                        <dd>{renderCount(drawer.counts.loaded)}</dd>
                      </div>
                      <div>
                        <dt>排除筆數</dt>
                        <dd>{renderCount(drawer.counts.excluded)}</dd>
                      </div>
                    </dl>
                  </div>

                  {/* 對應狀態 */}
                  <div className="source-health-drawer-section">
                    <h4 className="source-health-drawer-section-title">對應狀態</h4>
                    <dl className="source-health-dl">
                      <div>
                        <dt>對應狀態</dt>
                        <dd>{drawer.mappingLabel}</dd>
                      </div>
                    </dl>
                  </div>

                  {/* 時間紀錄 (Timestamps) */}
                  <div className="source-health-drawer-section">
                    <h4 className="source-health-drawer-section-title">時間紀錄</h4>
                    <dl className="source-health-dl">
                      <div>
                        <dt>最近嘗試時間</dt>
                        <dd>{drawer.last_attempt.label}</dd>
                      </div>
                      <div>
                        <dt>最近成功時間</dt>
                        <dd>{drawer.last_success.label}</dd>
                      </div>
                      <div>
                        <dt>來源更新時間</dt>
                        <dd>{drawer.source_updated.label}</dd>
                      </div>
                    </dl>
                  </div>

                  {/* 欄位清單 (Fields / Schema) */}
                  <div className="source-health-drawer-section">
                    <h4 className="source-health-drawer-section-title">授權欄位與對應</h4>
                    {drawer.fields.length === 0 ? (
                      <p className="source-health-drawer-empty-fields">尚無授權欄位資訊</p>
                    ) : (
                      <div className="source-health-fields-scroll">
                        <table className="source-health-fields-table">
                          <thead>
                            <tr>
                              <th scope="col">欄位名稱</th>
                              <th scope="col">型別</th>
                              <th scope="col">欄位 ID</th>
                              <th scope="col">YX 對應</th>
                              <th scope="col">對應狀態</th>
                            </tr>
                          </thead>
                          <tbody>
                            {drawer.fields.map((field, idx) => (
                              <tr key={field.fieldId ?? `field-${idx}`}>
                                <td>{field.name ?? '未知'}</td>
                                <td>{field.type ?? '未知'}</td>
                                <td>
                                  <code>{field.fieldId ?? '未知'}</code>
                                </td>
                                <td>{field.yxMapping ?? '未知'}</td>
                                <td>{field.mappingLabel}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  {/* 重試按鈕 (Retry if exposed) */}
                  {drawer.retry !== null && (
                    <div className="source-health-drawer-section source-health-drawer-retry-section">
                      <button
                        type="button"
                        className="source-health-drawer-retry-btn"
                        onClick={() => onRetry?.(drawer.retry!.handle)}
                      >
                        重試此來源讀取
                      </button>
                    </div>
                  )}
                </div>
              </aside>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

export default SourceHealth;
