import {useState} from 'react';
import {Button} from './design';
import {SopImportSheet} from './SopImportSheet';
import {SopEnrollmentStatus} from './SopEnrollment';
import type {useSopTasks} from './useSopTasks';
export function CaseSopStart({projectId,sop}:{projectId:string;sop:ReturnType<typeof useSopTasks>}) {
 const [open,setOpen]=useState(false);
 const data='data' in sop.state?sop.state.data:undefined;
 const reason=sop.state.kind==='loading'?'正在讀取 SOP':sop.state.kind==='error'?'讀取失敗，請重試':sop.state.kind==='forbidden'?'需由案件 PM 或管理者啟動':!data?.allowed.import?'任務寫入尚未開放或無啟動權限':'';
 if(!open&&data?.tasks.some(t=>!t.manual))return null;
 return <div className="nw-start">
  {data?.enrollment?.canOptIn && !data.allowed.import ? <SopEnrollmentStatus projectId={projectId} enrollment={data.enrollment} current={sop.current} reload={sop.reload} startLabel="啟動 SOP"/> : <Button variant="primary" disabled={!!reason} disabledReason={reason} onClick={()=>setOpen(true)}>啟動 SOP</Button>}
  {sop.state.kind==='error' && <Button onClick={()=>void sop.reload()}>重試 SOP</Button>}
  {open&&data&&<SopImportSheet projectId={projectId} startNode="sales" onApplied={sop.reload} onClose={()=>setOpen(false)} onOpenImported={()=>setOpen(false)}/>}
 </div>;
}
