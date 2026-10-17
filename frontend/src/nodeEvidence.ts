import {formatPlanQuantity} from './caseDetailView';
import type {AssignmentNode, NodeEvidence, WorkItemStatus} from './nodeAssignmentApi';

export const NO_PROGRESS_TEXT = '尚無進度資料（日報未連結或尚未開工）';
export const SUBMIT_HINT_TEXT = '可送審';
export const SUBMIT_HINT_TITLE = '所有工項依來源的營業額點數皆已完成，可送審';
export const DRIVES_STATUS_TEXT = '依案件資料判定';
export const OPTIONAL_TASKS_LABEL = '任務（選用）';
const PRODUCTION_NODES = new Set(['field', 'control', 'mapping', 'report']);
export const isProductionNode = (key: string) => PRODUCTION_NODES.has(key);

const shortDate = (value: string) => value.length >= 10 ? `${value.slice(5, 7)}/${value.slice(8, 10)}` : value;

export interface EvidenceLine {text: string; known: boolean; plan: string}

// What a production card says about its source evidence. Unknown stays unknown: never a 0 or a percentage.
export function evidenceLine(e: NodeEvidence): EvidenceLine {
  const plan = e.planned_qty ? `計畫 ${formatPlanQuantity(e.planned_qty)}` : '';
  if (e.work_orders > 0) {
    return {known: true, plan, text: [plan, `日報 ${e.work_orders} 筆`, e.latest_date ? `最近 ${shortDate(e.latest_date)}` : ''].filter(Boolean).join(' · ')};
  }
  if (e.actual_source === 'v3_reports') return {known: true, plan, text: [plan, '週報登記冊已有外業進度'].filter(Boolean).join(' · ')};
  return {known: false, plan, text: NO_PROGRESS_TEXT};
}

export const showsEvidence = (n: AssignmentNode) => isProductionNode(n.key) && !!n.evidence;
export const progressHref = (projectId: string) => `#view=project&project=${encodeURIComponent(projectId)}&tab=progress`;

export const ITEM_STATUS_LABEL: Record<WorkItemStatus, string> = {done: '已完成', partial: '進行中', no_signal: '尚無進度資料'};
export interface ProgressLine {known: boolean; percent: number | null; text: string}

// Progress is only known when some item has real progress; no signal is never shown as 0%.
export function progressLine(e: Pick<NodeEvidence, 'progress'>): ProgressLine {
  const p = e.progress;
  if (!p) return {known: false, percent: null, text: NO_PROGRESS_TEXT};
  const percent = p.percent === null ? null : Number(p.percent);
  const shown = percent === null ? null : String(Math.round(percent * 10) / 10);
  const counts = `已完成 ${p.items_done}/${p.items_total} 工項`;
  return {known: true, percent, text: shown === null ? counts : `完成 ${shown}%（${counts}）`};
}

export const itemsSummary = (e: NodeEvidence) => `工項明細（${e.items_total}）`;
export const itemsTruncatedNote = (e: NodeEvidence) => `僅顯示前 ${e.work_items.length} 筆，共 ${e.items_total} 筆`;
export const itemPoints = (remaining: string | null, planned: string | null) =>
  remaining !== null && planned !== null ? `剩餘 ${formatPlanQuantity(remaining)} / ${formatPlanQuantity(planned)} 點` : '';
