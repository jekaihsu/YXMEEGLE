import {useEffect,useId,useRef,useState,type ReactNode} from 'react';
import {CircleHelp} from 'lucide-react';
import {Button,DisabledAction,DisabledActionReasons} from './design';
import {AssignForm,TaskCreator,RejectForm,LegacyCompleteForm} from './NodeAssignmentForms';
import type {AssignmentMutation,NodeAssignmentDetail,NodeAssignmentError} from './nodeAssignmentApi';
export function HelpTip({label,text}:{label:string;text:string}){
 const [open,setOpen]=useState(false);const id=useId();const ref=useRef<HTMLSpanElement>(null);
 useEffect(()=>{if(!open)return;const away=(e:PointerEvent)=>{if(!ref.current?.contains(e.target as Node))setOpen(false)};document.addEventListener('pointerdown',away);return()=>document.removeEventListener('pointerdown',away)},[open]);
 return <span ref={ref} className="help-tip"><button type="button" className="help-tip-btn" aria-label={`${label}說明`} aria-expanded={open} aria-describedby={id} onClick={()=>setOpen(o=>!o)} onKeyDown={e=>{if(e.key==='Escape')setOpen(false)}}><CircleHelp size={16} aria-hidden="true"/></button><span role="tooltip" id={id} className="help-tip-pop">{text}</span></span>;
}
export function FlowAction({allowed,reason,children,onClick,help,primary}:{allowed:boolean;reason:string;children:ReactNode;onClick:()=>void;help?:string;primary?:boolean}){
 const button=<DisabledAction disabled={!allowed} reason={reason}>{id=><button className={primary?'button primary compact':'button compact'} type="button" disabled={!allowed} title={allowed?undefined:reason} aria-describedby={id} onClick={onClick}>{children}</button>}</DisabledAction>;
 return help ? <span className="pf-action">{button}<HelpTip label={String(children)} text={help}/></span> : button;
}
type ActionName='claim'|'assign'|'create_task'|'complete'|'approve'|'reject';
const ACTIONS:Record<ActionName,{label:string;help:string;confirm?:string}>={
 approve:{label:'核准',help:'主管確認成果無誤後核准，節點即正式完成。',confirm:'確定核准？核准後節點即正式完成。'},
 claim:{label:'認領節點',help:'把自己設為此節點的負責人，由你開始處理本節點。'},
 complete:{label:'完成節點',help:'回報本節點的工作已完成，送交主管確認成果。',confirm:'確定本節點工作已完成，並送交主管確認？'},
 assign:{label:'指派負責人',help:'從可指派人員中選出本節點的負責人，可選多位。'},
 create_task:{label:'新增任務',help:'在本節點下建立具體工作，可指定負責人、部門與期限。'},
 reject:{label:'退回',help:'成果不符時退回，需填寫原因，節點回到處理中。'}};
const ORDER=Object.keys(ACTIONS) as ActionName[];
const LEAD:ActionName[]=['approve','claim','complete','assign'];
const REOPEN={label:'取消完成',help:'節點已完成但需要重做時使用，填寫原因後節點回到處理中；已完成的任務不會被改動。'};
export function FlowNodeActions({detail,busy,error,reason,mutate,extra}:{detail:NodeAssignmentDetail;busy:boolean;error:NodeAssignmentError|null;reason:string;mutate:(m:AssignmentMutation)=>Promise<boolean>;extra?:ReactNode}){
 const [form,setForm]=useState<'assign'|'task'|'reject'|'legacy_complete'|''>('');
 const [confirm,setConfirm]=useState<ActionName|''>('');
 const save=async(m:AssignmentMutation)=>{if(await mutate(m))setForm('')};
 const allowed=ORDER.filter(n=>detail.can[n]===true);
 const done=detail.node.derived_status==='已完成';
 const legacyAllowed=detail.can.legacy_complete===true && !['已完成','略過'].includes(detail.node.derived_status);
 const label=(n:ActionName)=>n==='reject'&&done?REOPEN.label:ACTIONS[n].label,help=(n:ActionName)=>n==='reject'&&done?REOPEN.help:ACTIONS[n].help;
 const lead=LEAD.find(n=>allowed.includes(n))||(done&&allowed.includes('reject')?'reject':undefined);
 const shown=lead?[lead,...allowed.filter(n=>n!==lead)]:allowed;
 const run=(name:ActionName)=>name==='assign' ? setForm('assign') : name==='create_task' ? setForm('task') : name==='reject' ? setForm('reject') : ACTIONS[name].confirm ? setConfirm(name) : void save({action:name as 'claim',nodeKey:detail.node.key,expected_revision:detail.node.revision});
 return <DisabledActionReasons.Provider value={false}><div className="pf-node-actions"><div className="pf-actions">{lead && <FlowAction primary={lead!=='reject'} allowed={!busy} reason={reason} help={help(lead)} onClick={()=>run(lead)}>{label(lead)}</FlowAction>}{legacyAllowed && <FlowAction allowed={!busy} reason={reason} onClick={()=>setForm('legacy_complete')}>直接標記完成</FlowAction>}{(shown.length>1 || extra) && <details className="pf-action-more"><summary>其他操作</summary><div className="pf-actions">{shown.filter(name=>name!==lead).map(name=><FlowAction key={name} allowed={!busy} reason={reason} help={help(name)} onClick={()=>run(name)}>{label(name)}</FlowAction>)}{extra}</div></details>}</div>
  {!shown.length && !legacyAllowed && <p className="pf-actions-hint">目前沒有你可執行的節點操作。</p>}
  {confirm && <div className="pf-confirm" role="group" aria-label={`確認${ACTIONS[confirm].label}`}><p>{ACTIONS[confirm].confirm}</p><div className="pf-actions"><button type="button" className="button compact" onClick={()=>setConfirm('')}>取消</button><button type="button" className="button primary compact" disabled={busy} onClick={()=>{const action=confirm;setConfirm('');void save({action:action as 'complete',nodeKey:detail.node.key,expected_revision:detail.node.revision})}}>確認{ACTIONS[confirm].label}</button></div></div>}
  {form==='assign' && <AssignForm detail={detail} busy={busy} error={error} onCancel={()=>setForm('')} onSubmit={ids=>save({action:'assign',nodeKey:detail.node.key,owner_open_ids:ids,expected_revision:detail.node.revision})}/>}
  {form==='task' && <TaskCreator detail={detail} busy={busy} error={error} onCancel={()=>setForm('')} onSubmit={task=>save({action:'create_task',nodeKey:detail.node.key,task})}/>}
  {form==='reject' && <RejectForm reopen={done} busy={busy} error={error} onCancel={()=>setForm('')} onSubmit={reason=>save({action:'reject',nodeKey:detail.node.key,reason,expected_revision:detail.node.revision})}/>}
  {form==='legacy_complete' && <LegacyCompleteForm busy={busy} error={error} onCancel={()=>setForm('')} onSubmit={reason=>save({action:'legacy_complete',nodeKey:detail.node.key,reason,expected_revision:detail.node.revision})}/>}
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
