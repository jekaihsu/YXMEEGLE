import {useId,useState,type FormEvent} from 'react';
import type {NodeAssignmentDetail,NodeAssignmentError,NewAssignmentTask} from './nodeAssignmentApi';
export function AssignForm({detail, busy, error, onCancel, onSubmit}: {detail: NodeAssignmentDetail; busy: boolean; error: NodeAssignmentError | null; onCancel: () => void; onSubmit: (ids: string[]) => Promise<void>}) {
  const [selected, setSelected] = useState(detail.node.owners.filter(p => detail.assignable_people.some(candidate => candidate.open_id === p.open_id)).map(p => p.open_id));
  const [validation, setValidation] = useState('');
  const submit = (event: FormEvent) => {event.preventDefault(); const ids = selected.filter(id => detail.assignable_people.some(p => p.open_id === id)); if (!ids.length || ids.length > 20) {setValidation('請選擇 1 至 20 位負責人。'); return} setValidation(''); void onSubmit(ids)};
  return <form className="na-form assignment-edit" onSubmit={submit}><fieldset disabled={busy}><legend>選擇節點負責人</legend><div className="na-person-options">{detail.assignable_people.map(p => <label key={p.open_id}><input type="checkbox" checked={selected.includes(p.open_id)} onChange={e => setSelected(ids => e.target.checked ? [...ids, p.open_id] : ids.filter(id => id !== p.open_id))}/><span>{p.name}<small>{p.departments.join('、')}</small></span></label>)}</div>
    {!detail.assignable_people.length && <p className="na-empty">目前沒有可指派人員，請聯絡管理員。</p>}{(validation || error?.fields.owner_open_ids) && <p className="na-field-error" role="alert">{validation || error?.fields.owner_open_ids}</p>}
    <div className="na-form-actions"><button type="button" className="button compact" onClick={onCancel}>取消</button><button className="button primary compact" type="submit" disabled={!detail.assignable_people.length}>儲存指派</button></div></fieldset></form>;
}
export function TaskCreator({detail, busy, error, onCancel, onSubmit}: {detail: NodeAssignmentDetail; busy: boolean; error: NodeAssignmentError | null; onCancel: () => void; onSubmit: (task: NewAssignmentTask) => Promise<void>}) {
  const [draft, setDraft] = useState<NewAssignmentTask>({title: '', detail: '', assignee_open_id: '', department: '', deadline: ''});
  const [validation, setValidation] = useState<Record<string, string>>({});
  const id = useId(), fields = {...error?.fields, ...validation};
  const departments = [...new Set(draft.assignee_open_id ? detail.assignable_people.find(p => p.open_id === draft.assignee_open_id)?.departments || [] : detail.node.departments)];
  const update = (field: keyof NewAssignmentTask, value: string) => {setDraft(d => ({...d, [field]: value, ...(field === 'assignee_open_id' ? {department: ''} : {})})); setValidation(v => {const next = {...v}; delete next[field]; return next})};
  const submit = (event: FormEvent) => {
    event.preventDefault(); const errors: Record<string, string> = {};
    if (!draft.title.trim()) errors.title = '請填寫任務名稱。';
    setValidation(errors); if (!Object.keys(errors).length) void onSubmit({...draft, title: draft.title.trim(), detail: draft.detail.trim()});
  };
  const invalid = (field: string) => ({'aria-invalid': !!fields[field], 'aria-describedby': fields[field] ? `${id}-${field}` : undefined});
  const fieldError = (field: string) => fields[field] && <small className="na-field-error" id={`${id}-${field}`} role="alert">{fields[field]}</small>;
  return <form className="na-form assignment-edit" noValidate onSubmit={submit}><fieldset disabled={busy}><legend>新增節點任務</legend><div className="na-form-grid">
    <label className="na-wide"><span>任務名稱 <small>必填</small></span><input value={draft.title} required {...invalid('title')} onChange={e => update('title', e.target.value)} placeholder="例如 控制點成果核對"/>{fieldError('title')}</label>
    <label className="na-wide"><span>任務說明</span><textarea value={draft.detail} {...invalid('detail')} onChange={e => update('detail', e.target.value)} rows={3} placeholder="補充作業範圍與交付內容"/>{fieldError('detail')}</label>
    {detail.assignable_people.length > 0 && <label><span>負責人 <small>{detail.can.assign ? '未選擇則建立未指派任務' : '未選擇則由自己負責'}</small></span><select value={draft.assignee_open_id} {...invalid('assignee_open_id')} onChange={e => update('assignee_open_id', e.target.value)}><option value="">選擇負責人</option>{detail.assignable_people.map(p => <option key={p.open_id} value={p.open_id}>{p.name}</option>)}</select>{fieldError('assignee_open_id')}</label>}
    <label><span>部門</span><select value={draft.department} {...invalid('department')} onChange={e => update('department', e.target.value)}><option value="">選擇部門</option>{departments.map(d => <option key={d} value={d}>{d}</option>)}</select>{fieldError('department')}</label>
    <label><span>期限 <small>僅日期</small></span><input type="date" value={draft.deadline} {...invalid('deadline')} onChange={e => update('deadline', e.target.value)}/>{fieldError('deadline')}</label>
  </div><div className="na-form-actions"><button type="button" className="button compact" onClick={onCancel}>取消</button><button type="submit" className="button primary compact">建立任務</button></div></fieldset></form>;
}
export function RejectForm({busy, error, onCancel, onSubmit}: {busy: boolean; error: NodeAssignmentError | null; onCancel: () => void; onSubmit: (reason: string) => Promise<void>}) {
  const [reason, setReason] = useState(''), [validation, setValidation] = useState('');
  const id = useId(), message = validation || error?.fields.reason;
  const submit = (event: FormEvent) => {event.preventDefault(); if (!reason.trim()) {setValidation('請填寫退回原因。'); return} setValidation(''); void onSubmit(reason.trim())};
  return <form className="na-form assignment-edit" noValidate onSubmit={submit}><fieldset disabled={busy}><legend>退回節點</legend><label><span>退回原因 <small>必填</small></span><textarea placeholder="說明本次調整的原因" rows={3} value={reason} required aria-invalid={!!message} aria-describedby={message ? id : undefined} onChange={e => {setReason(e.target.value); setValidation('')}}/></label>{message && <p id={id} className="na-field-error" role="alert">{message}</p>}
    <div className="na-form-actions"><button type="button" className="button compact" onClick={onCancel}>取消</button><button type="submit" className="button primary compact">確認退回</button></div></fieldset></form>;
}
