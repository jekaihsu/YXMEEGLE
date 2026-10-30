import {Select as FormSelect} from './design/Select';
import {buildFlowModel} from './flowModel';
import type {useNodeAssignments} from './useNodeAssignments';
import {FlowSchedule} from './FlowSchedule';
import {ProjectRoleAssignment} from './ProjectRoleAssignment';
import {nameOf,type Ctx} from './appCommon';
import type {Project} from './types';
type Props={c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>;selectedKey:string};
export function ProjectPeople({c,p,assignments,selectedKey}:Props){
 const list='data' in assignments.state ? assignments.state.data : undefined,model=buildFlowModel({project:assignments.state.kind==='disabled' ? p : {...p,nodes:[]},assignments:list,today:c.w.as_of,users:c.w.users});
 const node=model.nodes.find(n=>n.key===selectedKey) || model.nodes[0],local=p.nodes.find(n=>n.key===node.key);
 return <section className="detail-page-content"><h2>排程與人員</h2><p>案件 PM · {p.pm_id ? nameOf(c.w,p.pm_id) : '尚未指派'} · 案件期限 {p.due_date || '未排定'}</p><label>節點<FormSelect value={node.key} onChange={e=>c.go({view:'project',project:p.id,tab:'people',node:e.target.value})}>{model.nodes.map(n=><option key={n.key} value={n.key}>{n.label}</option>)}</FormSelect></label><p>負責人 · {node.owners.map(o=>o.name).join('、') || '尚未指派'} · 節點期限 {node.finalDeadline?.slice(0,10) || '未排定'}</p><FlowSchedule key={node.key} project={p} node={node} session={c.s} onPublished={()=>void assignments.reload()}/>{local && <details><summary>案件角色與本地節點負責人</summary><ProjectRoleAssignment c={c} p={p} n={local}/></details>}</section>;
}
