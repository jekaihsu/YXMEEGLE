import {useId,useState,type ReactNode} from 'react';
import {Button,DisabledAction,DisabledActionReasons} from './design';
import {AssignForm,TaskCreator,RejectForm} from './NodeAssignmentForms';
import type {AssignmentMutation,NodeAssignmentDetail,NodeAssignmentError} from './nodeAssignmentApi';
export function HelpTip({label,text}:{label:string;text:string}){
 const [open,setOpen]=useState(false);const id=useId();
 return <span className="help-tip"><button type="button" className="help-tip-btn" aria-label={`${label}說明`} aria-expanded={open} aria-describedby={id} onClick={()=>setOpen(o=>!o)} onBlur={()=>setOpen(false)} onKeyDown={e=>{if(e.key==='Escape')setOpen(false)}}>?</button><span role="tooltip" id={id} className="help-tip-pop">{text}</span></span>;
}
export function FlowAction({allowed,reason,children,onClick,help}:{allowed:boolean;reason:string;children:ReactNode;onClick:()=>void;help?:string}){
 const button=<DisabledAction disabled={!allowed} reason={reason}>{id=><button className="button compact" type="button" disabled={!allowed} title={allowed?undefined:reason} aria-describedby={id} onClick={onClick}>{children}</button>}</DisabledAction>;
 return help ? <span className="pf-action">{button}<HelpTip label={String(children)} text={help}/></span> : button;
}
const ACTION_HELP={claim:'把自己設為此節點的負責人，由你開始處理本節點。',assign:'從可指派人員中選出本節點的負責人，可選多位。',create_task:'在本節點下建立具體工作，可指定負責人、部門與期限。',complete:'回報本節點的工作已完成，送交主管確認成果。',approve:'主管確認成果無誤後核准，節點即正式完成。',reject:'成果不符時退回，需填寫原因，節點回到處理中。'} as const;
export function FlowNodeActions({detail,busy,error,reason,mutate,extra}:{detail:NodeAssignmentDetail;busy:boolean;error:NodeAssignmentError|null;reason:string;mutate:(m:AssignmentMutation)=>Promise<boolean>;extra?:ReactNode}){
 const [form,setForm]=useState<'assign'|'task'|'reject'|''>('');
 const save=async(m:AssignmentMutation)=>{if(await mutate(m))setForm('')};
 const action=(name:'claim'|'assign'|'create_task'|'complete'|'approve'|'reject',label:string)=> <FlowAction allowed={!busy && detail.can[name]===true} reason={busy ? reason : '需有此節點操作權限，且節點狀態允許。'} help={ACTION_HELP[name]} onClick={()=>name==='assign' ? setForm('assign') : name==='create_task' ? setForm('task') : name==='reject' ? setForm('reject') : void save({action:name,nodeKey:detail.node.key,expected_revision:detail.node.revision})}>{label}</FlowAction>;
 const blocked=(['claim','assign','create_task','complete','approve','reject'] as const).some(n=>detail.can[n]!==true);
 return <DisabledActionReasons.Provider value={false}><div className="pf-node-actions"><div className="pf-actions">{action('claim','認領節點')}{action('assign','指派負責人')}{action('create_task','新增任務')}{action('complete','完成節點')}{action('approve','核准')}{action('reject','退回')}{extra}</div>{blocked && <p className="pf-actions-hint">灰色按鈕需有此節點操作權限，且節點狀態允許。</p>}
  {form==='assign' && <AssignForm detail={detail} busy={busy} error={error} onCancel={()=>setForm('')} onSubmit={ids=>save({action:'assign',nodeKey:detail.node.key,owner_open_ids:ids,expected_revision:detail.node.revision})}/>}
  {form==='task' && <TaskCreator detail={detail} busy={busy} error={error} onCancel={()=>setForm('')} onSubmit={task=>save({action:'create_task',nodeKey:detail.node.key,task})}/>}
  {form==='reject' && <RejectForm busy={busy} error={error} onCancel={()=>setForm('')} onSubmit={reason=>save({action:'reject',nodeKey:detail.node.key,reason,expected_revision:detail.node.revision})}/>}
 </div></DisabledActionReasons.Provider>;
}
export function TaskPersonPicker({detail,taskId,busy,error,mutate,onClose}:{detail:NodeAssignmentDetail;taskId:string;busy:boolean;error:NodeAssignmentError|null;mutate:(m:AssignmentMutation)=>Promise<boolean>;onClose:()=>void}){
 const task=detail.tasks.find(t=>t.id===taskId);
 const [person,setPerson]=useState(task?.assignee?.open_id || '');
 const [department,setDepartment]=useState(detail.node.departments[0] || '');
 const people=detail.assignable_people.filter(p=>!department || p.departments.includes(department));
 const valid=people.some(p=>p.open_id===person);
 if(!task)return null;
 return <form className="pf-task-picker assignment-edit" aria-label={`指派 ${task.title}`} onSubmit={event=>{event.preventDefault();if(!busy && task.can.assign && valid)void mutate({action:'update_task',nodeKey:detail.node.key,taskId:task.id,expected_revision:task.revision,patch:{assignee_open_id:person}}).then(ok=>{if(ok)onClose()})}}>
  <p>指派既有任務 · {task.title}</p><small>僅列出來源已核實的此組在職人員。</small>
  <label>組別<select value={department} onChange={e=>{setDepartment(e.target.value);setPerson('')}} disabled={busy}>{detail.node.departments.map(d=><option key={d}>{d}</option>)}</select></label>
  <label>負責人<select aria-label="任務負責人" value={person} onChange={e=>setPerson(e.target.value)} disabled={busy}><option value="">選擇負責人</option>{people.map(p=><option key={p.open_id} value={p.open_id}>{p.name}</option>)}</select></label>
  {!people.length && <p>目前沒有可指派的在職人員，請核對名冊與組別。</p>}
  {error && <p role="alert">{error.fields.assignee_open_id || error.message}</p>}
  <div className="pf-actions"><Button disabled={busy} onClick={onClose}>取消</Button><Button type="submit" variant="primary" disabled={busy || !valid || !task.can.assign} disabledReason={busy ? '正在儲存，請稍候。' : !task.can.assign ? '需有此任務指派權限。' : '請選擇此組在職人員。'}>{busy ? '儲存中…' : '儲存指派'}</Button></div>
 </form>;
}
