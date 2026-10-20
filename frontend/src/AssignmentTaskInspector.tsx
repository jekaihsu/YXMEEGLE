import {useState} from 'react';
import {Badge} from './design';
import {TASK_STATUS_OPTIONS,type AssignmentTask,type AssignmentMutation} from './nodeAssignmentApi';
import {FlowAction} from './FlowActions';
import {TaskDrawer,DrawerFacts} from './TaskDrawer';
export function AssignmentTaskInspector({assignment:task,nodeLabel,nodeKey,busy,reason,mutate,onClose}:{assignment:AssignmentTask;nodeLabel:string;nodeKey:string;busy:boolean;reason:string;mutate:(m:AssignmentMutation)=>Promise<boolean>;onClose:()=>void}){
 const [failure,setFailure]=useState(false);
 const [status,setStatus]=useState(task.status);
 const editable=task.can.edit_status || task.can.cancel;
 const footer=<div className="task-drawer-primary assignment-edit"><label className="sop-field">任務狀態<select aria-label="任務狀態" value={status} disabled={busy || !editable} onChange={e=>setStatus(e.target.value)}>{TASK_STATUS_OPTIONS.filter(([value])=>value===task.status || (value==='取消' ? task.can.cancel : task.can.edit_status)).map(([value,label])=><option key={value}>{label}</option>)}</select></label><FlowAction allowed={!busy && status!==task.status && (status==='取消' ? task.can.cancel : task.can.edit_status)} reason={busy ? reason : !editable ? '需任務處理權限' : '請選擇新狀態'} onClick={()=>void mutate({action:'update_task',nodeKey,taskId:task.id,expected_revision:task.revision,patch:{status}}).then(ok=>setFailure(!ok))}>{busy ? '儲存中…' : '儲存狀態'}</FlowAction></div>;
 return <TaskDrawer kind="lark" label={task.title} trail={[nodeLabel,'Lark 任務']} title={task.title} status={<Badge>{task.status}</Badge>} footer={footer} onClose={onClose}>
  {failure && <p role="alert">狀態尚未儲存</p>}
  <section className="task-drawer-section"><DrawerFacts facts={[{label:'負責人',value:task.assignee?.name || '尚未指派'},{label:'期限',value:task.deadline || '未排期限'},{label:'指派人',value:task.assigned_by?.name || '來源未提供'},{label:'完成時間',value:task.done_at || '未完成'}]}/></section>
  {task.detail && <section className="task-drawer-section"><h3>任務說明</h3><p>{task.detail}</p></section>}
  <details className="task-drawer-section sop-source"><summary>來源</summary><p>record {task.record_id}</p><p>建立 {task.created_at || '來源未提供'}</p></details>
 </TaskDrawer>;
}
