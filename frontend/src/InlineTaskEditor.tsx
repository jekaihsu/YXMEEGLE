import {useState} from 'react';
import {Button} from './design';
import {draftChanged,type TaskDraft,type TaskEditorModel} from './nodeWorkbenchModel';
import './NodeWorkbench.css';

export function InlineTaskEditor({model,busy=false,onSave}:{model:TaskEditorModel;busy?:boolean;onSave:(draft:TaskDraft)=>Promise<boolean>}) {
 const [draft,setDraft]=useState(model.draft),[saving,setSaving]=useState(false),[message,setMessage]=useState('');
 const changed=draftChanged(model.draft,draft),dueChanged=draft.due!==model.draft.due;
 const blocked=busy || saving;
 const denied=(['title','assignee','due','notes','status'] as const).find(key=>draft[key]!==model.draft[key]&&!model.fields[key].enabled);
 const saveReason=denied?model.fields[denied].reason:!draft.title.trim() ? '請填寫任務名稱' : !changed ? '請先修改任務內容' : model.dueReason && dueChanged && !draft.reason.trim() ? '請填寫期限變更原因' : '';
 const update=(key:keyof TaskDraft,value:string)=>{setDraft(d=>({...d,[key]:value}));setMessage('')};
 const field=(key:keyof TaskEditorModel['fields'])=>({disabled:blocked || !model.fields[key].enabled,'aria-describedby':!model.fields[key].enabled ? `task-editor-${key}-reason` : undefined});
 const reason=(key:keyof TaskEditorModel['fields'])=>!model.fields[key].enabled && <small id={`task-editor-${key}-reason`}>{model.fields[key].reason}</small>;
 const submit=async()=>{if(blocked || saveReason)return;setSaving(true);setMessage('');try{const ok=await onSave(draft);setMessage(ok?'已儲存任務':'尚未儲存，請核對錯誤後重試')}finally{setSaving(false)}};
 return <form className="nw-task-editor" aria-label="編輯任務" onSubmit={e=>{e.preventDefault();void submit()}}>
  <label>任務名稱<input aria-label="任務名稱" value={draft.title} maxLength={model.maxTitle} required {...field('title')} onChange={e=>update('title',e.target.value)}/>{reason('title')}</label>
  <label>負責人<select aria-label="任務負責人" value={draft.assignee} {...field('assignee')} onChange={e=>update('assignee',e.target.value)}><option value="">未指派</option>{draft.assignee && !model.people.some(p=>p.id===draft.assignee) && <option value={draft.assignee}>目前負責人</option>}{model.people.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>{reason('assignee')}</label>
  <label>期限<input aria-label="任務期限" type="date" value={draft.due} {...field('due')} onChange={e=>update('due',e.target.value)}/>{reason('due')}</label>
  <label>任務狀態<select aria-label="任務狀態" value={draft.status} {...field('status')} onChange={e=>update('status',e.target.value)}>{model.statuses.map(s=><option key={s.id} value={s.id}>{s.label}</option>)}</select>{reason('status')}</label>
  <label className="nw-editor-wide">備註<textarea aria-label="任務備註" rows={4} value={draft.notes} maxLength={model.maxNotes} {...field('notes')} onChange={e=>update('notes',e.target.value)}/>{reason('notes')}</label>
  {model.dueReason && dueChanged && <label className="nw-editor-wide">期限變更原因<input aria-label="期限變更原因" value={draft.reason} maxLength={1000} required disabled={blocked} onChange={e=>update('reason',e.target.value)}/></label>}
  <div className="nw-editor-wide nw-editor-save"><Button type="submit" variant="primary" disabled={blocked || !!saveReason} disabledReason={blocked ? '正在儲存，請稍候' : saveReason}>{saving ? '儲存中…' : '儲存任務'}</Button>{message && <span role="status">{message}</span>}</div>
 </form>;
}
