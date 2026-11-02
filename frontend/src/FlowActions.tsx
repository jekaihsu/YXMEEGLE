import {DetailsMenu} from './design/DetailsMenu';
import {actionRegistry,type ActionRegistry} from './nodeWorkbenchModel';
import {useRef,useState,type ReactNode} from 'react';
import {DisabledAction,DisabledActionReasons} from './design';
import {AssignForm,TaskCreator,RejectForm,LegacyCompleteForm} from './NodeAssignmentForms';
import type {AssignmentMutation,NodeAssignmentDetail,NodeAssignmentError} from './nodeAssignmentApi';
export function FlowAction({allowed,reason,children,onClick,primary}:{allowed:boolean;reason:string;children:ReactNode;onClick:()=>void;primary?:boolean}){
 const button=<DisabledAction disabled={!allowed} reason={reason}>{id=><button className={primary?'button primary compact':'button plain compact'} type="button" disabled={!allowed} title={allowed?undefined:reason} aria-describedby={id} onClick={onClick}>{children}</button>}</DisabledAction>;
 return button;
}
export function FlowPeopleLink({href,allowed,reason}:{href:string;allowed:boolean;reason:string}){
 return <DisabledAction disabled={!allowed} reason={reason}>{id=><a className="pf-people-link" href={href} aria-disabled={!allowed||undefined} aria-describedby={id} onClick={e=>{if(!allowed)e.preventDefault()}}>前往排程與人員</a>}</DisabledAction>;
}
type ActionName='claim'|'assign'|'create_task'|'complete'|'approve'|'reject';
const ACTIONS:Record<ActionName,{label:string;confirm?:string}>={
 approve:{label:'核准',confirm:'確定核准？核准後節點即正式完成。'},
 claim:{label:'認領節點'},
 complete:{label:'完成節點',confirm:'確定完成此節點？'},
 assign:{label:'指派負責人'},
 create_task:{label:'新增任務'},
 reject:{label:'退回節點'}};
const ORDER=Object.keys(ACTIONS) as ActionName[];
const REOPEN={label:'取消完成'};
export function FlowNodeActions({detail,busy,error,reason,mutate,registry}:{detail:NodeAssignmentDetail;busy:boolean;error:NodeAssignmentError|null;reason:string;mutate:(m:AssignmentMutation)=>Promise<boolean>;registry?:ActionRegistry}){
 const [form,setForm]=useState<'assign'|'task'|'reject'|'legacy_complete'|''>('');
 const [confirm,setConfirm]=useState<ActionName|''>('');
 const trigger=useRef<HTMLElement|null>(null);
 const closeForm=()=>{setForm('');setConfirm('');requestAnimationFrame(()=>{if(trigger.current?.isConnected)trigger.current.focus({preventScroll:true})})};
 const save=async(m:AssignmentMutation)=>{if(await mutate(m)){closeForm();requestAnimationFrame(()=>document.getElementById('flow-selected')?.scrollIntoView({block:'start',behavior:'auto'}))}};
 const actions=registry || actionRegistry({can:detail.can,busy,reason:reason || detail.writes_disabled_reason || ''});
 const done=detail.node.derived_status==='已完成';
 const unfinished=detail.tasks.filter(t=>!['已完成','取消'].includes(t.status)).length;
 const visibleActions=ORDER.filter(name=>actions[name].visible && !(name==='complete'&&(done||detail.node.derived_status==='略過')));
 const legacyVisible=detail.can.legacy_complete===true && actions.legacy_complete.visible && !done && detail.node.derived_status!=='略過';
 const viewOnly=!visibleActions.length && !legacyVisible;
 if(viewOnly)return <p className="nw-action-reason">{detail.writes_disabled_reason || reason || detail.node.auto_done?.reason || detail.node.derived_status || '僅供檢視'}</p>;
 const label=(n:ActionName)=>n==='reject'&&done?REOPEN.label:ACTIONS[n].label;
 const run=(name:ActionName)=>name==='assign' ? setForm('assign') : name==='create_task' ? setForm('task') : name==='reject' ? setForm('reject') : ACTIONS[name].confirm ? setConfirm(name) : void save({action:name as 'claim',nodeKey:detail.node.key,expected_revision:detail.node.revision});
 const primary=visibleActions.find(n=>n==='approve')||visibleActions.find(n=>n==='complete')||visibleActions.find(n=>n==='create_task')||visibleActions.find(n=>n==='claim');
 const actionButton=(name:ActionName,close?:()=>void)=><FlowAction key={name} primary={name===primary} allowed={actions[name].enabled} reason={actions[name].disabledReason} onClick={()=>{close?.();trigger.current=document.activeElement instanceof HTMLElement?document.activeElement:null;run(name)}}>{label(name)}</FlowAction>;
 return <DisabledActionReasons.Provider value={true}><div className="pf-node-actions" onKeyDown={e=>{if(e.key==='Escape'&&(form||confirm)&&!busy){e.preventDefault();closeForm()}}}><div className="nw-actions">{primary&&actionButton(primary)}{(visibleActions.some(n=>n!==primary)||legacyVisible)&&<DetailsMenu className="pf-more" label="⋯" ariaLabel="更多節點操作">{close=><div>{visibleActions.filter(n=>n!==primary).map(n=>actionButton(n,close))}{legacyVisible&&<FlowAction allowed={actions.legacy_complete.enabled} reason={actions.legacy_complete.disabledReason} onClick={()=>{close();trigger.current=document.activeElement instanceof HTMLElement?document.activeElement:null;setForm('legacy_complete')}}>直接標記完成</FlowAction>}</div>}</DetailsMenu>}</div>
  {confirm && <div className="pf-confirm" role="group" aria-label={`確認${ACTIONS[confirm].label}`}><p>{ACTIONS[confirm].confirm}</p>{confirm==='complete'&&unfinished>0&&<p role="status">尚有 {unfinished} 項任務未完成</p>}<div className="pf-actions"><button type="button" className="button compact" onClick={closeForm}>取消</button><button type="button" className="button primary compact" disabled={busy} onClick={()=>{const action=confirm;setConfirm('');void save({action:action as 'complete',nodeKey:detail.node.key,expected_revision:detail.node.revision})}}>確認{ACTIONS[confirm].label}</button></div></div>}
  {form==='assign' && <AssignForm detail={detail} busy={busy} error={error} onCancel={closeForm} onSubmit={ids=>save({action:'assign',nodeKey:detail.node.key,owner_open_ids:ids,expected_revision:detail.node.revision})}/>}
  {form==='task' && <TaskCreator detail={detail} busy={busy} error={error} onCancel={closeForm} onSubmit={task=>save({action:'create_task',nodeKey:detail.node.key,task})}/>}
  {form==='reject' && <RejectForm reopen={done} busy={busy} error={error} onCancel={closeForm} onSubmit={reason=>save({action:'reject',nodeKey:detail.node.key,reason,expected_revision:detail.node.revision})}/>}
  {form==='legacy_complete' && <LegacyCompleteForm busy={busy} error={error} onCancel={closeForm} onSubmit={reason=>save({action:'legacy_complete',nodeKey:detail.node.key,reason,expected_revision:detail.node.revision})}/>}
 </div></DisabledActionReasons.Provider>;
}
