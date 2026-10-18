import {createPortal} from 'react-dom';
import {useEffect, useId, useState} from 'react';
import {TriangleAlert} from 'lucide-react';
import {Badge, Button, Row, Section, Sheet} from './design';
import {formatPlanQuantity} from './caseDetailView';
import {canConfirmSop, canSeedTasks, sopActionLabel, currentSopStep, sopWarningMessage, SEED_ACTION_LABEL, SEED_EXPLANATION, SOP_STEPS, type PlanNode} from './startSop';
import type {NodeAssignmentList} from './nodeAssignmentApi';
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
 return <div className="sop-controls">{preview?.already_started && <Badge>SOP 已啟動</Badge>}{actionLabel && <Button disabled={state.kind === 'forbidden'} aria-describedby={state.kind === 'forbidden' ? reasonId : undefined} onClick={() => setMode('nodes')}>{actionLabel}</Button>}{preview && canSeedTasks(preview) && <span className="sop-seed-option"><Button variant="plain" disabled={!canConfirmSop(preview, true)} onClick={() => setMode('seed')}>{SEED_ACTION_LABEL}</Button><small>{SEED_EXPLANATION}</small></span>}{state.kind === 'forbidden' && <span id={reasonId}>{reason}</span>}{notice && !mode && <p role="status">{notice}</p>}
 {mode && preview && createPortal(<Sheet title={seed ? '建立計畫任務預覽' : '啟動 SOP 預覽'} onClose={close}><div className="sop-preview"><div className="sop-preview-body">{seed && <p>{SEED_EXPLANATION}會同時補建缺少的節點，並為每個節點建立一筆計畫任務。</p>}{notice && <p role="status">{notice}</p>}<Section title="建立內容">{preview.nodes.map(n => <Row key={n.key} label={n.label} detail={`計畫 ${formatPlanQuantity(n.planned_qty)} · ${n.deadline || '未排定'}`} value={[n.will_create_node && '建立節點', seed && n.will_create_task && '建立任務'].filter(Boolean).join('、') || '已存在'}/>)}</Section><p>{preview.chain_note}</p>{preview.warnings.map((w,i) => <p className="sop-warning" key={i}><TriangleAlert size={16} aria-hidden="true"/>{w.node && `${preview.nodes.find(n => n.key === w.node)?.label || w.node}：`}{sopWarningMessage(w)}</p>)}</div><footer><Button disabled={busy} onClick={close}>取消</Button><Button variant="primary" disabled={busy || !canConfirmSop(preview, seed)} aria-describedby={reason ? reasonId : undefined} onClick={() => {void sop.confirm(seed).then(done => {if (done) setMode(null)})}}>{busy ? '啟動中…' : seed ? '確認建立節點與計畫任務' : '確認啟動'}</Button>{reason && <p id={reasonId}>{reason}</p>}</footer></div></Sheet>,document.body)}
 </div>;
}
export function UsageMap({data, sop}: {data: NodeAssignmentList; sop: ReturnType<typeof useStartSop>}) {
 const [mobile, setMobile] = useState(() => window.matchMedia?.('(max-width: 640px)').matches || false);
 const storageKey = mobile ? 'yx-flow-usage-mobile' : 'yx-flow-usage';
 const readOpen = () => {try {return localStorage.getItem(storageKey) === 'open' || (!mobile && localStorage.getItem(storageKey) !== 'closed')} catch {return !mobile}};
 const [open, setOpen] = useState(readOpen);
 useEffect(() => {
  const query = window.matchMedia?.('(max-width: 640px)');
  const change = () => setMobile(query?.matches || false);
  query?.addEventListener('change', change);
  return () => query?.removeEventListener('change', change);
 }, []);
 useEffect(() => {setOpen(readOpen())}, [storageKey]);
 const id = useId(), step = currentSopStep(data, sop.state.kind === 'ready' ? sop.state.data : undefined);
 const permissions = data.writes_enabled ? Object.values(data.can) : [];
 const hints = ['請 PM／行政建立來源確認單。','請 PM 或主管確認啟動預覽。', permissions.some(c => c.assign || c.claim) ? '開啟節點，指派或認領負責人。' : '請節點主管指派負責人。', '查看案件資料帶入的進度；需要指派具體工作時再建立任務。', permissions.some(c => c.complete) ? '確認任務全數完成，再完成節點。' : '請主管完成節點並送審。', permissions.some(c => c.approve) ? '開啟待審核節點，核准或退回。' : '等待節點主管或副總以上核准。'];
 const toggle = () => {const next = !open; setOpen(next); try {localStorage.setItem(storageKey, next ? 'open' : 'closed')} catch {}};
 return <section className="sop-map glass--card" aria-label="使用地圖"><header><strong>使用地圖</strong><Button variant="plain" aria-label="使用說明" aria-expanded={open} aria-controls={id} onClick={toggle}>? 使用說明 {open ? '收合' : mobile ? '展開全部步驟' : '展開'}</Button></header>{(open || mobile) && <ol id={id}>{SOP_STEPS.map(([label,who,action], i) => (open || !mobile || i + 1 === step || i + 1 === Math.min(step + 1, 6)) && <li key={label} aria-current={step === i+1 ? 'step' : undefined}><strong>{['①','②','③','④','⑤','⑥'][i]} {label}</strong><small>{who}</small><span>{action}</span>{step === i+1 && <Badge tone="accent">你在這裡</Badge>}{i === 1 && step >= 4 && sop.state.kind === 'ready' && !sop.state.data.already_started && <small>尚未啟動 SOP</small>}<small>下一步：{hints[i]}</small></li>)}</ol>}</section>;
}
