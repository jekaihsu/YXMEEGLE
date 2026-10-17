import {formatPlanQuantity} from './caseDetailView';
import type {AssignmentNode, NodeEvidence, WorkItem, WorkItemStatus} from './nodeAssignmentApi';

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
export const UNCERTAIN_LINK_LABEL = '關聯待確認';
export const UNNAMED_ITEM_LABEL = '未命名工項';
const CERTAIN_LINKS = new Set(['native', 'derived']);
// An item whose contract link is not certain is listed but carries no signal, whatever its points say.
export const itemStatusLabel = (item: Pick<WorkItem, 'status' | 'link_basis'>) =>
  item.link_basis && !CERTAIN_LINKS.has(item.link_basis) ? UNCERTAIN_LINK_LABEL : ITEM_STATUS_LABEL[item.status];
export const itemLabel = (item: Pick<WorkItem, 'code' | 'name'>) => item.code ?? item.name ?? UNNAMED_ITEM_LABEL;
export interface ProgressLine {
  known: boolean; percent: number | null; text: string; counts: string;
  // Some items have no signal: the percent covers only the known ones. `muted` when they are fewer than half, then the caveat leads.
  partial: boolean; muted: boolean; caveat: string | null; figure: string | null; fill: number | null;
}

// Progress is only known when some item has real progress; no signal is never shown as 0% and a partial view is never shown as the whole.
export function progressLine(e: Pick<NodeEvidence, 'progress'>): ProgressLine {
  const p = e.progress;
  if (!p) return {known: false, percent: null, text: NO_PROGRESS_TEXT, counts: '', partial: false, muted: false, caveat: null, figure: null, fill: null};
  const percent = p.percent === null ? null : Number(p.percent);
  const shown = percent === null ? null : String(Math.round(percent * 10) / 10);
  const unknown = p.unknown_items ?? 0, known = p.known_items ?? p.items_total - unknown;   // the project progress payload is not normalized on the way in
  const partial = unknown > 0;
  const caveat = partial ? `僅計有進度資料的 ${known} 項；其餘 ${unknown} 項尚無資料` : null;
  const counts = `已完成 ${p.items_done}/${p.items_total} 工項`;
  const figure = shown === null ? null : `完成 ${shown}%`;
  const text = shown === null ? (partial ? `${counts}（${caveat}）` : counts) : `${figure}（${caveat ?? counts}）`;
  // The bar shows how much of the whole is proven, so 99.9% of one known item out of 100 never looks nearly full.
  const fill = percent === null ? null : partial ? Math.round(percent * known / p.items_total * 10) / 10 : percent;
  return {known: true, percent, text, counts, partial, muted: partial && known * 2 < p.items_total, caveat, figure, fill};
}

export const itemsSummary = (e: NodeEvidence) => `工項明細（${e.items_total}）`;
export const itemsTruncatedNote = (e: NodeEvidence) => `僅顯示前 ${e.work_items.length} 筆，共 ${e.items_total} 筆`;
export const itemPoints = (remaining: string | null, planned: string | null) =>
  remaining !== null && planned !== null ? `剩餘 ${formatPlanQuantity(remaining)} / ${formatPlanQuantity(planned)} 點` : '';

export const LINK_BASIS_TEXT: Record<string, string> = {
  native: 'Lark 原生關聯（合約工項已連結此工項）',
  derived: '依工編推導的關聯，非 Lark 原生連結',
};
export const UNCERTAIN_LINK_TEXT = '關聯尚未確認，暫不計入進度，請到工程確認單核對。';
export const linkBasisText = (item: Pick<WorkItem, 'link_basis'>) => LINK_BASIS_TEXT[item.link_basis] ?? UNCERTAIN_LINK_TEXT;

export interface ItemProgress {earned: number; planned: number; remaining: number; percent: number}
// Only a pair of valid numbers with remaining not above plan counts; anything else is unknown, never 0.
export function itemProgress(item: Pick<WorkItem, 'planned_points' | 'remaining_points' | 'link_basis' | 'status'>): ItemProgress | null {
  if (item.status === 'no_signal' || (item.link_basis && !CERTAIN_LINKS.has(item.link_basis))) return null;
  if (item.planned_points === null || item.remaining_points === null) return null;
  const planned = Number(item.planned_points), remaining = Number(item.remaining_points);
  if (!Number.isFinite(planned) || !Number.isFinite(remaining) || planned <= 0 || remaining < 0 || remaining > planned) return null;
  const earned = planned - remaining;
  return {earned, planned, remaining, percent: Math.round(earned / planned * 1000) / 10};
}
export const itemsDoneCount = (e: Pick<NodeEvidence, 'progress'>) => e.progress ? `${e.progress.items_done}/${e.progress.items_total}` : null;
