import {useState} from 'react';
import {createPortal} from 'react-dom';
import {buildFlowModel,productionKey} from './flowModel';
import {useProjectProgress} from './useProjectProgress';
import type {useNodeAssignments} from './useNodeAssignments';
import {ProductionCard} from './FlowEvidence';
import {FlowSourceDetails} from './FlowSourceDetails';
import {FlowSchedule} from './FlowSchedule';
import {ProjectRoleAssignment} from './ProjectRoleAssignment';
import ProgressDetail from './reports/ProgressDetail';
import {progressHash} from './reports/progressView';
import type {ProgressReportRow} from './projectProgressApi';
import {Button} from './design';
import {nameOf,type Ctx} from './appCommon';
import type {Project} from './types';
type Props={c:Ctx;p:Project;assignments:ReturnType<typeof useNodeAssignments>;selectedKey:string};
export function ProjectItems({c,p,assignments,selectedKey}:Props){
 const read=useProjectProgress(p.id),[report,setReport]=useState<ProgressReportRow|null>(null),list='data' in assignments.state ? assignments.state.data : undefined;
 const model=buildFlowModel({project:assignments.state.kind==='disabled' ? p : {...p,nodes:[]},assignments:list,progress:read.state.kind==='ready' ? read.state.data : undefined,today:c.w.as_of,users:c.w.users});
 const category=productionKey(selectedKey) || 'field',node=model.nodes.find(n=>n.key===category)!;
 return <div className="project-flow"><div className="section-heading"><h2>工項與進度</h2><label>生產部門<select value={category} onChange={e=>c.go({view:'project',project:p.id,tab:'items',node:e.target.value})}>{[['field','外業'],['control','控制'],['mapping','圖資'],['report','報告']].map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label></div>{read.state.kind==='ready' ? <><ProductionCard node={node} category={category} data={read.state.data} onDetail={setReport} onReports={row=>{location.hash=progressHash('#view=reports&tab=progress',{dept:row?.dept || (category==='field' ? 'field' : 'office'),week:row?.week || '',group:'',caseKey:'',q:row?.case_code || p.code})}}/><FlowSourceDetails data={read.state.data}/></> : <p role={read.state.kind==='error' ? 'alert' : 'status'}>{read.state.kind==='error' ? `工程證據暫不可用 · ${read.state.message}` : '工程證據載入中'}{read.state.kind==='error' && <Button onClick={read.retry}>重試工程證據</Button>}</p>}{report && createPortal(<ProgressDetail caseKey={report.case_key} dept={report.dept} week={report.week} onClose={()=>setReport(null)}/>,document.body)}</div>;
}
export function ProjectPeople({c,p,assignments,selectedKey}:Props){
 const list='data' in assignments.state ? assignments.state.data : undefined,model=buildFlowModel({project:assignments.state.kind==='disabled' ? p : {...p,nodes:[]},assignments:list,today:c.w.as_of,users:c.w.users});
 const node=model.nodes.find(n=>n.key===selectedKey) || model.nodes[0],local=p.nodes.find(n=>n.key===node.key);
 return <section className="detail-page-content"><h2>排程與人員</h2><p>案件 PM · {p.pm_id ? nameOf(c.w,p.pm_id) : '尚未指派'} · 案件期限 {p.due_date || '未排定'}</p><label>節點<select value={node.key} onChange={e=>c.go({view:'project',project:p.id,tab:'people',node:e.target.value})}>{model.nodes.map(n=><option key={n.key} value={n.key}>{n.label}</option>)}</select></label><p>負責人 · {node.owners.map(o=>o.name).join('、') || '尚未指派'} · 節點期限 {node.finalDeadline?.slice(0,10) || '未排定'}</p><FlowSchedule key={node.key} project={p} node={node} session={c.s} onPublished={()=>void assignments.reload()}/>{local && <details><summary>案件角色與本地節點負責人</summary><ProjectRoleAssignment c={c} p={p} n={local}/></details>}</section>;
}
