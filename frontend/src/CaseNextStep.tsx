import {Button,Skeleton} from './design';
import type {FlowNode} from './flowModel';
import type {OverviewAction,OverviewTarget} from './projectOverviewModel';
export function CaseNextStep({nodes,action,loading,stale,current,onOpen,error='' }:{nodes:FlowNode[];action:OverviewAction;loading:boolean;stale:boolean;current:string;error?:string;onOpen:(target:OverviewTarget)=>void}){
 const node=nodes.find(n=>n.key===current);
 const unfinished=nodes.find(n=>(n.assignment||n.legacy)&&!['已完成','略過'].includes(n.state));
 const stuck=unfinished||node;
 const remaining=stuck?Math.max(0,stuck.tasks.total-stuck.tasks.done):0;
 const reason=action.kind==='blocking'&&action.target.tab==='data'?action.reason:stuck?.state==='待審核'?'任務已送出，等待節點主管核准。':stuck?.state==='暫停'?'節點暫停中，請核對暫停原因。':stuck&&!stuck.owners.length?'此節點尚未指派負責人。':remaining?`尚有 ${remaining} 項任務未完成，完成後仍需主管核准節點。`:action.reason;
 return <section className="po-card po-next" aria-label="SOP 狀態與下一步" aria-busy={loading}>
  <h2>目前 SOP</h2>{error?<p role="alert">SOP 來源暫不可用，無法確認停留節點。{error}</p>:loading?<div role="status"><p>正在核對節點與任務…</p><Skeleton lines={3}/></div>:<>
   <p><strong>{stuck?`${stuck.label} · ${stuck.state}`:'流程尚未建立'}</strong>{stale&&' · 上次成功資料，待更新'}</p>
   <dl><div><dt>{unfinished?'停留節點':'流程狀態'}</dt><dd>{unfinished?unfinished.label:node?'節點皆已完成或略過':'尚無可核實的節點'}</dd></div><div><dt>原因</dt><dd>{reason}</dd></div><div><dt>下一步</dt><dd>{action.title}<small>負責人 · {action.owner}</small></dd></div></dl>
   <Button onClick={()=>onOpen(action.target)}>{action.button}</Button>
  </>}
 </section>;
}
