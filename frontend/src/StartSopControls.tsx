import {Badge} from './design';
import {formatPlanQuantity} from './caseDetailView';
import type {PlanNode} from './startSop';
import type {useStartSop} from './useStartSop';
export function PlanLine({node, chipsOnly = false}: {node?: PlanNode; chipsOnly?: boolean}) {
 if (!node) return null;
 return <span className="sop-plan">{!chipsOnly && <span>計畫 {formatPlanQuantity(node.planned_qty)}・合約項 {node.lines}・工項 {node.items}</span>}<span className="sop-chips">{([['ambiguous','待確認'],['unlinked','未關聯']] as const).map(([key,label]) => node.items_basis[key] > 0 && <Badge key={key}>{label} {node.items_basis[key]}</Badge>)}</span></span>;
}
export function SopControls({sop}: {sop: ReturnType<typeof useStartSop>}) {
 return sop.state.kind === 'ready' && sop.state.data.already_started ? <Badge>SOP 已啟動</Badge> : null;
}
