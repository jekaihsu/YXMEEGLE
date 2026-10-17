import {assignmentRequest, type NodeAssignmentList, nodeStatusLabel} from './nodeAssignmentApi';
export const PRODUCTION = {field: '外業', control: '控制', mapping: '圖資', report: '報告'} as const;
export type ProductionKey = keyof typeof PRODUCTION;
export interface PlanNode {key: ProductionKey; label: string; category: string; planned_qty: string; lines: number; items: number; items_basis: Record<'native'|'derived'|'ambiguous'|'unlinked', number>; deadline: string|null; node_exists: boolean; seed_task_exists: boolean; will_create_node: boolean; will_create_task: boolean; task_title: string; task_detail: string}
interface Issue {code: string; message: string; node?: ProductionKey|null}
export interface SopPreview {project_id: string; code: string|null; eligible: boolean; already_started: boolean; blockers: Issue[]; warnings: Issue[]; nodes: PlanNode[]; chain_note: string; preview_hash: string; plan_rule_version: string}
export interface SopResult {started: boolean; complete: boolean; results: {key: ProductionKey; node: 'created'|'existing'|'failed'; task: 'created'|'existing'|'failed'|'skipped'; error: string|null}[]; overview: unknown}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown) => typeof v === 'string';
const nullable = (v: unknown) => v === null || str(v);
const count = (v: unknown) => Number.isSafeInteger(v) && Number(v) >= 0;
const key = (v: unknown): v is ProductionKey => str(v) && Object.hasOwn(PRODUCTION, v as string);
function issue(v: unknown): boolean {return object(v) && str(v.code) && str(v.message) && (v.node === undefined || v.node === null || key(v.node))}
export function parseSopPreview(v: unknown): SopPreview {
 const fail = () => {throw new Error('啟動預覽格式不正確。')};
 if (!object(v) || !str(v.project_id) || !nullable(v.code) || typeof v.eligible !== 'boolean' || typeof v.already_started !== 'boolean' || !str(v.chain_note) || !str(v.preview_hash) || !str(v.plan_rule_version) || !Array.isArray(v.blockers) || !v.blockers.every(issue) || !Array.isArray(v.warnings) || !v.warnings.every(issue) || !Array.isArray(v.nodes)) return fail();
 for (const n of v.nodes) {
  if (!object(n) || !key(n.key) || !['label','category','task_title','task_detail'].every(k => str(n[k])) || !str(n.planned_qty) || !/^\d+(?:\.\d+)?$/.test(n.planned_qty as string) || (n.planned_qty as string).length > 100 || !count(n.lines) || !count(n.items) || !nullable(n.deadline) || !object(n.items_basis) || !['native','derived','ambiguous','unlinked'].every(k => count((n.items_basis as Record<string, unknown>)[k])) || !['node_exists','seed_task_exists','will_create_node','will_create_task'].every(k => typeof n[k] === 'boolean')) return fail();
 }
 if (new Set(v.nodes.map(n => n.key)).size !== v.nodes.length) return fail();
 return v as unknown as SopPreview;
}
export function parseSopResult(v: unknown): SopResult {
 if (!object(v) || typeof v.started !== 'boolean' || typeof v.complete !== 'boolean' || !object(v.overview) || !Array.isArray(v.results) || !v.results.every(r => object(r) && key(r.key) && ['created','existing','failed'].includes(String(r.node)) && ['created','existing','failed','skipped'].includes(String(r.task)) && nullable(r.error))) throw new Error('啟動結果格式不正確，請重新讀取。');
 return v as unknown as SopResult;
}
export const sopPath = (id: string) => `/api/projects/${encodeURIComponent(id)}/node-assignments/start-sop`;
export async function fetchSop(id: string, current: () => boolean) {return parseSopPreview(await assignmentRequest(sopPath(id), {cache: 'no-store'}, current))}
export const SOP_STEPS = [
 ['確認單建立','PM／行政','在來源 Lark 建立確認單'],
 ['啟動 SOP','PM 或主管','按下「啟動 SOP」預覽並確認'],
 ['指派負責人','節點主管','在節點上指派或認領'],
 ['執行與回報','負責人','完成任務並上傳成果'],
 ['送審','主管','全部任務完成後完成節點'],
 ['核准','節點主管或副總以上','核准；退回會回到進行中'],
] as const;
export function currentSopStep(data: NodeAssignmentList, preview?: SopPreview): number {
 if (!(preview ? preview.code : data.code)) return 1;
 if (preview?.eligible && !preview.already_started) return 2;
 const nodes = data.nodes.filter(n => Object.hasOwn(PRODUCTION, n.key));
 if ((preview?.already_started || nodes.some(n => n.record_id)) && nodes.some(n => !n.owners.length)) return 3;
 if (nodes.some(n => nodeStatusLabel(n.derived_status) === '進行中')) return 4;
 if (nodes.some(n => nodeStatusLabel(n.derived_status) === '待審核')) return 5;
 if (nodes.length && nodes.every(n => ['已完成','略過'].includes(nodeStatusLabel(n.derived_status)))) return 6;
 return 4;
}
