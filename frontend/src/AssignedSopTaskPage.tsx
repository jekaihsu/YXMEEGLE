import {canOperateTestTasks} from './sopTaskModel';
import {Button,Skeleton} from './design';
import {SopTaskInspector} from './SopTaskInspector';
import {useSopTasks} from './useSopTasks';
import type {Ctx} from './appCommon';
import './SopTasks.css';
import './ProjectCalm.css';

export default function AssignedSopTaskPage({c}:{c:Ctx}){
 const sop=useSopTasks(c.route.project||'',c.s.workspace_id||'');
 const data='data' in sop.state?sop.state.data:undefined;
 const task=data?.tasks.find(t=>t.id===c.route.task);
 return <div className="project-detail project-detail-calm"><Button onClick={()=>c.go({view:'work'})}>返回我的工作</Button>
  {data&&<header><p>{data.caseHeader?.code}</p><h1>{data.caseHeader?.name||'SOP 任務'}</h1></header>}
  {sop.state.kind==='loading'&&<div aria-busy="true"><p role="status">正在讀取你的 SOP 任務…</p><Skeleton lines={3} height="3rem"/></div>}
  {sop.state.kind==='error'&&<div role="alert" className="pg-callout">{sop.state.message}<Button onClick={()=>void sop.reload()}>重試</Button></div>}
  {(sop.state.kind==='forbidden'||data&&!task)&&<p role="alert">找不到此 SOP 任務或沒有讀取權限</p>}
  {task&&data&&<SopTaskInspector key={task.id} task={task} project={{id:data.projectId}} users={[]} sop={sop} testOperator={canOperateTestTasks(c.s.user)} onClose={()=>c.go({view:'work'})}/>}
 </div>;
}
