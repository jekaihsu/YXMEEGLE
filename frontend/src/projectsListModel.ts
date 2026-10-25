import type {Project, User} from './types';
import {buildFlowModel, type FlowNode} from './flowModel';
import {compareTableValues, tableCalendarDay} from './companyDashboardCache';

export type PortfolioNode = {key:string;status:string;owner_id:string|null;collaborator_ids:string[]};
export type PortfolioProject = Project & {duplicate_count?:number;source_removed_at?:string;portfolio_nodes?:PortfolioNode[];sop_summary?:{policy:string|null;imported_tasks:boolean}};
export type PortfolioPage = {items:PortfolioProject[];total:number;hidden_duplicates?:number;hidden_removed?:number;source_synced_at?:string;as_of:string;basis:string};
export type CaseState = '進行中'|'待審核'|'尚未開始'|'已完成'|'待核對'|'暫停';
export type CaseRow = {project:PortfolioProject;nodes:FlowNode[];current:FlowNode|undefined;state:CaseState;mine:boolean;sop:boolean|null};
export type GroupKey = 'pinned'|'mine'|'sop'|'notStarted'|'done'|'other';
export const GROUPS = [
 {key:'pinned',label:'已釘選'}, {key:'mine',label:'我的案件'}, {key:'sop',label:'SOP 進行中'},
 {key:'notStarted',label:'尚未開始'}, {key:'done',label:'已完成'}, {key:'other',label:'其他案件'},
] satisfies {key:GroupKey;label:string}[];
export type CaseFilters = {q:string;client:string;owner:string;node:string;state:string;kind:string;attention:boolean;sort:string;direction:number};
export const DEFAULT_FILTERS:CaseFilters = {q:'',client:'',owner:'',node:'',state:'',kind:'',attention:false,sort:'due',direction:1};
const finished = (n:FlowNode) => ['已完成','略過'].includes(n.state);
export function currentNode(nodes:FlowNode[]):{current:FlowNode|undefined;state:CaseState} {
 if(!nodes.length)return {current:undefined,state:'待核對'};
 if(nodes.every(finished))return {current:undefined,state:'已完成'};
 const current=nodes.find(n=>!finished(n));
 if(!current || nodes.some(n=>!['已完成','略過','未開始','待處理','進行中','待審核','暫停'].includes(n.state)))return {current:undefined,state:'待核對'};
 if(nodes.every(n=>['未開始','待處理'].includes(n.state)))return {current,state:'尚未開始'};
 return {current,state:current.state==='待審核'?'待審核':current.state==='暫停'?'暫停':'進行中'};
}
export function caseRow(project:PortfolioProject,users:User[],viewer:string,today:string):CaseRow {
 const source=project.portfolio_nodes;
 const local=source ? {...project,nodes:source.map(n=>({id:n.key,name:n.key,key:n.key,status:n.status,owner_id:n.owner_id||'',collaborator_ids:n.collaborator_ids,start_date:null,due_date:null,original_due_date:null,started_at:null,completed_at:null,tasks:[]}))} : {...project,nodes:project.nodes||[]};
 const nodes=buildFlowModel({project:local,users,today}).nodes.map(n=>n.legacy?.status==='paused'?{...n,state:'暫停'}:n);
 const {current,state}=currentNode(nodes);
 const mine=!!viewer && (project.pm_id===viewer || project.owner_id===viewer ||
  Array.isArray(project.collaborator_ids)&&project.collaborator_ids.includes(viewer) ||
  current?.legacy?.collaborator_ids?.includes(viewer)===true || current?.owners.some(p=>p.open_id===viewer)===true);
 const sop=project.sop_summary ? project.sop_summary.policy==='managed' || project.sop_summary.imported_tasks===true : null;
 return {project,nodes,current,state,mine,sop};
}
export function groupKey(row:CaseRow,pins:ReadonlySet<string>):GroupKey {
 // Precedence is exclusive. Closed and unstarted cases retain their lifecycle group, even when owned or managed.
 if(pins.has(row.project.id))return 'pinned';
 if(row.state==='已完成')return 'done';
 if(row.state==='尚未開始')return 'notStarted';
 if(row.mine)return 'mine';
 if(row.sop)return 'sop';
 return 'other';
}
export function groupRows(rows:CaseRow[],pins:ReadonlySet<string>) {
 return GROUPS.map(group=>({...group,rows:rows.filter(row=>groupKey(row,pins)===group.key)}));
}
export function portfolioCounts(rows:CaseRow[]) {
 const unknown=rows.some(r=>r.state==='待核對');
 return {all:rows.length,active:unknown?null:rows.filter(r=>['進行中','待審核','暫停'].includes(r.state)).length,
  sop:rows.some(r=>r.state!=='已完成'&&(r.sop===null||r.sop&&r.state==='待核對'))?null:rows.filter(r=>r.sop&&r.state!=='已完成').length,done:unknown?null:rows.filter(r=>r.state==='已完成').length};
}
export function caseAttention(p:Project,today:string) {
 const due=tableCalendarDay(p.due_date),date=tableCalendarDay(today);
 const days=due&&date?(Date.parse(due)-Date.parse(date))/86400000:Infinity;
 const tasks=(p.nodes||[]).flatMap(n=>n.tasks||[]).filter(t=>!['completed','superseded','approved_skipped'].includes(t.status));
 const closed=(p.execution_status||p.status)==='completed';
 return {late:!closed&&(Number(p.overdue_tasks)>0 || days<0 || tasks.some(t=>t.due_date&&t.due_date.slice(0,10)<today.slice(0,10))),
  soon:!closed&&days>=0&&days<=7,blocked:['paused','blocked'].includes(p.execution_status||p.status)||tasks.some(t=>['paused','blocked'].includes(t.status))};
}
export function filterRows(rows:CaseRow[],f:CaseFilters,today:string) {
 const filtered=rows.filter(r=>{const p=r.project;return `${p.code} ${p.name} ${p.client}`.toLocaleLowerCase().includes(f.q.trim().toLocaleLowerCase()) &&
  (!f.client||p.client===f.client)&&(!f.owner||p.pm_id===f.owner)&&(!f.node||(f.node==='unknown'?r.state==='待核對':r.current?.key===f.node))&&
  (!f.state||r.state===f.state)&&(!f.kind||(f.kind==='formal'?p.case_type!=='intake':p.case_type==='intake'))&&
  (!f.attention||Object.values(caseAttention(p,today)).some(Boolean));});
 return filtered.sort((a,b)=>{
  const dir=f.direction===1?'asc':'desc';
  const urgency=f.sort==='due'?Number(caseAttention(b.project,today).late)-Number(caseAttention(a.project,today).late):0;
  const field=f.sort==='name'?'name':f.sort==='created'?'created_at':'due_date';
  return urgency||compareTableValues(a.project[field],b.project[field],f.sort==='name'?'text':'date',dir)||compareTableValues(a.project.code,b.project.code,'text')||a.project.id.localeCompare(b.project.id);
 });
}
export const pinStorageKey=(workspace:string,viewer:string)=>`yx.projects.pins.v1:${encodeURIComponent(workspace)}:${encodeURIComponent(viewer)}`;
export function readPins(storage:Pick<Storage,'getItem'>,key:string):string[] {
 try{const value:unknown=JSON.parse(storage.getItem(key)||'[]');return Array.isArray(value)?[...new Set(value.filter((id):id is string=>typeof id==='string'))]:[]}catch{return []}
}
export function writePins(storage:Pick<Storage,'setItem'>,key:string,pins:string[]):boolean {
 try{storage.setItem(key,JSON.stringify([...new Set(pins)]));return true}catch{return false}
}
export function verification(p:Project) {
 return p.source_lifecycle?.reasons?.includes('conflict')?'不一致':p.source_lifecycle?.state==='mapped'&&p.source_lifecycle.canonical&&!p.source_lifecycle.reasons?.length?'已驗證':'來源待確認';
}
