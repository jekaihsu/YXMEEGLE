import {useState} from 'react';
import {ArrowRight, ChevronRight} from 'lucide-react';
import {Row, Section, Sheet} from './design';
import {formatPlanQuantity} from './caseDetailView';
import type {AssignmentNode, WorkItem} from './nodeAssignmentApi';
import {SUBMIT_HINT_TEXT, SUBMIT_HINT_TITLE, evidenceLine, itemLabel, itemProgress, itemStatusLabel, itemsTruncatedNote, linkBasisText, progressHref, progressLine} from './nodeEvidence';

const points = (value: number) => formatPlanQuantity(String(Math.round(value * 100) / 100));
const qty = (item: WorkItem) => item.planned_qty === null ? '來源未提供' : formatPlanQuantity(item.planned_qty);
const title = (item: WorkItem) => item.code && item.name ? `${item.code} ${item.name}` : itemLabel(item);

function ItemBar({item, empty = '尚無進度資料'}: {item: WorkItem; empty?: string}) {
  const p = itemProgress(item);
  return p ? <span className="na-wi-bar"><span className="na-progress-bar" role="progressbar" aria-label="工項完成度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p.percent)}><span style={{width: `${p.percent}%`}}/></span><strong>{p.percent}%</strong></span>
    : <span className="na-muted">{empty}</span>;
}

function ItemSheet({item, node, projectId, onClose}: {item: WorkItem; node: AssignmentNode; projectId: string; onClose: () => void}) {
  const p = itemProgress(item);
  return <Sheet title={`工項明細 · ${title(item)}`} onClose={onClose}><div className="na-wi-sheet">
    <Section title="基本資料"><Row label="工項編號" value={item.code ?? '來源未提供'}/>
      <Row label="工項名稱" value={item.name ?? '來源未提供'}/>
      <Row label="所屬節點" value={node.label}/>
      <Row label="計畫數量" value={qty(item)}/></Section>
    <Section title="進度"><Row label="狀態" value={itemStatusLabel(item)}/>
      <Row label="完成度" value={<ItemBar item={item}/>}/>
      <Row label="營業額點數（計畫）" value={item.planned_points === null ? '來源未提供' : formatPlanQuantity(item.planned_points)}/>
      <Row label="已完成點數" value={p ? points(p.earned) : '尚無進度資料'}/>
      <Row label="剩餘點數" value={item.remaining_points === null ? '來源未提供' : formatPlanQuantity(item.remaining_points)}/></Section>
    <Section title="資料來源"><Row label="關聯依據" value={linkBasisText(item)}/></Section>
    <a className="na-evidence-link" href={progressHref(projectId)}>到工程進度看完整證據 <ArrowRight size={12} aria-hidden="true"/></a>
  </div></Sheet>;
}

export function NodeWorkItems({node, projectId}: {node: AssignmentNode; projectId: string}) {
  const evidence = node.evidence, [open, setOpen] = useState<number | null>(null);
  if (!evidence) return null;
  const line = evidenceLine(evidence), progress = progressLine(evidence), items = evidence.work_items;
  return <section className="na-wi" aria-label={`${node.label}工項明細`}>
    <div className="na-wi-heading"><h4>工項明細 <span>{evidence.items_total} 項</span></h4>{node.can_submit_hint && <strong className="na-evidence-hint" title={SUBMIT_HINT_TITLE}>{SUBMIT_HINT_TEXT}</strong>}</div>
    <p className="na-wi-summary">{[...(line.known ? [line.text] : [line.plan, !progress.known && line.text]), progress.known && progress.text].filter(Boolean).map((part, i) => i ? <span key={i}> · <strong>{part}</strong></span> : part)}</p>
    {items.length ? <ul className="na-wi-list">
      <li className="na-wi-head" aria-hidden="true"><span>工項</span><span>數量</span><span>營業額點數</span><span>完成度</span><span>狀態</span><span/></li>
      {items.map((item, i) => <li key={i}><button className="na-wi-row" aria-label={`查看工項 ${title(item)} 明細`} onClick={() => setOpen(i)}>
        <span className="na-wi-name">{item.code === null && item.name === null ? itemLabel(item) : <>{item.code && <code>{item.code}</code>}<span>{item.name}</span></>}</span>
        <span data-label="數量">{qty(item)}</span>
        <span data-label="營業額點數">{item.planned_points === null ? '—' : formatPlanQuantity(item.planned_points)}</span>
        <span data-label="完成度"><ItemBar item={item} empty="—"/></span>
        <span data-label="狀態"><span className={`na-item-status na-item-${item.status}`}>{itemStatusLabel(item)}</span></span>
        <ChevronRight size={16} className="na-wi-chevron" aria-hidden="true"/>
      </button></li>)}
    </ul> : <p className="na-empty">此節點尚無對應的合約工項。</p>}
    {evidence.items_truncated && <p className="na-muted">{itemsTruncatedNote(evidence)}</p>}
    {open !== null && items[open] && <ItemSheet item={items[open]} node={node} projectId={projectId} onClose={() => setOpen(null)}/>}
  </section>;
}
