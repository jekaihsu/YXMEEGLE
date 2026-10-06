import type {Project} from './types';
import {ActionForm, Field, Status, who, type Context} from './Operations';
import {executionAllowed} from './ProjectExecution';

const groups:Record<string,string>={field:'外業',control:'控制',mapping:'圖資',report:'報告'};
type Proposal={id:string;status:string;applies:boolean;groups:string[];reason:string;proposed_by:string;supervisors:Record<string,string>;confirmations:{actor_id:string}[];return_reason?:string};
export function SopApplicability({c,p}:{c:Context;p:Project}){
 const proposal=p.sop_applicability_proposal as Proposal|undefined;
 const user=c.s.user?.id||''; const allowed=executionAllowed(p,c.w);
 const stale=proposal?.status==='pending'&&(proposal.proposed_by!==p.pm_id||Object.entries(proposal.supervisors).some(([group,id])=>id!==(group==='project'?p.supervisor_id:p.nodes.find(n=>n.key===group)?.supervisor_id||p.supervisor_id)));
 const canPropose=allowed&&user===p.pm_id&&(!proposal||proposal.status==='returned'||stale);
 const canConfirm=allowed&&!stale&&proposal?.status==='pending'&&Object.values(proposal.supervisors).includes(user)&&user!==p.pm_id&&!proposal.confirmations.some(v=>v.actor_id===user);
 return <section aria-labelledby={`subcontract-${p.id}`}>
  <h3 id={`subcontract-${p.id}`}>報價前的下包需求確認</h3>
  <p>PM 彙整是否下包及作業組別，由對應主管確認範圍。有下包時，先收齊下包報價再提出業主報價。</p>
  {stale&&<p role="status">PM 或主管已變更，請目前 PM 重新彙整，原提案保留歷史。</p>}
  {proposal?<><p><Status value={proposal.status}/> · {proposal.applies?`下包組別：${proposal.groups.map(g=>groups[g]).join('、')}`:'無下包需求'}</p><p>{proposal.reason}</p>
   {proposal.status==='returned'&&<p role="status">退回理由：{proposal.return_reason}</p>}
   <ul>{Object.entries(proposal.supervisors).map(([group,id])=><li key={group}>{groups[group]||'案件'}主管：{who(c,id)} · {proposal.confirmations.some(v=>v.actor_id===id)?'已確認':'待確認'}</li>)}</ul>
  </>:<p className="ops-notice">尚未確認下包需求。請案件 PM 彙整，再交對應主管確認。</p>}
  {canPropose&&<ActionForm key={`${p.id}:${proposal?.id||'new'}`} title="彙整下包需求" draftId={`sop-propose:${p.id}:${proposal?.id||'new'}`} busy={c.busy} onSubmit={(d,e)=>c.run('sop_applicability_propose',{
   applies:d.applies==='true',groups:d.applies==='true'?new FormData(e.currentTarget).getAll('groups'):[],reason:d.reason,
  },{project_id:p.id})}>
   <Field title="是否下包" name="applies"><select name="applies" required defaultValue=""><option value="" disabled>請選擇</option><option value="false">無下包需求</option><option value="true">有下包需求</option></select></Field>
   <fieldset><legend>下包作業組別（有下包時選填）</legend>{Object.entries(groups).map(([key,name])=><label key={key}><input type="checkbox" name="groups" value={key}/>{name}</label>)}</fieldset>
   <Field title="工作範圍及判斷理由" name="reason"><textarea name="reason" required maxLength={2000}/></Field>
  </ActionForm>}
  {canConfirm&&<ActionForm key={`${p.id}:${proposal.id}`} title="確認本次下包範圍" draftId={`sop-confirm:${p.id}:${proposal.id}`} busy={c.busy} onSubmit={d=>c.run('sop_applicability_confirm',{...d,proposal_id:proposal.id},{project_id:p.id})}>
   <Field title="確認結果" name="result"><select name="result"><option value="approved">確認範圍</option><option value="returned">退回 PM 補充</option></select></Field>
   <Field title="退回理由（退回時必填）" name="reason" required={false}/>
  </ActionForm>}
 </section>;
}

export function SopFollowups({c,p}:{c:Context;p:Project}){
 const tasks=(p.sop_followups||[]) as {id:string;title:string;owner_id:string;due_date:string;status:string;output?:string}[];
 if(!tasks.length)return null;
 return <section><h3>完成後追蹤</h3><p>這些通知或追蹤工作另留紀錄，原節點的完成成果與確認仍保留。</p>
  {tasks.map(task=><article key={task.id}><h4>{task.title}</h4><p>{who(c,task.owner_id)} · {task.due_date} · <Status value={task.status}/></p>
   {task.output&&<p>{task.output}</p>}
   {executionAllowed(p,c.w)&&task.status==='pending'&&task.owner_id===c.s.user?.id&&<ActionForm key={`${p.id}:${task.id}`} title={`交付追蹤成果：${task.title}`} draftId={`sop-followup:${p.id}:${task.id}`} busy={c.busy} onSubmit={d=>c.run('sop_followup_complete',{...d,id:task.id},{project_id:p.id})}>
    <Field title="追蹤成果" name="output"><textarea name="output" required maxLength={10000}/></Field>
   </ActionForm>}
  </article>)}
 </section>;
}
