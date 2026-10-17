import {useEffect, useId, useState} from 'react';
import {TriangleAlert} from 'lucide-react';
import {Badge, Button, Row, Section, Sheet} from './design';
import {formatPlanQuantity} from './caseDetailView';
import {currentSopStep, SOP_STEPS, type PlanNode} from './startSop';
import type {NodeAssignmentList} from './nodeAssignmentApi';
import type {useStartSop} from './useStartSop';
export function PlanLine({node}: {node?: PlanNode}) {
 if (!node) return null;
 return <span className="sop-plan"><span>計畫 {formatPlanQuantity(node.planned_qty)}・合約項 {node.lines}・工項 {node.items}</span><span className="sop-chips">{([['ambiguous','待確認'],['unlinked','未關聯']] as const).map(([key,label]) => node.items_basis[key] > 0 && <Badge key={key}>{label} {node.items_basis[key]}</Badge>)}</span></span>;
}
export function SopControls({sop}: {sop: ReturnType<typeof useStartSop>}) {
 const [open, setOpen] = useState(false);
 const reasonId = useId();
 const {state, busy, notice} = sop;
 if (state.kind === 'hidden') return null;
 const preview = state.kind === 'ready' ? state.data : undefined;
 const reason = state.kind === 'forbidden' ? state.reason : preview?.can_start === false ? '僅案件 PM、主管或節點主管可以啟動' : preview?.blockers.map(b => b.message).join('、') || (!preview?.eligible && !preview?.already_started ? '目前不符合啟動條件。' : '');
 return <div className="sop-controls"><Button disabled={state.kind === 'forbidden'} aria-describedby={state.kind === 'forbidden' ? reasonId : undefined} onClick={() => setOpen(true)}>啟動 SOP</Button>{state.kind === 'forbidden' && <span id={reasonId}>{reason}</span>}{notice && !open && <p role="status">{notice}</p>}
 {open && preview && <Sheet title="啟動 SOP 預覽" onClose={() => {if (!busy) setOpen(false)}}><div className="sop-preview"><div className="sop-preview-body">{notice && <p role="status">{notice}</p>}<Section title="建立內容">{preview.nodes.map(n => <Row key={n.key} label={n.label} detail={`計畫 ${formatPlanQuantity(n.planned_qty)} · ${n.deadline || '未排定'}`} value={[n.will_create_node && '建立節點', n.will_create_task && '建立任務'].filter(Boolean).join('、') || '已存在'}/>)}</Section><p>{preview.chain_note}</p>{preview.warnings.map((w,i) => <p className="sop-warning" key={i}><TriangleAlert size={16} aria-hidden="true"/>{w.node && `${preview.nodes.find(n => n.key === w.node)?.label || w.node}：`}{w.message}</p>)}</div><footer><Button disabled={busy} onClick={() => setOpen(false)}>取消</Button><Button variant="primary" disabled={busy || !preview.can_start || preview.already_started || !preview.eligible || !!preview.blockers.length} aria-describedby={reason ? reasonId : undefined} onClick={() => {void sop.confirm().then(done => {if (done) setOpen(false)})}}>{busy ? '啟動中…' : preview.already_started ? '已啟動' : '確認啟動'}</Button>{reason && <p id={reasonId}>{reason}</p>}</footer></div></Sheet>}
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
 const hints = ['請 PM／行政建立來源確認單。','請 PM 或主管確認啟動預覽。', permissions.some(c => c.assign || c.claim) ? '開啟節點，指派或認領負責人。' : '請節點主管指派負責人。', '開啟任務，回報進度並上傳成果。', permissions.some(c => c.complete) ? '確認任務全數完成，再完成節點。' : '請主管完成節點並送審。', permissions.some(c => c.approve) ? '開啟待審核節點，核准或退回。' : '等待節點主管或副總以上核准。'];
 const toggle = () => {const next = !open; setOpen(next); try {localStorage.setItem(storageKey, next ? 'open' : 'closed')} catch {}};
 return <section className="sop-map glass--card" aria-label="使用地圖"><header><strong>使用地圖</strong><Button variant="plain" aria-label="使用說明" aria-expanded={open} aria-controls={id} onClick={toggle}>? 使用說明 {open ? '收合' : mobile ? '展開全部步驟' : '展開'}</Button></header>{(open || mobile) && <ol id={id}>{SOP_STEPS.map(([label,who,action], i) => (open || !mobile || i + 1 === step || i + 1 === Math.min(step + 1, 6)) && <li key={label} aria-current={step === i+1 ? 'step' : undefined}><strong>{['①','②','③','④','⑤','⑥'][i]} {label}</strong><small>{who}</small><span>{action}</span>{step === i+1 && <Badge tone="accent">你在這裡</Badge>}{i === 1 && step >= 4 && sop.state.kind === 'ready' && !sop.state.data.already_started && <small>尚未啟動 SOP 種子任務</small>}<small>下一步：{hints[i]}</small></li>)}</ol>}</section>;
}
