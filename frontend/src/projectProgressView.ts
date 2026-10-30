import type {AssignmentNode} from './nodeAssignmentApi';
import type {ProjectProgress, ProgressReportRow, ProgressStage} from './projectProgressApi';
export const progressValue = (value: string|number|null|undefined) => value === null || value === undefined || value === '' ? '來源未提供' : String(value);
export const stageLabels = {done: '已完成', active: '進行中', waiting: '待前置作業', unknown: '未知'};
export function joinProgressStages(stages: ProgressStage[], nodes: AssignmentNode[] = []) {
 return stages.map(stage => ({...stage, sop: nodes.find(node => node.key === (stage.key === 'billing' ? 'pricing' : stage.key))}));
}
export const linkLabels = {native: '原生關聯', derived: '依工編推導', ambiguous: '關聯待確認', unlinked: '未關聯'};
export const linkHints = {native: '來源已直接連結合約工項。', derived: '以工編對應合約工項，尚非來源直接連結。', ambiguous: '找到多筆可能的合約工項，需人工確認。', unlinked: '尚無法對應合約工項。'};
const hints: Record<string,string> = {
 no_confirmation: '請 PM／行政在 Lark 建立工程確認單並連結案件。', confirmation_status_conflict: '請 PM 核對確認單狀態與合約明細。', fill_items_unknown: '請確認填報工項表的來源同步權限。',
 plan_unavailable: '請確認合約明細與工項表同步完整且權限涵蓋相關資料。', plan_truncated: '請核對來源完整工項，清單超過顯示上限。', items_unlinked: '在 Lark 工項填入對應的合約工項。', items_ambiguous: '核對重複工編，指定唯一的合約工項關聯。', quotes_duplicated: '核對附掛報價，保留正確的案件關聯。',
 no_daily_linked: '在 Lark 日報填「所屬案件」與「合約工項」後，下次來源同步會連起來。', v3_ambiguous: '核對各 v3 案件的案號／報價單號，修正重複對應後重新同步。', v3_none: '核對 v3 案號與此案工編或報價單號。', v3_no_activity: '請在對應 v3 案件填寫工作預排或工作單。',
 reports_cold: '報表快照正在建立，稍後重新讀取。', reports_unavailable: '請管理員檢查報表來源連線後重試。', reports_restricted: '請有報表權限的 PM／主管查看，或向管理員申請權限。', reports_disabled: '請管理員確認報表功能設定。', reports_stale: '請管理員檢查報表同步，更新後再核對。', finance_restricted: '請有財務權限的人員查看。', finance_empty: '請在來源報價填寫請款、收款資料並等待同步。',
};
export function gapHint(id: string) {return hints[id] || '請核對來源欄位與案件關聯，修正後等待下次同步。'}

export type ReportTarget = {case_code: string; dept: string; week?: string};
export function caseReportTargets(cases: ProjectProgress['identity']['v3_cases'], rows: ProgressReportRow[], dept: 'field'|'office'): ReportTarget[] {
 return cases.map(c => ({case_code: c.case_code, dept, week: rows.find(r => r.case_key === c.case_key && r.dept === dept)?.week}));
}
