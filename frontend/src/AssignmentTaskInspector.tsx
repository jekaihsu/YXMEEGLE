import {createPortal} from 'react-dom';
import {useState} from 'react';
import {Button,Sheet} from './design';
import {TASK_STATUS_OPTIONS,type AssignmentTask,type AssignmentMutation} from './nodeAssignmentApi';
import {FlowAction} from './FlowActions';
export function AssignmentTaskInspector({assignment:task,nodeLabel,nodeKey,busy,reason,mutate,onClose}:{assignment:AssignmentTask;nodeLabel:string;nodeKey:string;busy:boolean;reason:string;mutate:(m:AssignmentMutation)=>Promise<boolean>;onClose:()=>void}){
 const [failure,setFailure]=useState(false);
 const [status,setStatus]=useState(task.status);
 return createPortal(<Sheet title={task.title} onClose={onClose}><div className="pf-inspector assignment-edit"><p>{nodeLabel} · Lark 任務</p><dl className="pf-facts"><div><dt>負責人</dt><dd>{task.assignee?.name || '尚未指派'}</dd></div><div><dt>截止日</dt><dd>{task.deadline || '未排期限'}</dd></div><div><dt>指派人</dt><dd>{task.assigned_by?.name || '來源未提供'}</dd></div></dl><h3>任務說明</h3><p>{task.detail || '來源未提供'}</p><details><summary>來源與歷程</summary><p><span>來源狀態</span> {task.status}</p><p>來源 record ID {task.record_id}</p><p>建立時間 {task.created_at || '來源未提供'}</p><p>完成時間 {task.done_at || '來源未提供'}</p></details>
 <label>任務狀態<select aria-label="任務狀態" value={status} disabled={busy || !(task.can.edit_status || task.can.cancel)} onChange={e=>setStatus(e.target.value)}>{TASK_STATUS_OPTIONS.filter(([value])=>value===task.status || (value==='取消' ? task.can.cancel : task.can.edit_status)).map(([value,label])=><option key={value}>{label}</option>)}</select>{!(task.can.edit_status || task.can.cancel) && <small>需有任務處理權限。</small>}</label>
 <div className="pf-actions"><Button onClick={onClose}>關閉</Button><FlowAction allowed={!busy && status!==task.status && (status==='取消' ? task.can.cancel : task.can.edit_status)} reason={busy ? reason : status===task.status ? '請先選擇新的任務狀態。' : '需有此任務處理權限。'} onClick={()=>void mutate({action:'update_task',nodeKey,taskId:task.id,expected_revision:task.revision,patch:{status}}).then(ok=>setFailure(!ok))}>{busy ? '儲存中…' : '儲存狀態'}</FlowAction></div>{failure && <p role="alert">狀態尚未儲存，請查看頁面錯誤後重試。</p>}</div></Sheet>,document.body);
}
