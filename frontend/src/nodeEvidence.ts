import {formatPlanQuantity} from './caseDetailView';
import type {AssignmentNode, NodeEvidence} from './nodeAssignmentApi';

export const NO_DAILY_TEXT = '尚無日報連結（完成量未知）';
export const SUBMIT_HINT_TEXT = '資料顯示已達計畫量，可送審';
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
  return {known: false, plan, text: NO_DAILY_TEXT};
}

export const showsEvidence = (n: AssignmentNode) => isProductionNode(n.key) && !!n.evidence;
export const progressHref = (projectId: string) => `#view=project&project=${encodeURIComponent(projectId)}&tab=progress`;
