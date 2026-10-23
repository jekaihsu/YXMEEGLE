import {useState} from 'react';
import {createPortal} from 'react-dom';
import {Button,Sheet} from './design';
import {sopApi,sopErrorText,type SopAssignee,type SopTask} from './sopTaskApi';
export type BulkAction='assign'|'due'|'start';
const LABELS={assign:'指派',due:'設期限',start:'標記進行中'};
export function bulkEligible(task:SopTask,action:BulkAction) {return task.allowedActions.includes(action==='start'?'start':'edit')}
export function SopBulkActions({projectId,tasks,action,assignees,current,reload,onClose}:{projectId:string;tasks:SopTask[];action:BulkAction;assignees:SopAssignee[];current:()=>boolean;reload:()=>Promise<void>;onClose:()=>void}) {
 const [person,setPerson]=useState(''),[date,setDate]=useState(''),[reason,setReason]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [done,setDone]=useState<string[]>([]);
 const eligible=tasks.filter(t=>bulkEligible(t,action)&&!done.includes(t.id));
 const skipped=tasks.filter(t=>!bulkEligible(t,action)&&!done.includes(t.id));
 const valid=action==='start'||action==='assign'||!!date&&!!reason.trim();
 const submit=async()=>{if(busy||!valid||!eligible.length)return;setBusy(true);setError('');try{for(const t of eligible){if(!current())return;if(action==='start')await sopApi.transition(projectId,t.id,{expected_revision:t.revision,action:'start'},current);else await sopApi.patch(projectId,t.id,{expected_revision:t.revision,...(action==='assign'?{participants:Object.fromEntries(Object.entries({...t.participants,executor:person||undefined}).filter(([,value])=>value))}:{due_date:date,reason:reason.trim()})},current);if(current())setDone(old=>[...old,t.id])}await reload();if(current())onClose()}catch(e){if(current()){setError(sopErrorText(e));await reload()}}finally{if(current()){setBusy(false)}}};
 return createPortal(<Sheet title={LABELS[action]} onClose={()=>{if(!busy)onClose()}}><form className="sop-form sop-import" onSubmit={e=>{e.preventDefault();void submit()}}><details className="sop-batch-details"><summary>批次範圍 · {eligible.length} 項待更新{skipped.length>0&&` · 略過 ${skipped.length} 項`}{done.length>0&&` · 已更新 ${done.length} 項`}</summary><ul className="sop-batch-list">{tasks.map(t=><li key={t.id}>{t.title} · {done.includes(t.id)?'已更新':bulkEligible(t,action)?'待更新':'不可操作'}</li>)}</ul></details>{action==='assign'&&<label>執行人員<select value={person} disabled={busy} onChange={e=>setPerson(e.target.value)}><option value="">未指派</option>{assignees.map(u=><option key={u.id} value={u.id}>{u.name}</option>)}</select></label>}{action==='due'&&<><label>期限<input type="date" required value={date} disabled={busy} onChange={e=>setDate(e.target.value)}/></label><label>期限原因<input required value={reason} disabled={busy} maxLength={1000} onChange={e=>setReason(e.target.value)}/></label></>}{error&&<p role="alert">{error}</p>}<div className="sop-sheet-actions"><Button disabled={busy} onClick={onClose}>取消</Button><Button type="submit" variant="primary" disabled={busy||!valid||!eligible.length}>確認{LABELS[action]}</Button></div></form></Sheet>,document.body);
}
