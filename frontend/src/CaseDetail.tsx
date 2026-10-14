import {compareTableValues} from './companyDashboardCache';
import {taipeiTime} from './taipeiTime';
import { useRef, useEffect, useId } from 'react';
import type {
  CaseDetailView,
  DetailRow,
  DisplayField,
  SectionView,
  SortSpec,
} from './caseDetailView.ts';
import './p2-case.css';

export interface CaseDetailNavTarget {
  route?: 'confirmation' | 'contract' | 'workitem';
  nativeKey?: string;
  view?: string;
  project?: string;
  tab?: string;
  section?: string;
  [k: string]: unknown;
}

export interface CaseDetailProps {
  view: CaseDetailView;
  onSelect?: (key: string | null) => void;
  onSort?: (sort: SortSpec | string) => void;
  onNavigate?: (target: CaseDetailNavTarget | string) => void;
  onBack?: () => void;
  onPage?: (page: number) => void;
  currentSort?: SortSpec;
}

function renderDisplayField(f: DisplayField) {
  if (f.text === '未核准顯示') {
    return (
      <span className="p2-cell-withheld" title={f.reason ?? undefined}>
        {['事件時間','取代時間'].includes(f.label)?taipeiTime(f.text,'未提供'):f.text}
      </span>
    );
  }
  if (f.text === '—') {
    return (
      <span className="p2-cell-unknown" title={f.reason ?? undefined}>
        {['事件時間','取代時間'].includes(f.label)?taipeiTime(f.text,'未提供'):f.text}
      </span>
    );
  }
  return <span className="p2-cell-text">{['事件時間','取代時間'].includes(f.label)?taipeiTime(f.text,'未提供'):f.text}</span>;
}

function getKindLabel(kind: string): string {
  switch (kind) {
    case 'case':
      return '案件';
    case 'confirmation':
      return '確認單';
    case 'contract':
      return '合約明細';
    case 'work_item':
      return '工項';
    case 'node':
      return '流程節點';
    case 'task':
      return '任務';
    case 'evidence':
      return '文件／報告';
    case 'unresolved_edge':
      return '未解析關聯';
    case 'history':
      return '歷程紀錄';
    default:
      return kind;
  }
}

function getIdentifierLabel(idKey: string): string {
  switch (idKey) {
    case 'case_identity':
      return '案件識別碼';
    case 'record_key':
      return '紀錄識別碼';
    case 'node_id':
      return '節點識別碼';
    case 'task_id':
      return '任務識別碼';
    case 'confirmation_key':
      return '確認單鍵';
    case 'event_id':
      return '事件識別碼';
    default:
      return idKey;
  }
}

export function CaseDetail({
  view,
  onSelect,
  onSort,
  onNavigate,
  onBack,
  currentSort,
}: CaseDetailProps) {
  const instanceId = useId();
  const sectionId = (key: string) => `${instanceId}-section-${key}`;
  const rootRef = useRef<HTMLDivElement>(null);
  const rowSelectButtonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const prevDrawerKeyRef = useRef<string | null>(view.drawer?.row.key ?? null);
  const pendingNavRef = useRef<string | null>(null);

  const restoreFocus = (targetKey: string | null) => {
    if (targetKey) {
      const btn = rowSelectButtonRefs.current.get(targetKey);
      if (btn && !btn.closest('[hidden]')) {
        btn.focus();
        return;
      }
    }
    const fallback = rootRef.current?.querySelector<HTMLElement>(
      'caption, h2, h1'
    );
    if (fallback) {
      if (!fallback.hasAttribute('tabindex')) {
        fallback.setAttribute('tabindex', '-1');
      }
      fallback.focus();
    }
  };

  useEffect(() => {
    const currentKey = view.drawer?.row.key ?? null;
    const prevKey = prevDrawerKeyRef.current;
    prevDrawerKeyRef.current = currentKey;

    if (prevKey !== null && currentKey === null) {
      restoreFocus(prevKey);
    }
  }, [view.drawer]);

  useEffect(() => {
    if (
      pendingNavRef.current &&
      view.drawer &&
      view.drawer.row.key === pendingNavRef.current
    ) {
      const nav = view.drawer.navigation;
      pendingNavRef.current = null;
      if (nav) {
        onNavigate?.(nav);
      }
    }
  }, [view.drawer, onNavigate]);

  const handleRowNavigate = (row: DetailRow) => {
    const isSelected = view.drawer?.row.key === row.key;
    if (isSelected && view.drawer?.navigation) {
      onNavigate?.(view.drawer.navigation);
    } else {
      pendingNavRef.current = row.key;
      onSelect?.(row.key);
    }
  };

  const setRowBtnRef = (key: string, el: HTMLButtonElement | null) => {
    if (el) {
      rowSelectButtonRefs.current.set(key, el);
    } else {
      rowSelectButtonRefs.current.delete(key);
    }
  };

  const handleSortClick = () => {
    const nextDir =
      currentSort?.key === 'title' && currentSort.dir === 'asc'
        ? 'desc'
        : 'asc';
    onSort?.({ key: 'title', dir: nextDir });
  };

  // Page-level non-ready / error view (header empty or blocked)
  if (view.header.length === 0) {
    return (
      <div className="p2-detail-root p2-case-root" ref={rootRef}>
        <section
          className={`p2-banner ${view.page.states.map(s => `state-${s}`).join(' ')}`}
          role="status"
          aria-live="polite"
          aria-label="案件與確認單明細資料狀態"
        >
          <div className="p2-banner-header">
            <span className="p2-banner-title">案件與確認單明細資料狀態</span>
            <span className="p2-badge" data-state={view.page.states[0]}>
              {view.page.label}
            </span>
          </div>
          {view.page.reason && (
            <p className="p2-banner-reason">{view.page.reason}</p>
          )}
        </section>
        {onBack && (
          <div>
            <button
              type="button"
              className="p2-btn p2-btn-plain"
              onClick={onBack}
              aria-label="返回確認單清單"
            >
              返回確認單清單
            </button>
          </div>
        )}
      </div>
    );
  }

  const renderRow = (row: DetailRow, sectionKey: string) => {
    const isSelected = view.drawer?.row.key === row.key;
    const isUnresolved = row.unresolved || row.kind === 'unresolved_edge';

    return (
      <tr
        key={row.key}
        className={`${isUnresolved ? 'p2-row-unresolved' : ''} ${
          isSelected ? 'is-selected' : ''
        }`}
      >
        <th scope="row">
          {renderDisplayField(row.title)}
          {isUnresolved && row.reason && (
            <span className="p2-reason-text"> ({row.reason})</span>
          )}
        </th>
        <td>
          <span className="p2-badge">{getKindLabel(row.kind)}</span>
        </td>
        <td>{renderDisplayField(row.status)}</td>
        <td>
          {isUnresolved ? (
            <span className="p2-unresolved-label">{row.relationship}</span>
          ) : (
            <span>{row.relationship}</span>
          )}
        </td>
        <td>
          {row.amount ? renderDisplayField(row.amount) : <span>—</span>}
        </td>
        <td>
          {row.fields.length > 0 ? (
            <div className="p2-row-fields">
              {row.fields.map((f, fIdx) => (
                <span
                  key={`${sectionKey}-f-${fIdx}-${f.label}`}
                  className="p2-field-tag"
                >
                  {f.label}: {renderDisplayField(f)}
                </span>
              ))}
            </div>
          ) : (
            <span>—</span>
          )}
        </td>
        <td>
          {row.sourceLink.url ? (
            <a
              href={row.sourceLink.url}
              target="_blank"
              rel="noreferrer"
              className="p2-cell-link"
            >
              {row.sourceLink.label}
            </a>
          ) : (
            <span
              className="p2-cell-unknown"
              title={row.sourceLink.reason ?? undefined}
            >
              {row.sourceLink.label}：—
            </span>
          )}
        </td>
        <td>
          <div className="p2-row-actions">
            <button
              type="button"
              ref={el => setRowBtnRef(row.key, el)}
              className="p2-btn p2-btn-sm p2-btn-select"
              aria-expanded={isSelected}
              onClick={() => {
                pendingNavRef.current = null;
                onSelect?.(isSelected ? null : row.key);
              }}
              aria-label={`${isSelected ? '收合' : '檢視'} ${row.title.text}`}
            >
              {isSelected ? '收合' : '詳情'}
            </button>
            {row.kind === 'contract' && (
              <button
                type="button"
                className="p2-btn p2-btn-sm p2-btn-primary"
                onClick={() => handleRowNavigate(row)}
                aria-label={`前往合約 ${row.title.text}`}
              >
                前往合約
              </button>
            )}
            {row.kind === 'work_item' && (
              <button
                type="button"
                className="p2-btn p2-btn-sm p2-btn-primary"
                onClick={() => handleRowNavigate(row)}
                aria-label={`前往工項 ${row.title.text}`}
              >
                前往工項
              </button>
            )}
          </div>
        </td>
      </tr>
    );
  };

  const renderSection = (section: SectionView) => {
    return (
      <section
        key={section.key}
        id={sectionId(section.key)}
        className="p2-card p2-section-card"
        aria-label={section.title}
      >
        <div className="p2-card-header">
          <div className="p2-card-header-left">
            <h2 className="p2-section-title">{section.title}</h2>
            <span className="p2-badge" data-state={section.states[0]}>
              {section.label}
            </span>
            {section.freshness && (
              <span className="p2-badge p2-badge-verification">
                {section.freshness}
              </span>
            )}
          </div>
          <div className="p2-section-meta">
            <span className="p2-meta-item">
              {section.sourceTime.label}：{renderDisplayField(section.sourceTime)}
            </span>
          </div>
        </div>

        {/* Failed or blocked section reason */}
        {section.reason && (
          <div className="p2-section-reason-block" role="status">
            <span className="p2-warning-icon" aria-hidden="true">
              ⚠️
            </span>
            <span className="p2-section-reason-text">
              狀態原因：{section.reason}
            </span>
          </div>
        )}

        {/* Section rows or state placeholder */}
        {section.rows.length === 0 ? (
          <div className="p2-section-empty">
            <p className="p2-empty-message">
              {section.label}
            </p>
          </div>
        ) : (
          <div
            className="p2-table-wrapper"
            tabIndex={0}
            role="region"
            aria-label={`${section.title}表格`}
          >
            <table className="p2-table">
              <caption className="p2-sr-only">{section.title}清單</caption>
              <thead>
                <tr>
                  <th
                    scope="col"
                    aria-sort={
                      currentSort?.key === 'title'
                        ? currentSort.dir === 'asc'
                          ? 'ascending'
                          : 'descending'
                        : 'none'
                    }
                    className="p2-th-sortable"
                  >
                    <button
                      type="button"
                      className="p2-sort-btn"
                      onClick={handleSortClick}
                      aria-label="依名稱排序"
                    >
                      <span>名稱</span>
                      <span className="p2-sort-icon" aria-hidden="true">
                        {currentSort?.key === 'title'
                          ? currentSort.dir === 'asc'
                            ? ' ↑'
                            : ' ↓'
                          : ' ↕'}
                      </span>
                    </button>
                  </th>
                  <th scope="col">種類</th>
                  <th scope="col">狀態</th>
                  <th scope="col">關聯</th>
                  <th scope="col">金額</th>
                  <th scope="col">明細資訊</th>
                  <th scope="col">來源連結</th>
                  <th scope="col">動作</th>
                </tr>
              </thead>
              <tbody>
                {section.rows.flatMap(row => {
                  const mainTr = renderRow(row, section.key);
                  if (row.children.length === 0) return [mainTr];

                  const childTrs = row.children.map(child => {
                    const isChildSelected = view.drawer?.row.key === child.key;
                    const isChildUnresolved =
                      child.unresolved || child.kind === 'unresolved_edge';

                    return (
                      <tr
                        key={child.key}
                        className={`p2-sub-row ${
                          isChildUnresolved ? 'p2-row-unresolved' : ''
                        } ${isChildSelected ? 'is-selected' : ''}`}
                      >
                        <th scope="row" style={{ paddingLeft: '32px' }}>
                          <span
                            className="p2-sub-indicator"
                            aria-hidden="true"
                          >
                            ↳{' '}
                          </span>
                          {renderDisplayField(child.title)}
                          {isChildUnresolved && child.reason && (
                            <span className="p2-reason-text">
                              {' '}
                              ({child.reason})
                            </span>
                          )}
                        </th>
                        <td>
                          <span className="p2-badge">
                            {getKindLabel(child.kind)}
                          </span>
                        </td>
                        <td>{renderDisplayField(child.status)}</td>
                        <td>
                          {isChildUnresolved ? (
                            <span className="p2-unresolved-label">
                              {child.relationship}
                            </span>
                          ) : (
                            <span>{child.relationship}</span>
                          )}
                        </td>
                        <td>
                          {child.amount ? (
                            renderDisplayField(child.amount)
                          ) : (
                            <span>—</span>
                          )}
                        </td>
                        <td>
                          {child.fields.length > 0 ? (
                            <div className="p2-row-fields">
                              {child.fields.map((f, fIdx) => (
                                <span
                                  key={`${child.key}-f-${fIdx}-${f.label}`}
                                  className="p2-field-tag"
                                >
                                  {f.label}: {renderDisplayField(f)}
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span>—</span>
                          )}
                        </td>
                        <td>
                          {child.sourceLink.url ? (
                            <a
                              href={child.sourceLink.url}
                              target="_blank"
                              rel="noreferrer"
                              className="p2-cell-link"
                            >
                              {child.sourceLink.label}
                            </a>
                          ) : (
                            <span
                              className="p2-cell-unknown"
                              title={child.sourceLink.reason ?? undefined}
                            >
                              {child.sourceLink.label}：—
                            </span>
                          )}
                        </td>
                        <td>
                          <div className="p2-row-actions">
                            <button
                              type="button"
                              ref={el => setRowBtnRef(child.key, el)}
                              className="p2-btn p2-btn-sm p2-btn-select"
                              aria-expanded={isChildSelected}
                              onClick={() =>
                                onSelect?.(isChildSelected ? null : child.key)
                              }
                              aria-label={`${
                                isChildSelected ? '收合' : '檢視'
                              } ${child.title.text}`}
                            >
                              {isChildSelected ? '收合' : '詳情'}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  });

                  return [mainTr, ...childTrs];
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    );
  };

  return (
    <div className="p2-detail-root p2-case-root" ref={rootRef}>
      {/* 頁面資料狀態橫幅 (Page State Banner) */}
      {view.page.states.length > 0 && (
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
          {view.page.reason && (
            <p className="p2-banner-reason">{view.page.reason}</p>
          )}
        </section>
      )}

      {/* 路徑導覽 (Breadcrumb) */}
      <nav className="p2-breadcrumb" aria-label="路徑導覽">
        <ol className="p2-breadcrumb-list">
          <li className="p2-breadcrumb-item">
            {onBack ? (
              <button
                type="button"
                className="p2-breadcrumb-link"
                onClick={onBack}
                aria-label="返回確認單清單"
              >
                確認單清單
              </button>
            ) : (
              <span className="p2-breadcrumb-text">確認單清單</span>
            )}
          </li>
          <li className="p2-breadcrumb-item">
            <span className="p2-breadcrumb-separator" aria-hidden="true">
              /
            </span>
            <span
              className="p2-breadcrumb-text p2-breadcrumb-current"
              aria-current="page"
            >
              案件與確認單明細
            </span>
          </li>
        </ol>
      </nav>

      {/* 標頭資訊 (Header Fields) */}
      <header className="p2-header" aria-label="案件與確認單標頭資訊">
        <div className="p2-header-title-row">
          <h1 className="p2-header-title">案件與確認單明細</h1>
          <span className="p2-badge p2-badge-source">{view.page.label}</span>
        </div>

        <div className="p2-header-meta">
          <span className="p2-meta-item">
            {view.sourceLink.url ? (
              <a
                href={view.sourceLink.url}
                target="_blank"
                rel="noreferrer"
                className="p2-cell-link"
                aria-label={view.sourceLink.label}
              >
                {view.sourceLink.label}
              </a>
            ) : (
              <span
                className="p2-cell-unknown"
                title={view.sourceLink.reason ?? undefined}
              >
                {view.sourceLink.label}：—
              </span>
            )}
          </span>
        </div>

        {/* Distinct labelled header fields: dates are never merged */}
        <dl className="p2-header-grid">
          {view.header.filter(f=>['專案','案件編號','確認單版本','PM','目前階段'].includes(f.label)).map((fieldItem, idx) => (
            <div
              key={`${instanceId}-hdr-${idx}-${fieldItem.label}`}
              className="p2-header-field-item"
            >
              <dt className="p2-header-label">{fieldItem.label}</dt>
              <dd className="p2-header-val">
                {renderDisplayField(fieldItem)}
              </dd>
            </div>
          ))}
        </dl>
        <details className="p2-card">
          <summary>阻礙、日期與來源說明</summary>
          <dl className="p2-header-grid">
            {view.header.filter(f=>!['專案','案件編號','確認單版本','PM','目前階段'].includes(f.label)).map((fieldItem,idx)=><div key={idx} className="p2-header-field-item"><dt className="p2-header-label">{fieldItem.label}</dt><dd className="p2-header-val">{renderDisplayField(fieldItem)}</dd></div>)}
          </dl>
        </details>
      </header>

      {/* 頁內導覽 (In-page Navigation) */}
      <nav className="p2-inpage-nav" aria-label="章節快速導覽">
        <span className="p2-inpage-nav-label">頁內導覽：</span>
        <ul className="p2-inpage-nav-list">
          {view.sections.map(section => (
            <li key={`nav-${section.key}`} className="p2-inpage-nav-item">
              <a
                href={`#${sectionId(section.key)}`}
                className="p2-inpage-nav-link"
                aria-label={`前往 ${section.title} 章節`}
              >
                {section.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      {/* 主體與側欄佈局 (Main Layout with Drawer and Side Column) */}
      <div className="p2-main-layout">
        <div className="p2-layout-with-drawer">
          <div className="p2-primary-column">
            {/* 案件關聯樹狀結構 (Related tree one level deep, expanding on selection) */}
            {view.tree.root && (
              <section
                className="p2-card p2-tree-section"
                aria-label="案件關聯樹狀結構"
              >
                <div className="p2-card-header">
                  <div className="p2-card-header-left">
                    <h2 className="p2-section-title">
                      案件關聯結構 (Related Tree)
                    </h2>
                    <span className="p2-badge">單層展開</span>
                  </div>
                </div>
                <p className="p2-tree-note">
                  點選項目以展開子關聯或於抽屜檢視原生識別資訊
                </p>

                <div className="p2-tree-root-container">
                  <div className="p2-tree-node-wrapper">
                    <button
                      type="button"
                      ref={el => setRowBtnRef(view.tree.root!.key, el)}
                      className={`p2-tree-node-btn p2-tree-root-btn ${
                        view.drawer?.row.key === view.tree.root.key
                          ? 'is-selected'
                          : ''
                      }`}
                      aria-expanded={view.tree.children.length > 0}
                      onClick={() => {
                        pendingNavRef.current = null;
                        const isSel =
                          view.drawer?.row.key === view.tree.root!.key;
                        onSelect?.(isSel ? null : view.tree.root!.key);
                      }}
                      aria-label={`案件根節點 ${view.tree.root.title.text}`}
                    >
                      <span className="p2-tree-icon" aria-hidden="true">
                        {view.tree.children.length > 0 ? '▼' : '▶'}
                      </span>
                      <span className="p2-badge p2-badge-root">案件</span>
                      <span className="p2-tree-label">
                        {renderDisplayField(view.tree.root.title)}
                      </span>
                      <span className="p2-badge p2-badge-verification">
                        {view.tree.root.relationship}
                      </span>
                    </button>
                  </div>

                  <ul className="p2-tree-level-1" role="list">
                    {view.tree.children.map(child => {
                      const isExpanded =
                        view.tree.expanded?.key === child.key;
                      const isSelected =
                        view.drawer?.row.key === child.key;
                      const subChildren = isExpanded
                        ? view.tree.expanded?.children ?? []
                        : [];

                      return (
                        <li key={child.key} className="p2-tree-item">
                          <div className="p2-tree-node-wrapper">
                            <button
                              type="button"
                              ref={el => setRowBtnRef(child.key, el)}
                              className={`p2-tree-node-btn ${
                                isExpanded ? 'is-expanded' : ''
                              } ${isSelected ? 'is-selected' : ''}`}
                              aria-expanded={isExpanded}
                              onClick={() => {
                                pendingNavRef.current = null;
                                onSelect?.(isSelected ? null : child.key);
                              }}
                              aria-label={`${
                                isExpanded ? '收合' : '展開'
                              } ${child.title.text}`}
                            >
                              <span
                                className="p2-tree-icon"
                                aria-hidden="true"
                              >
                                {isExpanded ? '▼' : '▶'}
                              </span>
                              <span className="p2-badge">
                                {getKindLabel(child.kind)}
                              </span>
                              <span className="p2-tree-label">
                                {renderDisplayField(child.title)}
                              </span>
                              {child.status.text !== '—' && (
                                <span className="p2-badge">
                                  {renderDisplayField(child.status)}
                                </span>
                              )}
                              {child.unresolved && (
                                <span className="p2-unresolved-label">
                                  {child.relationship}{' '}
                                  {child.reason ? `(${child.reason})` : ''}
                                </span>
                              )}
                            </button>
                          </div>

                          {isExpanded && subChildren.length > 0 && (
                            <ul className="p2-tree-level-2" role="list">
                              {subChildren.map(sub => {
                                const isSubSelected =
                                  view.drawer?.row.key === sub.key;
                                return (
                                  <li key={sub.key} className="p2-tree-item">
                                    <div className="p2-tree-node-wrapper">
                                      <button
                                        type="button"
                                        ref={el => setRowBtnRef(sub.key, el)}
                                        className={`p2-tree-node-btn p2-tree-sub-btn ${
                                          isSubSelected ? 'is-selected' : ''
                                        }`}
                                        onClick={() => {
                                          pendingNavRef.current = null;
                                          onSelect?.(
                                            isSubSelected ? null : sub.key
                                          );
                                        }}
                                        aria-label={`檢視 ${sub.title.text}`}
                                      >
                                        <span className="p2-badge">
                                          {getKindLabel(sub.kind)}
                                        </span>
                                        <span className="p2-tree-label">
                                          {renderDisplayField(sub.title)}
                                        </span>
                                        {sub.unresolved && (
                                          <span className="p2-unresolved-label">
                                            {sub.relationship}{' '}
                                            {sub.reason
                                              ? `(${sub.reason})`
                                              : ''}
                                          </span>
                                        )}
                                      </button>
                                    </div>
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                          {isExpanded && subChildren.length === 0 && (
                            <p className="p2-tree-empty-nested">無子層關聯</p>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </section>
            )}

            {/* 各章節資料 (Overview, Versions, Contract Lines, Work Items, Workflow Nodes, Reports, History) */}
            {view.sections.map(section => ['history','reports_documents'].includes(section.key)
              ? <details key={section.key} className="p2-card"><summary>{section.title}</summary>{renderSection(sortCaseSection(section,currentSort??null))}</details>
              : renderSection(sortCaseSection(section,currentSort??null)))}
          </div>

          {/* 原生識別抽屜 (Selection-only Drawer for Full IDs) */}
          {view.drawer && (
            <aside
              className="p2-drawer"
              role="region"
              aria-label="選取項目原生詳情抽屜"
            >
              <div className="p2-drawer-header">
                <h3 className="p2-drawer-title">原生識別與詳情</h3>
                <button
                  type="button"
                  className="p2-btn p2-btn-sm p2-btn-close"
                  onClick={() => {
                    const keyToRestore = view.drawer?.row.key ?? null;
                    pendingNavRef.current = null;
                    onSelect?.(null);
                    restoreFocus(keyToRestore);
                  }}
                  aria-label="關閉原生詳情抽屜"
                >
                  關閉
                </button>
              </div>

              <div className="p2-drawer-body">
                {/* 選取項目摘要 */}
                <div className="p2-drawer-section">
                  <h4 className="p2-drawer-section-title">選取項目</h4>
                  <dl className="p2-drawer-def">
                    <div>
                      <dt>名稱</dt>
                      <dd>{renderDisplayField(view.drawer.row.title)}</dd>
                    </div>
                    <div>
                      <dt>種類</dt>
                      <dd>
                        <span className="p2-badge">
                          {getKindLabel(view.drawer.row.kind)}
                        </span>
                      </dd>
                    </div>
                    <div>
                      <dt>狀態</dt>
                      <dd>{renderDisplayField(view.drawer.row.status)}</dd>
                    </div>
                    <div>
                      <dt>關聯狀態</dt>
                      <dd>{view.drawer.row.relationship}</dd>
                    </div>
                    {view.drawer.row.amount && (
                      <div>
                        <dt>{view.drawer.row.amount.label}</dt>
                        <dd>{renderDisplayField(view.drawer.row.amount)}</dd>
                      </div>
                    )}
                  </dl>
                </div>

                {/* 原生識別碼 (Technical IDs - exactly as provided) */}
                <div className="p2-drawer-section">
                  <h4 className="p2-drawer-section-title">原生識別碼</h4>
                  <dl className="p2-drawer-def">
                    {Object.entries(view.drawer.identifiers).map(
                      ([idKey, idVal]) => {
                        if (idVal === null) return null;
                        return (
                          <div key={idKey}>
                            <dt>{getIdentifierLabel(idKey)}</dt>
                            <dd>
                              <code>{idVal}</code>
                            </dd>
                          </div>
                        );
                      }
                    )}
                  </dl>
                </div>

                {/* 上層關聯 */}
                {view.drawer.parents.length > 0 && (
                  <div className="p2-drawer-section">
                    <h4 className="p2-drawer-section-title">上層關聯</h4>
                    <ul className="p2-drawer-parents-list">
                      {view.drawer.parents.map((parent, pIdx) => (
                        <li
                          key={`parent-${pIdx}`}
                          className="p2-drawer-parent-item"
                        >
                          <span className="p2-parent-label">{parent.label}</span>
                          <span className="p2-badge p2-badge-verification">
                            {parent.verification}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* 關聯數量統計 (Only when provided by view model) */}
                {view.drawer.relationshipCounts && (
                  <div className="p2-drawer-section">
                    <h4 className="p2-drawer-section-title">關聯數量統計</h4>
                    {view.drawer.countBasis && (
                      <p className="p2-count-basis">
                        {view.drawer.countBasis}
                      </p>
                    )}
                    <dl className="p2-drawer-def">
                      <div>
                        <dt>確認單數量</dt>
                        <dd>{view.drawer.relationshipCounts.confirmations}</dd>
                      </div>
                      <div>
                        <dt>合約明細數量</dt>
                        <dd>{view.drawer.relationshipCounts.contracts}</dd>
                      </div>
                      <div>
                        <dt>工項數量</dt>
                        <dd>{view.drawer.relationshipCounts.work_items}</dd>
                      </div>
                      <div>
                        <dt>任務數量</dt>
                        <dd>{view.drawer.relationshipCounts.tasks}</dd>
                      </div>
                    </dl>
                  </div>
                )}

                {/* 動作與導向按鈕 */}
                <div className="p2-drawer-section p2-drawer-actions">
                  {view.drawer.navigation && (
                    <button
                      type="button"
                      className="p2-btn p2-btn-primary"
                      onClick={() =>
                        onNavigate?.(view.drawer!.navigation!)
                      }
                    >
                      前往
                      {view.drawer.navigation.route === 'contract'
                        ? '合約明細'
                        : view.drawer.navigation.route === 'workitem'
                        ? '工項明細'
                        : '確認單'}
                    </button>
                  )}
                  {view.drawer.reportsDocuments && (
                    <button
                      type="button"
                      className="p2-btn p2-btn-secondary"
                      onClick={() =>
                        onNavigate?.(view.drawer!.reportsDocuments!)
                      }
                    >
                      查看報告與文件
                    </button>
                  )}
                  <button
                    type="button"
                    className="p2-btn p2-btn-plain"
                    onClick={() => onNavigate?.(view.drawer!.sourceHealth)}
                  >
                    查看來源健康 (Source Health)
                  </button>
                </div>
              </div>
            </aside>
          )}
        </div>

        {/* 側欄區域 (Side Area: completeness, missing-edge warnings, source times, responsibility, operations) */}
        <aside className="p2-side-column" aria-label="案件側欄資訊">
          {/* 關係完整性 */}
          <section className="p2-card p2-side-card" aria-label="關係完整性">
            <h3 className="p2-section-title">
              {view.side.relationshipCompleteness.label}
            </h3>
            <div className="p2-completeness-value">
              {renderDisplayField(view.side.relationshipCompleteness)}
            </div>
            {view.side.relationshipCompleteness.reason && (
              <p className="p2-completeness-reason">
                原因：{view.side.relationshipCompleteness.reason}
              </p>
            )}
          </section>

          {/* 關聯警示 (Missing-edge warnings) */}
          <section className="p2-card p2-side-card" aria-label="關聯警示">
            <div className="p2-card-header">
              <h3 className="p2-section-title">關聯警示</h3>
            </div>
            {view.side.warnings.length > 0 && (
              <ul className="p2-warnings-list">
                {view.side.warnings.map(w => (
                  <li key={w.key} className="p2-warning-item">
                    <span className="p2-warning-icon" aria-hidden="true">
                      ⚠️
                    </span>
                    <div className="p2-warning-details">
                      <span className="p2-warning-text">{w.relationship}</span>
                      {w.reason && (
                        <span className="p2-warning-reason">
                          （{w.reason}）
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* 章節同步時間與狀態 */}
          <section
            className="p2-card p2-side-card"
            aria-label="各章節來源同步時間"
          >
            <h3 className="p2-section-title">章節同步時間與狀態</h3>
            <ul className="p2-source-times-list">
              {view.side.sourceTimes.map((st, sIdx) => (
                <li
                  key={`${instanceId}-st-${sIdx}-${st.section}`}
                  className="p2-source-time-item"
                >
                  <div className="p2-st-header">
                    <span className="p2-st-name">{st.section}</span>
                    {st.freshness && (
                      <span className="p2-badge p2-badge-verification">
                        {st.freshness}
                      </span>
                    )}
                  </div>
                  <span className="p2-st-time">
                    {renderDisplayField(st.time)}
                  </span>
                </li>
              ))}
            </ul>
            {/* Source Health link callback */}
            <div className="p2-side-actions">
              <button
                type="button"
                className="p2-btn p2-btn-secondary p2-btn-sm"
                onClick={() => onNavigate?.({ view: 'sources' })}
                aria-label="查看來源健康狀態"
              >
                查看來源健康 (Source Health)
              </button>
            </div>
          </section>

          {/* 權責與操作 */}
          <section className="p2-card p2-side-card" aria-label="權責與操作">
            <h3 className="p2-section-title">權責與操作</h3>
            <dl className="p2-def-grid-sm">
              <div className="p2-def-item">
                <dt>{view.side.responsibility.label}</dt>
                <dd>{renderDisplayField(view.side.responsibility)}</dd>
              </div>
              <div className="p2-def-item">
                <dt>操作限制</dt>
                <dd>
                  <span className="p2-badge">{view.side.operations}</span>
                </dd>
              </div>
            </dl>
          </section>
        </aside>
      </div>
    </div>
  );
}

export function sortCaseSection(section: CaseDetailView['sections'][number], sort: SortSpec) {
 const field = (row: CaseDetailView['sections'][number]['rows'][number], label: string) => row.fields.find(f=>f.label===label)?.text;
 const rows=[...section.rows].sort((a,b)=>{
  if(sort?.key==='title') return compareTableValues(a.title.reason?null:a.title.text,b.title.reason?null:b.title.text,'text',sort.dir)||a.key.localeCompare(b.key);
  const label=section.key==='contract_lines'?'項次':section.key==='versions'?'修訂':section.key==='history'?'事件時間':null;
  if(!label)return 0;
  const left=field(a,label),right=field(b,label);
  const result=compareTableValues(left,right,section.key==='history'?'date':'number',section.key==='contract_lines'?'asc':'desc');
  return result||a.key.localeCompare(b.key);
 });
 return {...section,rows};
}
