import {DataState} from './design/DataState';
import {taipeiTime} from './taipeiTime';
import {DetailRefreshProvider} from './detailRefresh';
import {canOperateTestTasks} from './sopTaskModel';
import {Button,Skeleton} from './design';
import {SopTaskInspector} from './SopTaskInspector';
import {useSopTasks} from './useSopTasks';
import type {Ctx} from './appCommon';
import './SopTasks.css';
import './ProjectCalm.css';

export default function AssignedSopTaskPage({c}:{c:Ctx}){return <DetailRefreshProvider scope={c.s.workspace_id||''} identityFingerprint={JSON.stringify([c.s.user?.id,c.s.user?.authz_version,c.s.user?.capabilities])}><AssignedSopTaskContent c={c}/></DetailRefreshProvider>}
function AssignedSopTaskContent({c}:{c:Ctx}){
 const sop=useSopTasks(c.route.project||'',c.s.workspace_id||'');
 const data='data' in sop.state?sop.state.data:undefined;
 const task=data?.tasks.find(t=>t.id===c.route.task);
 const leave=()=>window.history.length>1?window.history.back():c.go({view:'work'});
 return <div className="project-detail project-detail-calm"><Button onClick={leave}>返回</Button>
  {data&&<p>資料時間：{taipeiTime(sop.dataTime,'待核對')}</p>}{data&&<header><p>{data.caseHeader?.code}</p><h1>{data.caseHeader?.name||'SOP 任務'}</h1></header>}
  {sop.state.kind==='loading'&&<div aria-busy="true"><p role="status">正在讀取你的 SOP 任務…</p><Skeleton lines={3} height="3rem"/></div>}
  {sop.state.kind==='error'&&(sop.state.retrying
   ?<div role="status" aria-busy="true" className="pg-callout">正在重新讀取 SOP 任務，不會變更任何資料…<Button disabled>重新讀取中…</Button></div>
   :<div role="alert" className="pg-callout">{sop.state.message}<Button onClick={()=>void sop.reload(true,true)}>重試</Button></div>)}
  {(sop.state.kind==='forbidden'||data&&!task)&&<DataState kind="Denied" title="目前無法開啟 SOP 任務" body="找不到此任務或沒有讀取權限。請回工作清單確認。"/>}
  {task&&data&&<SopTaskInspector key={task.id} task={task} project={{id:data.projectId}} users={[]} sop={sop} testOperator={canOperateTestTasks(c.s.user)} onClose={leave}/>}
 </div>;
}
