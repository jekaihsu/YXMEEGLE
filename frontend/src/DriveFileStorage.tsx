import type {Project,Workspace,Session} from './types';
type Context={w:Workspace;s:Session;busy:boolean;refresh:()=>Promise<void>};
export function DriveFileStorage({c,file}:{c:Context;p:Project;file:any}){
 if(file.storage!=='local'||file.withdrawn)return null;
 return <div className="file-storage-actions">{!file.remote_status&&<small>{file.auto_store_requested?'保存狀態待更新，請查看背景工作回執。':'既有檔案尚無自動保存回執，請由管理員核對保存工作。'}</small>}{['queued','running','retry'].includes(file.remote_status)&&<><small>上傳後已自動安排 Drive 保存，無須再次送出。</small><button className="text-button" disabled={c.busy} onClick={()=>void c.refresh()}>更新保存狀態</button></>}{['failed','blocked','outcome_unknown'].includes(file.remote_status)&&<small>請先核對背景工作及遠端回執，避免重複保存。<a href="#view=admin&tab=jobs">查看背景工作</a></small>}</div>;
}
