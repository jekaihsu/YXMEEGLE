import type {SopSignals} from './sopTaskApi';
import type {SopWorkItem} from './SopWorkSummary';
import {PRODUCTION_NODE_KEYS} from './nodeAssignmentApi';
import {api} from './api';
import type {ItemsProgress, WorkItemStatus} from './nodeAssignmentApi';
export const STAGE_KEYS = ['sales','pm','confirmation','field','control','mapping','report','billing','settlement'] as const;
export type StageKey = typeof STAGE_KEYS[number];
export type ProductionKey = typeof PRODUCTION_NODE_KEYS[number];
export type LinkBasis = 'native'|'derived'|'ambiguous'|'unlinked';
export interface ProgressStage {key: StageKey; label: string; state: 'done'|'active'|'waiting'|'unknown'; basis: 'rule'|'source'|'none'; evidence: {label: string; value: string; tone: 'ok'|'warn'|'muted'}[]}
export interface ProductionStage {
 planned: {lines: number; items: number; qty: string; basis: Record<LinkBasis, number>; needs_review: number}|null;
 items: {item_id: string; code: string|null; name: string|null; planned_qty: string|null; planned_points?: string|null; remaining_points?: string|null; status?: WorkItemStatus; link_basis: LinkBasis}[];
 progress?: ItemsProgress|null;
 items_total: number; items_truncated: boolean;
 actual: {known: boolean; value: string|null; unit_note: string|null; reason: string|null; source: 'v4_daily'|'v3_reports'|null};
 work_orders: {count: number|null; latest_date: string|null};
}
export interface ProgressReportRow {case_key: string; case_code: string; dept: 'field'|'office'; week: string; basis: string; planned: number; actual: number; planned_days: number; actual_days: number; matched_days: number; achievement: number|null; expected_total: number|null; done_total: number|null; remaining: number|null; status: string}
export interface ProjectProgress {
 sop_signals?:SopSignals;sop_items?:SopWorkItem[];
 schema_version: 1; project_id: string; as_of: string|null;
 sources: {source_synced_at: string|null; source_status: string|null; reports_status: 'ok'|'cold'|'unavailable'|'restricted'|'disabled'; reports_fetched_at: string|null; reports_stale: boolean|null};
 identity: {code: string|null; is_c_prefix: boolean; confirmation: {present: boolean; line_count: number; fill_item_count: number|null; source_status: string|null}; quotes: {number: string|null; engineering_code: string|null; status: string|null}[]; v3_cases: {case_key: string; case_code: string; status: string; match: 'code'|'quote_number'}[]; v3_ambiguous: boolean};
 stages: ProgressStage[];
 production: Record<ProductionKey, ProductionStage> & {report_rows: ProgressReportRow[]; report_rows_truncated: boolean};
 finance: {restricted: boolean; quotes: {number: string|null; invoiced_total: string|null; billable_unrequested: string|null; billable_total: string|null; received_total: string|null; received_date: string|null; case_received: boolean|null}[]; case_received: boolean|null; received_date: string|null};
 gaps: {id: string; severity: 'info'|'warn'; message_zh: string}[];
}
type Check = (v: unknown) => boolean;
const str: Check = v => typeof v === 'string';
const bool: Check = v => typeof v === 'boolean';
const number: Check = v => typeof v === 'number' && Number.isFinite(v);
const count: Check = v => number(v) && Number.isSafeInteger(v) && Number(v) >= 0;
const nullable = (check: Check): Check => v => v === null || check(v);
const list = (check: Check): Check => v => Array.isArray(v) && v.every(check);
const one = (...values: unknown[]): Check => v => values.includes(v);
const shape = (fields: Record<string, Check>): Check => v => !!v && typeof v === 'object' && !Array.isArray(v) && Object.entries(fields).every(([key, check]) => check((v as Record<string, unknown>)[key]));
const ns = nullable(str), nn = nullable(number), nc = nullable(count), nb = nullable(bool);
const basis = one('native','derived','ambiguous','unlinked');
const production = shape({planned: nullable(shape({lines: count, items: count, qty: str, basis: shape({native: count, derived: count, ambiguous: count, unlinked: count}), needs_review: count})), items: list(shape({item_id: str, code: ns, name: ns, planned_qty: ns, link_basis: basis})), items_total: count, items_truncated: bool, actual: shape({known: bool, value: ns, unit_note: ns, reason: ns, source: nullable(one('v4_daily','v3_reports'))}), work_orders: shape({count: nc, latest_date: ns})});
const schema = shape({schema_version: one(1), project_id: str, as_of: ns,
 sources: shape({source_synced_at: ns, source_status: ns, reports_status: one('ok','cold','unavailable','restricted','disabled'), reports_fetched_at: ns, reports_stale: nb}),
 identity: shape({code: ns, is_c_prefix: bool, confirmation: shape({present: bool, line_count: count, fill_item_count: nc, source_status: ns}), quotes: list(shape({number: ns, engineering_code: ns, status: ns})), v3_cases: list(shape({case_key: str, case_code: str, status: str, match: one('code','quote_number')})), v3_ambiguous: bool}),
 stages: list(shape({key: one(...STAGE_KEYS), label: str, state: one('done','active','waiting','unknown'), basis: one('rule','source','none'), evidence: list(shape({label: str, value: str, tone: one('ok','warn','muted')}))})),
 production: shape({field: production, control: production, mapping: production, report: production, report_rows: list(shape({case_key: str, case_code: str, dept: one('field','office'), week: str, basis: str, planned: number, actual: number, planned_days: count, actual_days: count, matched_days: count, achievement: nn, expected_total: nn, done_total: nn, remaining: nn, status: str})), report_rows_truncated: bool}),
 finance: shape({restricted: bool, quotes: list(shape({number: ns, invoiced_total: ns, billable_unrequested: ns, billable_total: ns, received_total: ns, received_date: ns, case_received: nb})), case_received: nb, received_date: ns}), gaps: list(shape({id: str, severity: one('info','warn'), message_zh: str})),
});
export function parseProjectProgress(value: unknown): ProjectProgress {
 const fail = () => {throw new Error('工程進度資料格式不正確，請稍後重試。')};
 if (!schema(value)) return fail();
 const data = value as ProjectProgress;
 if (data.stages.length !== STAGE_KEYS.length || data.stages.some((s,i) => s.key !== STAGE_KEYS[i])) return fail();
 for (const key of PRODUCTION_NODE_KEYS) if (data.production[key].actual.known && data.production[key].actual.value === null) return fail();
 return data;
}
export async function fetchProjectProgress(id: string, current: () => boolean) {
 const data = parseProjectProgress(await api<unknown>(`/api/projects/${encodeURIComponent(id)}/progress`, {cache: 'no-store'}, current));
 if (data.project_id !== id) throw new Error('工程進度案件不符，請重新讀取。');
 return data;
}
