import {Select as FormSelect} from './design/Select';
import {Skeleton} from './design';
import {buildFlowModel,type FlowNode} from './flowModel';
import type {useNodeAssignments} from './useNodeAssignments';
import {FlowSchedule} from './FlowSchedule';
import {ProjectRoleAssignment} from './ProjectRoleAssignment';
import {Avatar} from './AppShell';
import {Primary,isProjectLead,nameOf} from './appCommon';
import {NODE_NAMES} from './workflowLabels';
import type {Ctx} from './appCommon';
import type {Project} from './types';
type Props={c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>;selectedKey:string;onParticipants:()=>void};
type Row={key:string;node:string;owners:{id:string;name:string;user?:unknown}[];others:string;deadline:string;source:string};
const day=(value?:string|null)=>value?.slice(0,10)||'未排定';

/** One row per node and source. Lark assignment and 本地流程 rows stay separate identities, told apart by the 來源 column. */
export function participantRows(c:Pick<Ctx,'w'>,p:Project,assignments:ReturnType<typeof useNodeAssignments>,nodes:FlowNode[]):Row[]{
 const data='data' in assignments.state ? assignments.state.data : undefined;
 const deadline=(key:string)=>day(nodes.find(n=>n.key===key)?.finalDeadline);
 const lark:Row[]=(data?.nodes||[]).map(n=>({key:`lark:${n.key}`,node:n.label,owners:n.owners.map(o=>({id:o.open_id,name:o.name,user:o})),others:data?.node_details?.[n.key]?.tasks.map(t=>t.assignee?.name||'尚未指派').join('、')||'',deadline:deadline(n.key),source:['Lark 指派',n.assignment_method,n.assigned_by?.name&&`${n.assigned_by.name}指派`].filter(Boolean).join(' · ')}));
 const local:Row[]=p.nodes.filter(n=>!data||n.owner_id||n.collaborator_ids.length||n.tasks.some(t=>t.status!=='superseded')).map(n=>{
  const tasks=n.tasks.filter(t=>t.status!=='superseded').length,team=n.collaborator_ids.map(id=>nameOf(c.w,id)).join('、');
  return {key:`local:${n.id}`,node:NODE_NAMES[n.key]||n.name,owners:n.owner_id?[{id:n.owner_id,name:nameOf(c.w,n.owner_id),user:c.w.users.find(u=>u.id===n.owner_id)}]:[],others:[team,tasks?`${tasks} 項任務`:''].filter(Boolean).join(' · '),deadline:data?'未排定':deadline(n.key),source:'本地流程'};
 });
 return [...lark,...local];
}

export function ProjectPeople({c,p,assignments,selectedKey,onParticipants}:Props){
 const list='data' in assignments.state ? assignments.state.data : undefined,model=buildFlowModel({project:assignments.state.kind==='disabled' ? p : {...p,nodes:[]},assignments:list,today:c.w.as_of,users:c.w.users});
 const node=model.nodes.find(n=>n.key===selectedKey) || model.nodes[0],local=p.nodes.find(n=>n.key===node.key);
 const state=assignments.state,rows=participantRows(c,p,assignments,model.nodes),lead=isProjectLead(c.s,p);
 return <section className="detail-page-content"><h2>排程與人員</h2>
  <div className="section-heading"><div><h3>案件參與人員</h3><p>各節點負責人作為子任務預設指派；個別改派保留。</p></div><Primary disabled={!lead} disabledReason="需由本案專案經理或主管調整" onClick={onParticipants}>統一設定人員</Primary></div>
  {state.kind==='error'&&<p role="alert">{state.message}</p>}{state.kind==='loading'&&<Skeleton lines={4}/>}
  <div className="table-scroll"><table className="data-table"><thead><tr><th>節點</th><th>負責人</th><th>協作與任務人員</th><th>節點期限</th><th>來源</th></tr></thead><tbody>{rows.map(r=><tr key={r.key}><td>{r.node}</td><td>{r.owners.length?r.owners.map(o=><span className="person-cell" key={o.id}><Avatar small user={o.user as never}/>{o.name}</span>):'尚未指派'}</td><td>{r.others||<span className="muted">尚未設定</span>}</td><td>{r.deadline}</td><td>{r.source}</td></tr>)}</tbody></table></div>
  <label>節點<FormSelect value={node.key} onChange={e=>c.go({view:'project',project:p.id,tab:'people',node:e.target.value})}>{model.nodes.map(n=><option key={n.key} value={n.key}>{n.label}</option>)}</FormSelect></label>
  <FlowSchedule key={node.key} project={p} node={node} session={c.s} onPublished={()=>void assignments.reload()}/>{local && <details><summary>案件角色與本地節點負責人</summary><ProjectRoleAssignment c={c} p={p} n={local}/></details>}</section>;
}
