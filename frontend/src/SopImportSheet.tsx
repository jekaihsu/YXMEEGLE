import {createPortal} from 'react-dom';
import {useEffect, useId} from 'react';
import {Badge, Button, Row, Section, Sheet, Skeleton} from './design';
import {SOP_NODES, SOP_NODE_KEYS, sopNodeLabel, type ImportPreview, type PreviewOutcome, type SopNodeKey} from './sopTaskApi';
import {groupOutcomes, needsDecision, selectable, STATE_LABEL} from './sopTaskModel';
import {defaultImportNodes, useSopImport} from './useSopTasks';

const STEPS = ['選擇版本', '選擇任務', '確認'] as const;
type Flow = ReturnType<typeof useSopImport>;

function Unresolved({counts}: {counts: ImportPreview['unresolved']}) {
 return <>{counts.dates > 0 && <Row label="期限待確認" value={counts.dates}/>}{counts.participants > 0 && <Row label="人員未指派" value={counts.participants}/>}{counts.applicability > 0 && <Row label="適用待確認" value={counts.applicability}/>}</>;
}

function Completion({o}: {o:PreviewOutcome}) {
 const c=o.completion;
 if(!c)return null;
 return <Section title={o.title}><Row label="狀態" value={STATE_LABEL[c.state]}/><Row label="完成人員" value={c.actorName||c.actorId||'未設定'}/><Row label="完成時間" value={c.at==null?'未設定':new Date(c.at*1000).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}/>{c.ruleId&&<Row label="完成依據" value={c.ruleId}/>}<Row label="依據編號" value={[c.factsHash,...c.evidenceRefs].filter(Boolean).join('、')||'未設定'}/></Section>;
}

function OutcomeRow({o, flow}: {o: PreviewOutcome; flow: Flow}) {
 const id = useId();
 const checked = flow.selected.has(o.source_row_key), blocked = flow.blockers[o.source_row_key];
 const decide = needsDecision(o, flow.defaults);
 const badges = <>{o.outcome === 'link_addition' && <Badge tone="accent">新增節點連結</Badge>}{o.existing_state && <Badge>{STATE_LABEL[o.existing_state]}</Badge>}{o.applicability === 'unresolved' && <Badge tone="warning">條件</Badge>}</>;
 return <li className="sop-outcome" data-row={o.source_row_key}>
  {selectable(o) ? <label><input type="checkbox" checked={checked} disabled={flow.busy} aria-describedby={blocked ? id : undefined} onChange={() => flow.toggle(o.source_row_key)}/><span>{o.title}</span>{badges}</label>
   : <span className="sop-outcome-fixed"><span>{o.title}</span>{badges}</span>}
  {checked && decide && <label className="sop-reason">適用原因<input value={flow.decisions[o.source_row_key] || ''} maxLength={1000} disabled={flow.busy} onChange={e => flow.decide(o.source_row_key, e.target.value)}/></label>}
  {blocked && <span id={id} className="sop-blocker" role="note">{blocked}</span>}
 </li>;
}

export function SopImportSheet({projectId, startNode, only, allowedNodes=SOP_NODE_KEYS, onApplied, onClose, onOpenImported}: {projectId: string; startNode: SopNodeKey; only?: SopNodeKey; allowedNodes?:readonly SopNodeKey[]; onApplied: () => Promise<void>; onClose: () => void; onOpenImported: () => void}) {
 const flow = useSopImport(projectId, onApplied);
 useEffect(() => {
  const initial=only ? [only] : allowedNodes.length < SOP_NODE_KEYS.length ? allowedNodes : defaultImportNodes(startNode);
  void flow.open(initial.filter(key=>allowedNodes.includes(key)));
 }, []);
 const {step, preview, status} = flow;
 const locked = status === 'applying' || status === 'confirming';
 const close = () => {if (!locked) onClose()};
 const index = step === 'receipt' ? 3 : ['version', 'select', 'confirm'].indexOf(step);
 const blockerCount = Object.keys(flow.blockers).length;
 const template = flow.templates?.find(t => t.version_id === flow.version);
 return createPortal(<Sheet title={only ? `匯入此節點任務 · ${sopNodeLabel(only)}` : '匯入預設任務'} onClose={close}>
  <div className="sop-import">
   <ol className="sop-steps">{STEPS.map((label, i) => <li key={label} aria-current={i === index ? 'step' : undefined} data-done={i < index}>{i + 1} {label}</li>)}</ol>
   {flow.error && <p role="alert" className="pg-callout">{flow.error}</p>}
   {step === 'version' && <>
    {flow.templates === null ? (status === 'loading' ? <Skeleton lines={2} height="2.75rem"/> : null)
     : flow.templates.length ? <fieldset className="sop-choices"><legend>範本版本</legend>{flow.templates.map(t => <label key={t.version_id}><input type="radio" name="sop-version" checked={flow.version === t.version_id} onChange={() => flow.setVersion(t.version_id)}/><span>{t.name}</span><span className="sop-muted">{t.revision}</span>{t.is_default && <Badge tone="accent">預設</Badge>}</label>)}</fieldset>
     : <p className="pf-empty">無已發布範本</p>}
    <Section><Row label="起始節點" value={`從 ${sopNodeLabel(only || flow.nodes[0] || startNode)} 開始`}/></Section>
    {!only && <fieldset className="sop-nodes"><legend>匯入節點</legend>{SOP_NODES.filter(([key])=>allowedNodes.includes(key)).map(([key, label]) => <Button key={key} aria-pressed={flow.nodes.includes(key)} disabled={flow.busy} onClick={() => flow.toggleNode(key)}>{label}</Button>)}</fieldset>}
    <div className="sop-sheet-actions"><Button onClick={close}>取消</Button><Button variant="primary" disabled={!flow.version || !flow.nodes.length || flow.busy} disabledReason={!flow.version ? '請選擇範本版本' : !flow.nodes.length ? '請選擇節點' : '讀取中'} onClick={() => void flow.loadDefault()}>{status === 'loading' && flow.templates ? '產生預覽中…' : '下一步'}</Button></div>
   </>}
   {step === 'select' && preview && (() => {
    const {groups, references} = groupOutcomes(preview);
    return <>
     <p className="sop-summary">{template?.name} {preview.template.revision} · 已選 {flow.selected.size} 項{references > 0 && <span className="sop-muted"> · 參考列 {references}</span>}</p>
     {groups.map(g => <fieldset key={g.key} className="sop-group"><legend>{g.label} <span className="sop-muted">{g.rows.length}</span></legend><ul>{g.rows.map(o => <OutcomeRow key={o.source_row_key} o={o} flow={flow}/>)}</ul></fieldset>)}
     <div className="sop-sheet-actions"><Button onClick={flow.back} disabled={flow.busy}>上一步</Button><Button variant="primary" disabled={!!blockerCount || !flow.selected.size || flow.busy} disabledReason={blockerCount ? `${blockerCount} 項需處理` : !flow.selected.size ? '未選擇任務' : '產生預覽中'} onClick={() => void flow.toConfirm()}>下一步</Button></div>
    </>;
   })()}
   {step === 'confirm' && preview && <>
    <Section title="匯入內容">
     <Row label="範本版本" value={`${template?.name || ''} ${preview.template.revision}`}/>
     <Row label="節點" value={preview.nodeKeys.map(sopNodeLabel).join('、')}/>
     <Row label="新增任務" value={preview.counts.new_tasks}/>
     <Row label="既有任務" value={preview.counts.existing_tasks}/>
     <Row label="新增節點連結" value={preview.counts.added_links}/>
     <Unresolved counts={preview.unresolved}/>
    </Section>
    {preview.outcomes.filter(o=>o.selected&&o.outcome==='link_addition'&&o.completion).map(o=><Completion key={o.source_row_key} o={o}/>)}
    {status === 'confirming' && <p role="status" className="sop-status">正在確認匯入結果</p>}
    {status === 'applying' && <p role="status" className="sop-status">匯入中…</p>}
    <div className="sop-sheet-actions">
     <Button onClick={flow.back} disabled={flow.busy}>上一步</Button>
     {status === 'unknown' ? <Button variant="primary" onClick={() => void flow.recover()}>重新確認匯入結果</Button>
      : <Button variant="primary" disabled={flow.busy || !(preview.counts.new_tasks + preview.counts.added_links)} disabledReason={flow.busy ? '處理中' : '沒有需要匯入的項目'} onClick={() => void flow.apply()}>{flow.hasAttempt() ? '重試匯入' : '確認匯入'}</Button>}
    </div>
   </>}
   {step === 'receipt' && flow.receipt && <>
    <Section title="匯入結果">
     <Row label="已建立" value={flow.receipt.created.length}/>
     <Row label="已存在" value={flow.receipt.existing.length}/>
     <Row label="新增節點連結" value={flow.receipt.links}/>
     <Unresolved counts={flow.receipt.unresolved}/>
    </Section>
    <div className="sop-sheet-actions"><Button onClick={onClose}>關閉</Button><Button variant="primary" onClick={onOpenImported}>開啟匯入任務</Button></div>
   </>}
  </div>
 </Sheet>, document.body);
}
