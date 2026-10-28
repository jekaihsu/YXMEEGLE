import {useEffect,useId,useRef,useState} from 'react';
import {getSessionEpoch} from './api';
import {AssigneePicker} from './AssigneePicker';
import {Badge,Button} from './design';
import type {AssignablePerson} from './nodeAssignmentApi';
import type {OverviewTodo} from './overviewDashboardModel';
import type {OverviewTarget} from './projectOverviewModel';
import {SopError,sopApi,sopErrorText} from './sopTaskApi';
import type {useSopTasks} from './useSopTasks';
import type {useNodeAssignments} from './useNodeAssignments';

type TaskRow=Exclude<OverviewTodo,{kind:'recommendation'}>;
export function OverviewTaskRow({row,projectId,today,sop,assignments,people=[],locked=false,go,href}:{row:TaskRow;projectId:string;today:string;sop:Pick<ReturnType<typeof useSopTasks>,'current'|'applyTask'|'reload'>;assignments:Pick<ReturnType<typeof useNodeAssignments>,'mutate'|'pending'>;people?:AssignablePerson[];locked?:boolean;go:(target:OverviewTarget)=>void;href:string}){
 const [saving,setSaving]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [menu,setMenu]=useState(false);
 const menuRoot=useRef<HTMLDivElement>(null),writing=useRef(false),life=useRef(true),id=useId();
 useEffect(()=>{life.current=true;return()=>{life.current=false}},[]);
 useEffect(()=>{if(menu)menuRoot.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()},[menu]);
 const close=()=>{setMenu(false);menuRoot.current?.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.focus()};
 const canAssign=row.kind==='sopTask'?row.permissions.includes('edit'):row.permissions.assign;
 const canEdit=row.kind==='sopTask'?row.permissions.includes('edit'):row.permissions.edit_details;
 const status=row.kind==='sopTask'?({pending:'待處理',in_progress:'進行中',blocked:'受阻',done:'已完成',archived:'已封存'})[row.task.state]:row.task.status;
 const overdue=row.kind==='sopTask'?row.task.overdue:!!row.deadline&&row.deadline.slice(0,10)<today.slice(0,10)&&status!=='已完成';
 const busy=saving || !!assignments.pending;
 const assign=async(person:string)=>{
  if(writing.current || busy || locked || !canAssign)return;
  const epoch=getSessionEpoch(),current=()=>life.current&&epoch===getSessionEpoch()&&sop.current();
  writing.current=true;setSaving(true);setError('');setNotice('');
  try{
   if(row.kind==='sopTask'){
    const participants=Object.fromEntries(Object.entries({...row.task.participants,executor:person}).filter(([,value])=>value));
    const result=await sopApi.patch(projectId,row.task.id,{expected_revision:row.revision,participants},current);
    if(!current())return;
    if(result.task)sop.applyTask(result.task,result.checklist_revision);else await sop.reload();
    setNotice('已更新負責人');
   }else{
    let failureMessage='尚未儲存，請核對最新資料後重試';
    const ok=await assignments.mutate({action:'update_task',nodeKey:row.node.key,taskId:row.task.id,expected_revision:row.revision,patch:{assignee_open_id:person || null}},message=>{failureMessage=message});
    if(current()){if(ok)setNotice('已更新負責人');else setError(failureMessage)}
   }
  }catch(failure){
   if(!current())return;
   if(failure instanceof SopError && failure.status===409){await sop.reload();if(current())setError('資料已被他人更新，已重新載入，請重新選擇負責人')}
   else{setError(sopErrorText(failure));if(failure instanceof SopError&&failure.ambiguous)await sop.reload()}
  }finally{writing.current=false;if(current())setSaving(false)}
 };
 return <li className="po-task-row" aria-busy={saving}>
  <div className="po-task-title"><a href={href} onClick={e=>{e.preventDefault();go(row.target)}}>{row.title} · {row.node.label}</a>{row.node.progress.basis==='tasks'&&<small>節點 {row.node.tasks.done}/{row.node.tasks.total} 已完成</small>}</div>
  <div className="po-task-executor">{canAssign?<AssigneePicker projectId={row.kind==='sopTask'?projectId:undefined} people={row.kind==='larkTask'?people.map(p=>({id:p.open_id,name:p.name})):undefined} nodeKey={row.node.key} title={row.title} value={row.ownerId} valueLabel={row.ownerId?row.owner:'指派'} busy={busy||locked} onChange={person=>void assign(person)}/>:<span>{row.ownerId?row.owner:'未指派'}</span>}</div>
  <Badge tone={status==='受阻'?'warning':status==='已完成'?'positive':undefined}>{status}</Badge>
  <div className="po-task-date">{row.deadline?<><time dateTime={row.deadline}>{row.deadline.slice(0,10)}</time>{overdue&&<span>已逾期</span>}</>:canEdit?<Button disabled={locked||busy} onClick={()=>go(row.target)}>排定日期</Button>:<span>未排定日期</span>}</div>
  <div ref={menuRoot} className="po-task-menu" onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setMenu(false)}}>
   <Button aria-label={`更多操作：${row.title}`} aria-haspopup="menu" aria-expanded={menu} aria-controls={id} onClick={()=>menu?close():setMenu(true)} onKeyDown={e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setMenu(true)}else if(e.key==='Escape')close()}}>⋯</Button>
   {menu&&<div id={id} role="menu" aria-label={`任務操作：${row.title}`} onKeyDown={e=>{if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();menuRoot.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()}else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close()}else if(e.key==='Tab')setMenu(false)}}><Button role="menuitem" onClick={()=>{close();go(row.target)}}>{canEdit?'編輯詳情':'查看詳情'}</Button></div>}
  </div>
  {(saving||error||notice)&&<div className="po-task-feedback">{saving?<span role="status">儲存中…</span>:error?<span role="alert">{error}</span>:<span role="status">{notice}</span>}</div>}
 </li>;
}
