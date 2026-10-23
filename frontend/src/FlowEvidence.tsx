import type {FlowNode} from './flowModel';
import {Button} from './design';
import {basisExplanations,basisLabels,workItemRows,workItemsTruncation} from './workItemsModel';
import {productionPlanGaps,type ProductionPlan} from './productionPlan';
import {caseReportTargets, type ReportTarget, progressValue as val} from './projectProgressView';
import type {ProductionKey, ProjectProgress as Data, ProgressReportRow} from './projectProgressApi';
import './WorkItemsTab.css';
import './reports/reports.css';
import './ProjectProgress.css';
const productionLabels: Record<ProductionKey,string> = {field:'外業',control:'控制',mapping:'圖資',report:'報告'};
export function ProductionPlanFacts({plan}:{plan:ProductionPlan}) {
 return <div className="pf-plan-facts"><dl><div><dt>來源計畫總量</dt><dd>{plan.quantity ?? '尚未提供'}</dd></div><div><dt>合約明細</dt><dd>{plan.lines===null ? '尚未提供' : `${plan.lines} 筆`}</dd></div><div><dt>工項</dt><dd>{plan.items===null ? '尚未提供' : `${plan.items} 項`}</dd></div></dl><div className="pf-plan-basis" aria-label="連結依據">{plan.basis.filter(b=>b.count>0).map(b=><span className="pf-basis-chip" key={b.key} title={basisExplanations[b.key]}>{basisLabels[b.key]} {b.count}</span>)}</div><p className="pf-plan-note">計畫數量依來源顯示，不同單位不加總。{plan.source==='task-detail' && '工程證據尚未載入，暫依建立任務時的計畫。'}</p></div>;
}
export function ProductionCard({node, category, data, plan, stale:sourceStale, onItems, onDetail, onReports}: {node:FlowNode; category: ProductionKey; data: Data; plan:ProductionPlan|null; stale:boolean; onItems:()=>void; onDetail: (row: ProgressReportRow) => void; onReports: (row?: ReportTarget) => void}) {
 const p = node.production;
 if(!p)return null;
 const planned = p.planned;
 const rows = data.production.report_rows.filter(r => r.dept === (category === 'field' ? 'field' : 'office'));
 const stale=sourceStale || /stale|error|unavailable|failed/i.test(data.sources.source_status || '') || data.sources.reports_stale===true || data.sources.reports_status!=='ok';
 const items=workItemRows(p,stale),truncation=workItemsTruncation(p);
 const standalone:ProductionPlan={source:'evidence',quantity:planned?.qty || null,lines:planned?.lines ?? null,items:planned?.items ?? null,basis:planned ? (['native','derived','ambiguous','unlinked'] as const).map(key=>({key,count:planned.basis[key]})) : []};
 return <section className="pf-production" aria-label={`${productionLabels[category]}生產計畫證據`}>
 {!plan && <h3>生產計畫</h3>}<ProductionPlanFacts plan={plan || standalone}/>{stale && <p className="pf-plan-note" role="status">來源或回報尚未核實，工項完成率暫不計算。請更新來源後核對。</p>}
 <div className="pf-items-heading"><h4>計畫工項</h4><a href={`#view=project&project=${encodeURIComponent(data.project_id)}&tab=items&node=${category}`} onClick={e=>{e.preventDefault();onItems()}}>在工項與進度查看完整表格 →</a></div>
 {items.length ? <div className="wi-table-wrap" role="region" aria-label="節點工項表格" tabIndex={0}><table className="wi-table pf-plan-table"><caption className="sr-only">{productionLabels[category]}計畫工項，實際完成量未核實</caption><thead><tr>{['工編','工項名稱','計畫量','實際完成量','進度','關聯依據'].map(label=><th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{items.map(item=><tr key={item.id} data-item-id={item.id}><td data-label="工編"><code>{item.code}</code></td><td data-label="工項名稱">{item.name}</td><td data-label="計畫量">{item.planned}</td><td data-label="實際完成量">{item.actualDisplay}</td><td data-label="進度">{item.progressDisplay}</td><td data-label="關聯依據"><span className="pf-basis-chip" title={basisExplanations[item.basis]}>{basisLabels[item.basis]}</span></td></tr>)}</tbody></table></div> : <p className="pf-plan-note">{planned===null ? '計畫工項來源尚未提供，筆數未知。' : '尚無可見工項，不代表確定未作業。'}</p>}
 {truncation && <p className="pf-plan-note">{truncation}</p>}
 {node.quantity.actual!==null && <p className="pf-plan-note">來源回報量 {node.quantity.actual} {node.quantity.unit} · {p.actual.source==='v4_daily' ? 'V4 日報' : 'v3 報表'}。此數值不代表各工項的已核實完成量。</p>}
 <ul className="pf-gap-list">{productionPlanGaps(node).map(gap=><li key={gap.key}><strong>{gap.title}</strong><span>{gap.why}</span><span>補齊方式 · {gap.fix}</span></li>)}</ul>
 <details className="pg-details"><summary>{category === 'field' ? '外業週報' : '內業週報（控制／圖資／報告共用）'}（{rows.length} 筆）</summary>{category !== 'field' && <p className="pg-muted">來源未按內業生產節點拆分，下列週報不代表本節點獨立實績。</p>}<p className="pg-muted">週報為工作預排與工作單資料，與上方日報回報量分開呈現。</p><p>工作單 {val(p.work_orders.count)} · 最新日期 {val(p.work_orders.latest_date)}</p><div className="pg-table"><table><thead><tr>{['週次／案件','預排','實際','狀態','達成率','明細'].map(t => <th key={t}>{t}</th>)}</tr></thead><tbody>{rows.map(r => <tr key={`${r.case_key}-${r.dept}-${r.week}`}><td data-label="週次／案件">{r.week}<small>{r.case_code} · {r.basis === 'points' ? '點數' : '天數'}</small></td><td data-label="預排">{val(r.planned)}</td><td data-label="實際">{val(r.actual)}</td><td data-label="狀態">{r.status}</td><td data-label="達成率">{r.achievement === null ? '來源未提供' : `${Math.round(r.achievement * 100)}%`}</td><td><Button onClick={() => onDetail(r)}>查看明細</Button><details><summary>週報數據</summary><p>預排 {val(r.planned_days)} 天 · 實際 {val(r.actual_days)} 天 · 對應 {val(r.matched_days)} 天</p><p>預期總量 {val(r.expected_total)} · 累計 {val(r.done_total)} · 剩餘 {val(r.remaining)}</p></details></td></tr>)}</tbody></table></div>{!rows.length && <p className="pg-muted">{data.sources.reports_status === 'cold' ? '報表資料載入中' : data.sources.reports_status !== 'ok' ? '報表資料暫不可用' : '尚無週報資料'}</p>}{data.production.report_rows_truncated && <p className="pg-warning">週報僅列出各部門最近 6 個有活動的週次。</p>}{data.identity.v3_cases.length ? caseReportTargets(data.identity.v3_cases, rows, category === 'field' ? 'field' : 'office').map(target => <Button key={target.case_code} variant="plain" onClick={() => onReports(target)}>前往報表 · {target.case_code}</Button>) : <Button variant="plain" onClick={() => onReports()}>前往報表查看此案</Button>}</details></section>;
}
