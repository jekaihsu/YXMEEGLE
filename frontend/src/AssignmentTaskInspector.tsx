import {Badge} from './design';
import {TaskDrawer,DrawerFacts} from './TaskDrawer';
import {TASK_STATUS_OPTIONS,type AssignmentTask,type AssignmentMutation,type AssignablePerson} from './nodeAssignmentApi';
import {InlineTaskEditor} from './InlineTaskEditor';
import {editorFields,type TaskDraft} from './nodeWorkbenchModel';
import type {ProductionPlan} from './productionPlan';
import {ProductionPlanFacts} from './FlowEvidence';
export function AssignmentTaskInspector({assignment:task,people=[],plan,nodeLabel,nodeKey,busy,reason,mutate,onClose}:{assignment:AssignmentTask;people?:AssignablePerson[];plan?:ProductionPlan|null;nodeLabel:string;nodeKey:string;busy:boolean;reason:string;mutate:(m:AssignmentMutation)=>Promise<boolean>;onClose:()=>void}){
 const generated=(line:string)=>/^(依計畫數量完成|計畫數量[：:]|合約明細[：:]|工項連結[：:]|\[SOP-START:)/.test(line);
 const notes=plan?task.detail.split('\n').filter(line=>!generated(line)).join('\n').trim():task.detail;
 const draft={title:task.title,assignee:task.assignee?.open_id || '',due:task.deadline || '',notes,status:task.status,reason:''};
 const save=(value:TaskDraft)=>{
  const patch:Extract<AssignmentMutation,{action:'update_task'}>['patch']={};
  if(value.title!==draft.title)patch.title=value.title.trim();
  if(value.assignee!==draft.assignee)patch.assignee_open_id=value.assignee || null;
  if(value.due!==draft.due)patch.deadline=value.due || null;
  if(value.notes!==draft.notes)patch.detail=plan?[...task.detail.split('\n').filter(generated),value.notes].join('\n'):value.notes;
  if(value.status!==draft.status)patch.status=value.status;
  return mutate({action:'update_task',nodeKey,taskId:task.id,expected_revision:task.revision,patch});
 };
 return <TaskDrawer kind="lark" label={task.title} trail={[nodeLabel,'Lark 任務']} title={plan?'依計畫數量完成':task.title} status={<Badge>{task.status}</Badge>} onClose={onClose}><div className="assignment-edit"><DrawerFacts facts={[{label:'負責人',value:task.assignee?.name || '尚未指派'},{label:'期限',value:task.deadline || '未排期限'},{label:'指派人',value:task.assigned_by?.name || '來源未提供'},{label:'完成時間',value:task.done_at || '未完成'}]}/>
  <InlineTaskEditor busy={busy} model={{draft,fields:editorFields({title:task.can.edit_details,assignee:task.can.assign,due:task.can.edit_details,notes:task.can.edit_details,status:task.can.edit_status || task.can.cancel},reason || '需有此任務的編輯權限'),people:people.map(p=>({id:p.open_id,name:p.name})),statuses:TASK_STATUS_OPTIONS.filter(([value])=>value===task.status || (value==='取消' ? task.can.cancel : task.can.edit_status)).map(([id,label])=>({id,label})),maxTitle:200,maxNotes:2000,dueReason:false}} onSave={save}/>
  {plan && <ProductionPlanFacts plan={plan}/>}<details className="sop-source"><summary>來源</summary><p>record {task.record_id}</p><p>建立 {task.created_at || '來源未提供'}</p></details></div></TaskDrawer>;
}
