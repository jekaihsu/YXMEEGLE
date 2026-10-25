import {createPortal} from 'react-dom';
import {useId, useState} from 'react';
import {TriangleAlert} from 'lucide-react';
import {Badge, Button, Row, Section, Sheet} from './design';
import {formatPlanQuantity} from './caseDetailView';
import {canConfirmSop, canSeedTasks, sopActionLabel, sopWarningMessage, SEED_ACTION_LABEL, type PlanNode} from './startSop';
import type {useStartSop} from './useStartSop';
export function PlanLine({node, chipsOnly = false}: {node?: PlanNode; chipsOnly?: boolean}) {
 if (!node) return null;
 return <span className="sop-plan">{!chipsOnly && <span>計畫 {formatPlanQuantity(node.planned_qty)}・合約項 {node.lines}・工項 {node.items}</span>}<span className="sop-chips">{([['ambiguous','待確認'],['unlinked','未關聯']] as const).map(([key,label]) => node.items_basis[key] > 0 && <Badge key={key}>{label} {node.items_basis[key]}</Badge>)}</span></span>;
}
export function SopControls({sop}: {sop: ReturnType<typeof useStartSop>}) {
 const [mode, setMode] = useState<'nodes' | 'seed' | null>(null);
 const reasonId = useId();
 const {state, busy, notice} = sop;
 if (state.kind === 'hidden') return null;
 const preview = state.kind === 'ready' ? state.data : undefined;
 const seed = mode === 'seed';
 const reason = state.kind === 'forbidden' ? state.reason : preview?.can_start === false ? '僅案件 PM、主管或節點主管可以啟動' : preview?.blockers.map(b => b.message).join('、') || (!preview?.eligible && !preview?.already_started ? '目前不符合啟動條件。' : '');
 const actionLabel = preview ? sopActionLabel(preview) : '啟動 SOP';
 const close = () => {if (!busy) setMode(null)};
 return <div className="sop-controls">{preview?.already_started && <Badge>SOP 已啟動</Badge>}{actionLabel && <Button variant="primary" disabled={state.kind === 'forbidden'} aria-describedby={state.kind === 'forbidden' ? reasonId : undefined} onClick={() => setMode('nodes')}>{actionLabel}</Button>}{preview && canSeedTasks(preview) && <span className="sop-seed-option"><Button variant="plain" disabled={!canConfirmSop(preview, true)} onClick={() => setMode('seed')}>{SEED_ACTION_LABEL}</Button></span>}{state.kind === 'forbidden' && <span id={reasonId}>{reason}</span>}{notice && !mode && <p role="status">{notice}</p>}
 {mode && preview && createPortal(<Sheet title={seed ? '建立計畫任務預覽' : '啟動 SOP 預覽'} onClose={close}><div className="sop-preview"><div className="sop-preview-body">{notice && <p role="status">{notice}</p>}<Section title="建立內容">{preview.nodes.map(n => <Row key={n.key} label={n.label} detail={`計畫 ${formatPlanQuantity(n.planned_qty)} · ${n.deadline || '未排定'}`} value={[n.will_create_node && '建立節點', seed && n.will_create_task && '建立任務'].filter(Boolean).join('、') || '已存在'}/>)}</Section>{preview.warnings.map((w,i) => <p className="sop-warning" key={i}><TriangleAlert size={16} aria-hidden="true"/>{w.node && `${preview.nodes.find(n => n.key === w.node)?.label || w.node}：`}{sopWarningMessage(w)}</p>)}</div><footer><Button disabled={busy} onClick={close}>取消</Button><Button variant="primary" disabled={busy || !canConfirmSop(preview, seed)} aria-describedby={reason ? reasonId : undefined} onClick={() => {void sop.confirm(seed).then(done => {if (done) setMode(null)})}}>{busy ? '啟動中…' : seed ? '確認建立節點與計畫任務' : '確認啟動'}</Button>{reason && <p id={reasonId}>{reason}</p>}</footer></div></Sheet>,document.body)}
 </div>;
}
