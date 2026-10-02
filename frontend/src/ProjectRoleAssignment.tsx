import {ActionForm, Field, Person, type Context} from './Operations';
import type {Project,Node} from './types';

export function ProjectRoleAssignment({c,p,n}:{c:Context;p:Project;n:Node}){
 const manage=c.s.user?.role==='manager'||c.s.user?.capabilities?.includes('manage_roles');
 return <ActionForm key={`${p.id}:${n.id}`} title="指定案件代表與本節點負責人" busy={c.busy} onSubmit={(d,e)=>{
  const form=new FormData(e.currentTarget);
  void c.run('project_roles',{...d,...(manage?{reviewers:form.getAll('reviewers')}:{ }),issuer_ids:form.getAll('issuer_ids')},{project_id:p.id,node_id:n.id});
 }}>
  <Person c={c} name="pm_id" value={p.pm_id} label="案件 PM"/>
  <Person c={c} name="admin_id" value={p.admin_id} label="行政代表"/>
  <Person c={c} name="sales_id" value={p.sales_id} label="業務代表（報價確認）"/>
  <Person c={c} name="quotation_id" value={p.quotation_id} label="報價組承辦"/>
  <Person c={c} name="assistant_id" value={p.assistant_id} label="工務助理"/>
  <Person c={c} name="owner_id" value={n.owner_id} label="本節點負責人"/>
  {manage?<>
   <Person c={c} name="supervisor_id" value={p.supervisor_id} label="案件主管"/>
   <Person c={c} name="node_supervisor_id" value={n.supervisor_id} label="本節點主管"/>
   <fieldset><legend>其他指定確認人</legend>{c.w.users.filter(u=>u.active!==false).map(u=><label key={u.id}><input type="checkbox" name="reviewers" value={u.id} defaultChecked={n.reviewers?.includes(u.id)}/>{u.name}</label>)}</fieldset>
   <Field title="一般節點確認模式" name="review_mode"><select name="review_mode" defaultValue={n.review_mode||'all'}><option value="all">全員通過</option><option value="any">任一指定人通過（必要覆核仍適用）</option></select></Field>
  </>:<p>審核主管與通過規則由人員權限管理者維護，PM 可調整日常工作指派。</p>}
  <fieldset><legend>確認單發出承辦（可複選）</legend>{c.w.users.filter(u=>u.active!==false).map(u=><label key={u.id}><input type="checkbox" name="issuer_ids" value={u.id} defaultChecked={p.issuer_ids?.includes(u.id)}/>{u.name}</label>)}</fieldset>
 </ActionForm>;
}
