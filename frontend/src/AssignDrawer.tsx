import {useId,useRef,useState} from 'react';
import {Button} from './design';
import {AssigneePicker} from './AssigneePicker';
import {TaskDrawer,DrawerFacts} from './TaskDrawer';
import {FIELD_LABELS,changedFields,classifyFailure,draftOf,fieldOutcomes,patchOf,validateDraft,verdict,type AssignDraft,type AssignField} from './assignDrawerModel';
import {taskStatusText} from './stageModel';
import type {AssignablePerson,AssignmentMutation,AssignmentTask} from './nodeAssignmentApi';
import './AssignDrawer.css';

type Phase={k:'edit'}|{k:'discard'}|{k:'saving'}|{k:'conflict'}|{k:'unknown';verifying:boolean;note:string;canRetry:boolean}|{k:'revoked'}|{k:'partial';latest:AssignDraft};
type Props={task:AssignmentTask|undefined;nodeKey:string;nodeLabel:string;caseLabel:string;people:AssignablePerson[];unavailableReason:string;mutate:(m:AssignmentMutation,onFailure?:(message:string,failure:unknown)=>void)=>Promise<boolean>;retry:()=>Promise<boolean>;verify:()=>Promise<AssignmentTask|undefined>;refresh:()=>void;onClose:(saved:boolean)=>void};
const valueText=(draft:AssignDraft,field:AssignField,people:AssignablePerson[],task?:AssignmentTask)=>field==='due'?draft.due||'未排期限':draft.assignee?people.find(p=>p.open_id===draft.assignee)?.name||(task?.assignee?.open_id===draft.assignee?task.assignee.name:'')||'目前負責人':'尚未指派';

export function AssignDrawer({task,nodeKey,nodeLabel,caseLabel,people,unavailableReason,mutate,retry,verify,refresh,onClose}:Props){
 const first=useRef(task);const [base,setBase]=useState(task);
 const baseDraft=base?draftOf(base):{assignee:'',due:''};
 const [draft,setDraft]=useState<AssignDraft>(baseDraft);
 const [phase,setPhase]=useState<Phase>({k:'edit'});
 const [errors,setErrors]=useState<Partial<Record<AssignField,string>>>({});
 const failure=useRef<unknown>(null);const id=useId();
 const dirty=!!base&&changedFields(baseDraft,draft).length>0;
 const live=task;const latestDraft=live?draftOf(live):baseDraft;
 const blockReason=!live?'此任務已不在可見範圍。':unavailableReason||(!live.can.assign?'你可查看此任務，但目前無指派權限。':phase.k==='revoked'?'權限已變更，已停止送出。':'');
 const locked=!!blockReason||phase.k==='saving'||phase.k==='unknown'||phase.k==='partial';
 const requestClose=()=>{if(phase.k==='saving')return;if(dirty&&phase.k!=='discard'&&phase.k!=='revoked'){setPhase({k:'discard'});return}onClose(false)};
 const update=(field:AssignField,value:string)=>{setDraft(d=>({...d,[field]:value}));setErrors(e=>({...e,[field]:undefined}))};
 const submit=async()=>{
  if(!base||locked||!live)return;
  const found=validateDraft(baseDraft,draft,people);setErrors(found);
  if(Object.values(found).some(Boolean)||!dirty)return;
  setPhase({k:'saving'});failure.current=null;
  const ok=await mutate({action:'update_task',nodeKey,taskId:base.id,expected_revision:base.revision,patch:patchOf(baseDraft,draft)},(_message,error)=>{failure.current=error});
  if(ok){onClose(true);return}
  const result=classifyFailure(failure.current);
  if(result.kind==='conflict')setPhase({k:'conflict'});
  else if(result.kind==='revoked'){refresh();setPhase({k:'revoked'})}
  else if(result.kind==='unknown')setPhase({k:'unknown',verifying:false,note:'尚無法確認儲存結果。請先查詢最新結果，確認未套用後才能重試。',canRetry:false});
  else{setErrors(result.fields);setPhase({k:'edit'})}
 };
 const check=async()=>{
  setPhase({k:'unknown',verifying:true,note:'正在查詢最新結果…',canRetry:false});
  try{
   const latest=await verify();
   if(!latest){onClose(false);return}
   const saved=draftOf(latest),result=verdict(baseDraft,draft,saved,base?.revision||'',latest.revision);
   if(result==='applied'){onClose(true);return}
   if(result==='partial'){setPhase({k:'partial',latest:saved});return}
   if(result==='moved'){setPhase({k:'conflict'});return}
   setPhase({k:'unknown',verifying:false,note:'已確認此次變更尚未套用，可以重試同一操作。',canRetry:true});
  }catch{setPhase({k:'unknown',verifying:false,note:'仍無法確認結果，請稍後再查詢。為避免重複送出，暫不允許重試。',canRetry:false})}
 };
 const resend=async()=>{
  setPhase({k:'saving'});failure.current=null;
  if(await retry()){onClose(true);return}
  setPhase({k:'unknown',verifying:false,note:'重試後仍無法確認結果，請再次查詢最新結果。',canRetry:false});
 };
 const rebase=()=>{if(live){setBase(live);setErrors({});setPhase({k:'edit'})}};
 const messages=Object.entries(errors).filter(([,v])=>v) as [AssignField,string][];
 const diff=(rows:{label:string;mine:string;theirs:string}[])=><table className="ad-diff"><thead><tr><th scope="col">欄位</th><th scope="col">你的草稿</th><th scope="col">最新值</th></tr></thead><tbody>{rows.map(r=><tr key={r.label}><th scope="row">{r.label}</th><td>{r.mine}</td><td>{r.theirs}</td></tr>)}</tbody></table>;
 const fields=(Object.keys(FIELD_LABELS) as AssignField[]).filter(k=>baseDraft[k]!==draft[k]);
 return <TaskDrawer kind="lark" label={`指派任務：${first.current?.title||''}`} trail={[caseLabel,nodeLabel,'指派任務']} title={base?.title||'任務'} status={base&&<span className="ad-status">任務狀態：{taskStatusText(base.status)}</span>} onClose={requestClose}
  footer={<><div className="task-drawer-secondary"><Button onClick={requestClose} disabled={phase.k==='saving'}>取消</Button></div><div className="task-drawer-primary">{phase.k==='conflict'?<Button variant="primary" onClick={rebase}>以最新值重新檢查</Button>:phase.k==='unknown'?<><Button onClick={()=>void check()} disabled={phase.verifying}>查詢最新結果</Button><Button variant="primary" onClick={()=>void resend()} disabled={!phase.canRetry}>重試同一操作</Button></>:phase.k==='partial'?<Button variant="primary" onClick={rebase}>重新檢查未儲存欄位</Button>:<Button variant="primary" type="submit" form={`${id}-form`} disabled={locked||!dirty} disabledReason={phase.k==='saving'?'儲存中，請稍候。':blockReason||'請先修改執行人或期限。'}>{phase.k==='saving'?'儲存中…':'儲存'}</Button>}</div></>}>
  <DrawerFacts facts={[{label:'案件',value:caseLabel},{label:'節點',value:nodeLabel},{label:'目前執行人',value:base?.assignee?.name||'尚未指派'},{label:'最新讀取版本',value:base?.revision.slice(0,12)||'—'}]}/>
  {phase.k==='discard'&&<div className="ad-panel" role="alertdialog" aria-labelledby={`${id}-discard`}><h3 id={`${id}-discard`}>放棄尚未儲存的變更？</h3><p>放棄後不會送出任何請求，重新開啟時會讀取最新資料。</p><div className="ad-actions"><Button onClick={()=>setPhase({k:'edit'})}>保留編輯</Button><Button variant="destructive" onClick={()=>onClose(false)}>放棄變更</Button></div></div>}
  {phase.k==='conflict'&&live&&<div className="ad-panel" role="alert"><h3>此任務已被他人修改</h3><p>你的草稿已保留，尚未送出。請確認最新值後明確再送出，系統不會覆蓋他人的變更。</p>{diff((Object.keys(FIELD_LABELS) as AssignField[]).map(k=>({label:FIELD_LABELS[k],mine:valueText(draft,k,people,live),theirs:valueText(latestDraft,k,people,live)})))}<small>最新讀取版本 {live.revision.slice(0,12)}</small></div>}
  {phase.k==='unknown'&&<div className="ad-panel" role="alert"><h3>儲存結果不明</h3><p>{phase.note}</p></div>}
  {phase.k==='partial'&&<div className="ad-panel" role="alert"><h3>只有部分欄位已儲存</h3><ul>{(Object.entries(fieldOutcomes(baseDraft,draft,phase.latest)) as [AssignField,string][]).filter(([,o])=>o!=='unchanged').map(([k,o])=><li key={k}>{FIELD_LABELS[k]}：{o==='saved'?'已儲存':'尚未儲存'}</li>)}</ul><p>此次不算完整成功，已重新讀取最新資料。</p></div>}
  {phase.k==='revoked'&&<div className="ad-panel" role="alert"><h3>權限已變更</h3><p>伺服器拒絕了這次變更，已停止送出並重新讀取你的權限。草稿未送出。</p></div>}
  {blockReason&&phase.k==='edit'&&<p className="ad-reason" role="status">{blockReason}</p>}
  {messages.length>0&&<div className="ad-summary" role="alert"><strong>請修正 {messages.length} 個欄位</strong><ul>{messages.map(([k,v])=><li key={k}><a href={`#${id}-${k}`} onClick={e=>{e.preventDefault();document.getElementById(`${id}-${k}`)?.focus()}}>{FIELD_LABELS[k]}：{v}</a></li>)}</ul></div>}
  <form id={`${id}-form`} className="ad-form" noValidate onSubmit={e=>{e.preventDefault();void submit()}}>
   <div className="ad-field"><span id={`${id}-assignee-label`}>執行人</span><div id={`${id}-assignee`} tabIndex={-1} aria-labelledby={`${id}-assignee-label`}><AssigneePicker title={base?.title||''} value={draft.assignee} valueLabel={valueText(draft,'assignee',people,base)} people={people.map(p=>({id:p.open_id,name:p.name,teams:p.departments}))} disabled={locked} busy={phase.k==='saving'} onChange={value=>update('assignee',value)}/></div>{!people.length&&!blockReason&&<small>目前沒有可指派的人員。</small>}{errors.assignee&&<small className="ad-error">{errors.assignee}</small>}</div>
   <div className="ad-field"><label htmlFor={`${id}-due`}>期限</label><input id={`${id}-due`} type="date" value={draft.due} disabled={locked} aria-invalid={!!errors.due} aria-describedby={errors.due?`${id}-due-err`:undefined} onChange={e=>update('due',e.target.value)}/>{errors.due&&<small className="ad-error" id={`${id}-due-err`}>{errors.due}</small>}</div>
   {fields.length>0&&<p className="ad-dirty" role="status">尚未儲存：{fields.map(k=>FIELD_LABELS[k]).join('、')}</p>}
  </form>
  <p className="ad-note">指派成功不會自動開始任務、完成節點、送出核准或切換階段。</p>
 </TaskDrawer>;
}
