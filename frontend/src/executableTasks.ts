// Assignment controls visibility. Execution authority and current readiness
// control personal urgency counts; retained source dates stay visible on waiting work.
import type {Task,Workspace} from './types';

const day=(v:string|null|undefined)=>(v||'').slice(0,10);
/** Assignment is a visibility fact. Business override alone does not make a coworker's task mine. */
/** Only the server projection may certify a proxy assignment. */
export const isHomeAssigned=(t:Task,_w:Workspace,viewerId:string)=>typeof t.assigned_to_viewer==='boolean'?t.assigned_to_viewer:!!viewerId&&t.owner_id===viewerId;
export const isHomeProxy=(t:Task,w:Workspace,viewerId:string)=>t.owner_id!==viewerId&&isHomeAssigned(t,w,viewerId);
export const isHomeExecutable=(t:Task,p:object,asOf?:string)=>{
 if(typeof t.home_detail?.actionable==='boolean')return t.home_detail.actionable;
 const project=p as {execution_status?:string;execution_allowed?:boolean;case_type?:string};
 return t.can_execute===true&&project.execution_status!=='paused'&&project.execution_allowed!==false&&project.case_type!=='intake'&&
  ['pending','in_progress','rework'].includes(t.status)&&!t.execution_blockers?.length&&
  (t.status!=='pending'||!t.activation_blockers?.length)&&(!asOf||!t.start_date||day(t.start_date)<=day(asOf));
};
export const isHomeLate=(t:Task,asOf:string)=>!!t.due_date&&day(t.due_date)<day(asOf);
export const isHomeDueToday=(t:Task,asOf:string)=>!!t.due_date&&day(t.due_date)===day(asOf);
/** Overdue count shown by the sidebar badge: the shell's server count, or the same rule over the full workspace. */
export const homeOverdueCount=(w:Workspace,viewerId?:string)=>w.scope==='shell'&&w.counts?w.counts.my_overdue_tasks:w.projects.reduce((n,p)=>n+(p.nodes||[]).reduce((m,node)=>m+node.tasks.filter(t=>(!viewerId||isHomeAssigned(t,w,viewerId))&&isHomeExecutable(t,p,w.as_of)&&isHomeLate(t,w.as_of)).length,0),0);
