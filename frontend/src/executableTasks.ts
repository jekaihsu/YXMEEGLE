// The one Home rule (backend/shell.py home_executable mirrors it): a task counts toward Home overdue / due-today /
// attention only when it is assigned to the viewer (can_execute), its case is not paused for execution, and it is open.
// Source deadlines on paused or unassigned template tasks are kept as data but never shown as the viewer's lateness.
import type {Task,Workspace} from './types';

const CLOSED=['completed','superseded'];
const day=(v:string|null|undefined)=>(v||'').slice(0,10);
export const isHomeExecutable=(t:Task,p:object)=>t.can_execute===true&&(p as {execution_status?:string}).execution_status!=='paused'&&!CLOSED.includes(t.status);
export const isHomeLate=(t:Task,asOf:string)=>!!t.due_date&&day(t.due_date)<day(asOf);
export const isHomeDueToday=(t:Task,asOf:string)=>!!t.due_date&&day(t.due_date)===day(asOf);
/** Overdue count shown by the sidebar badge: the shell's server count, or the same rule over the full workspace. */
export const homeOverdueCount=(w:Workspace)=>w.scope==='shell'&&w.counts?w.counts.my_overdue_tasks:w.projects.reduce((n,p)=>n+(p.nodes||[]).reduce((m,node)=>m+node.tasks.filter(t=>isHomeExecutable(t,p)&&isHomeLate(t,w.as_of)).length,0),0);
