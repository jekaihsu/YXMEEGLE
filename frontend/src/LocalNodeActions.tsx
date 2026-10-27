import {useRef,useState} from 'react';
import {Button} from './design';
import {FlowAction} from './FlowActions';
import {NODE_ACTIONS,type NodeWorkbench} from './nodeWorkbenchModel';
import {sopApi,sopErrorText} from './sopTaskApi';
import type {useSopTasks} from './useSopTasks';

export function LocalNodeActions({workbench,sop,projectId}:{workbench:NodeWorkbench;sop:ReturnType<typeof useSopTasks>;projectId:string}) {
 const [form,setForm]=useState<'assign'|'complete'|'reject'|null>(null),[person,setPerson]=useState(''),[reason,setReason]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const local=workbench.local;
 const trigger=useRef<HTMLElement|null>(null);
 const close=()=>{setForm(null);requestAnimationFrame(()=>{const target=trigger.current?.isConnected?trigger.current:document.getElementById('flow-selected');target?.focus({preventScroll:true})})};
 const submit=async()=>{
  if(!local||!form||busy)return;setBusy(true);setError('');
  try {await sopApi.localNode(projectId,local.key,{action:form,expected_revision:local.revision,...(form==='assign'?{owner_id:person}:{reason:reason.trim()})},sop.current);if(sop.current()){await sop.reload();close();requestAnimationFrame(()=>document.getElementById('flow-selected')?.scrollIntoView({block:'start',behavior:'auto'}))}}
  catch(e){if(sop.current()){setError(sopErrorText(e));await sop.reload()}}
  finally{if(sop.current())setBusy(false)}
 };
 const commands={assign:()=>{setPerson(local?.ownerId||'');setForm('assign')},complete:()=>{setReason('');setForm('complete')},reject:()=>{setReason('');setForm('reject')}};
 if(local&&!Object.values(local.can).some(Boolean))return <p className="nw-action-reason">{local.disabledReason||'僅供檢視'}</p>;
 return <div className="nw-local-actions"><div className="nw-actions">{NODE_ACTIONS.filter(([id])=>workbench.actions[id].visible && id in commands).map(([id,label])=>{
  const action=workbench.actions[id];return <FlowAction key={id} allowed={action.enabled&&!busy} reason={busy?'正在儲存，請稍候':action.disabledReason} primary={id==='complete'} onClick={()=>{trigger.current=document.activeElement instanceof HTMLElement?document.activeElement:null;if(id==='assign'||id==='complete'||id==='reject')commands[id]()}}>{label}</FlowAction>;
 })}</div>
 {form && <form className="nw-local-form" aria-label={form==='assign'?'指派節點負責人':form==='complete'?'確認完成節點':'退回節點'} onKeyDown={e=>{if(e.key==='Escape'&&!busy){e.preventDefault();close()}}} onSubmit={e=>{e.preventDefault();void submit()}}>
  {form==='assign'?<label>節點負責人<select aria-label="節點負責人" value={person} disabled={busy} onChange={e=>setPerson(e.target.value)}><option value="">選擇負責人</option>{sop.assignees.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>:<label>{form==='complete'?'完成依據':'退回原因'}<textarea aria-label={form==='complete'?'完成依據':'退回原因'} autoFocus rows={2} required maxLength={1000} value={reason} disabled={busy} onChange={e=>setReason(e.target.value)}/></label>}
  <Button disabled={busy} onClick={close}>取消</Button><Button type="submit" variant="primary" disabled={busy||(form==='assign'?!person:!reason.trim())} disabledReason={form==='assign'?'請選擇負責人':'請填寫原因'}>確認{form==='assign'?'指派':form==='complete'?'完成':'退回'}</Button>
 </form>}{error && <p role="alert">{error}</p>}{sop.assigneeError && <p role="alert">{sop.assigneeError}</p>}</div>;
}
