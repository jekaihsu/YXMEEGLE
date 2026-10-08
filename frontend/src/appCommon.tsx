import {StatusBadge,Skeleton,type StatusKind} from './design';
import {useEffect, useState, type MouseEvent, type ReactNode} from 'react';
import {ChevronRight, Circle, CircleCheck, CircleDot, FolderOpen, Loader2, Pause, TriangleAlert, X} from 'lucide-react';
import {useViewData} from './viewData';
import {api, perfMark, getSessionEpoch} from './api';
import {useDialogFocus} from './useDialogFocus';
import {Avatar} from './AppShell';
import {type DraftScope} from './useDraftNavigationGuard';
import {lifecycleGate} from './sourceLifecycle';
import {type Node, type Project, type Route, type Session, type Task, type Workspace, type Freshness, type LiveDataset} from './types';

export type ReadVersion={version:number;project_versions:Record<string,number>};
export type ActionScope={project_id?:string;node_id?:string;task_id?:string};
export type Ctx={w:Workspace;s:Session;busy:boolean;error:string;registerDrafts:(scope:DraftScope|null)=>void;onFreshness?:(freshness:Freshness)=>void;onRefreshError?:(datasets:LiveDataset[])=>void;reloadVersion?:number;route:Route;go:(r:Route)=>void;run:(action:string,payload?:Record<string,unknown>,scope?:ActionScope,readVersion?:ReadVersion)=>Promise<Workspace|undefined>;refresh:()=>Promise<void>;notify:(m:string)=>void;upload:(form:FormData,readVersion?:ReadVersion)=>Promise<boolean>};
export type ProjectPage={total:number;offset:number;limit:number;facets:{all:number;formal:number;intake:number};items:Project[]};
export type ProjectSlice={scope:'project';version:number;project:Project;[key:string]:any};
export type TaskRow={p:Project;n:Node;t:Task};
export const STATUS:Record<string,string>={approved_skipped:'核准跳過',engineering_complete:'工程完成、財務待結',internal:'內部案',source_conflict:'來源待核對',pending:'尚未開始',in_progress:'進行中',completed:'已完成',paused:'暫停中',superseded:'舊版留存',rework:'退回修正',draft:'草稿',approved:'已核准',executed:'已套用',rejected:'已駁回',withdrawn:'已撤回',active:'進行中',ongoing:'進行中'};
export const NODE_NAMES:Record<string,string>={sales:'業務',pm:'PM',confirmation:'確認單',field:'外業',control:'控制',mapping:'圖資',report:'報告',pricing:'計價',settlement:'結算'};
export const SOURCE_KINDS:Record<string,string>={quote:'報價資料',quote_confirmation:'報價確認單',daily:'日報紀錄',case:'案件資料',work:'工作單',confirmation:'工程確認單',contract:'合約明細',reporting:'填報工項',cost:'成本單'};
export const ACTION_NAMES:Record<string,string>={node_skip_create:'建立節點跳過草稿',node_skip_submit:'送出節點跳過審批',node_skip_vote:'確認節點跳過申請',node_skip_apply:'套用核准跳過',node_skip_withdraw:'撤回節點跳過申請',task_start:'開始作業',task_complete:'完成任務並交付成果',task_return:'退回任務修正',task_update:'更新任務指派與排程',task_add:'新增任務',node_complete:'送交節點確認',participants_update:'更新案件參與人員',comment_add:'新增評論',file_link:'加入檔案連結',approval_create:'建立審批草稿',approval_submit:'送出審批',approval_confirm:'完成審批確認',approval_lark:'更新示範審批結果',approval_execute:'套用已核准的調整',approval_withdraw:'撤回申請',change_resume:'恢復受影響工項',calendar_update:'更新工作日設定',demo_reset:'還原示範工作區'};
export const eventMessage=(e:{action?:string;message?:string})=>e.message&&e.message!==e.action?e.message:ACTION_NAMES[e.action||'']||e.action||'更新紀錄';
export const date=(value?:string|null)=>value?value.slice(0,10).replaceAll('-','/'):'未排定';
export const shortDate=(value?:string|null)=>value?value.slice(5,10).replace('-','/'):'—';
export const stamp=(value?:string|null)=>value?`${date(value)} ${value.includes('T')?new Date(value).toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'}):''}`:'—';
export const num=(value?:number|null)=>value==null?'—':value.toLocaleString('zh-TW',{maximumFractionDigits:2});
export const money=(value?:number|null)=>value==null?'待帶入':`NT$ ${num(value)}`;
export const unmatchedDaily=(w:Workspace)=>w.scope==='shell'&&w.counts?w.counts.daily_unmatched:w.source_status.mapping?.daily_unmatched??(Array.isArray(w.daily_unmatched)?w.daily_unmatched.length:0);
export const active=(t:Task)=>!['completed','superseded'].includes(t.status);
export const allTasks=(w:Workspace):TaskRow[]=>w.projects.flatMap(p=>(p.nodes||[]).flatMap(n=>n.tasks.map(t=>({p,n,t}))));
export const isLate=(t:{due_date:string|null;status:string},now:string)=>!!t.due_date&&t.due_date.slice(0,10)<now.slice(0,10)&&!['completed','superseded'].includes(t.status);
export const progress=(p:Project)=>{const ts=p.nodes.flatMap(n=>n.tasks).filter(t=>t.status!=='superseded');return ts.length?Math.round(ts.filter(t=>t.status==='completed').length/ts.length*100):0};
export const elapsed=(start:string|null|undefined,end:string|null|undefined)=>start&&end?Math.max(0,Math.floor((new Date(end).getTime()-new Date(start).getTime())/86400000)):0;
export const nameOf=(w:Workspace,id?:string)=>w.users.find(u=>u.id===id)?.name||'尚未指派';
export const isLead=(s:Session)=>['pm','manager'].includes(s.user?.role||'');
export const isProjectLead=(s:Session,p:Project)=>s.user?.role==='manager'||[p.pm_id,p.supervisor_id].includes(s.user?.id||'');
export const isTaskActor=(t:Task,_c:Ctx)=>t.can_execute===true;
export const safeUrl=(value?:string)=>value&&/^https?:\/\//i.test(value)?value:undefined;
export function Badge({status,label,kind}:{status:string;label?:string;kind?:StatusKind}){return <StatusBadge kind={kind||(status==='source_conflict'?'verification':'workflow')} state={status}>{label||STATUS[status]||status}</StatusBadge>}
export function Empty({title='目前沒有資料',detail,icon=<FolderOpen/>}:{title?:string;detail?:string;icon?:ReactNode}){return <div className="empty"><span>{icon}</span><h3>{title}</h3>{detail&&<p>{detail}</p>}</div>}
export function Modal({title,subtitle,children,onClose,wide=false}:{title:string;subtitle?:string;children:ReactNode;onClose:()=>void;wide?:boolean}){const dialogRef=useDialogFocus(onClose);return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><section ref={dialogRef} tabIndex={-1} className={`modal ${wide?'wide':''}`} role="dialog" aria-modal="true" aria-label={title}><header><div><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><button className="icon-button" onClick={onClose} aria-label="關閉"><X size={19}/></button></header>{children}</section></div>}
export function Field({label,children,hint}:{label:string;children:ReactNode;hint?:string}){return <label className="form-field"><span>{label}</span>{children}{hint&&<small>{hint}</small>}</label>}
export function OwnerSelect({w,value,onChange,name,disabled=false}:{w:Workspace;value?:string;onChange?:(s:string)=>void;name?:string;disabled?:boolean}){
 const[localValue,setLocalValue]=useState(value||'');const selected=onChange?(value||''):localValue;
 return <>{name&&<input type="hidden" name={name} value={selected} disabled={disabled}/>}<select aria-label="選擇負責人" value={selected} onChange={e=>{setLocalValue(e.target.value);onChange?.(e.target.value)}} disabled={disabled}><option value="">尚未指派</option>{w.users.filter(u=>u.active!==false||u.id===selected).map(u=><option key={u.id} value={u.id} disabled={u.active===false}>{u.name} · {u.department}{u.active===false?'（已停用，保留歷史指派）':''}</option>)}</select></>
}
export function Primary({children,busy,disabled,...rest}:{children:ReactNode;busy?:boolean;disabled?:boolean;onClick?:(e:MouseEvent<HTMLButtonElement>)=>void;type?:'button'|'submit'}){return <button className="button primary" disabled={disabled||busy} {...rest}>{busy?<Loader2 className="spin" size={15}/>:null}{children}</button>}
export function PageHead({eyebrow,title,subtitle,children}:{eyebrow:string;title:string;subtitle?:string;children?:ReactNode}){return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{subtitle&&<p>{subtitle}</p>}</div><div className="heading-actions">{children}</div></div>}
export function openTask(c:Ctx,row:TaskRow){c.go({view:'project',project:row.p.id,node:row.n.id,task:row.t.id,tab:'flow'})}
export function taskReadiness(r:TaskRow,c:Ctx){
 {const g=lifecycleGate(r.p);if(g)return g;}
 if(r.t.status==='paused')return '待設計變更審批';
 if(!isTaskActor(r.t,c))return `待 ${nameOf(c.w,r.t.owner_id)} 處理`;
 if(!['pending','in_progress','rework'].includes(r.t.status))return '查看目前狀態';
 if((r.t.input_task_ids as string[]|undefined)?.some(id=>!r.p.nodes.some(n=>n.tasks.some(t=>t.id===id&&t.status==='completed'&&!!t.output))))return '待前置成果交付';
 if(r.n.key==='field'){const permit=[...(r.p.evidence||[])].reverse().find((e:{node_id:string;key:string;withdrawn?:boolean})=>e.node_id===r.n.id&&e.key==='permits'&&!e.withdrawn);if(!permit||!['accepted','not_applicable'].includes(permit.status))return '待公務證明核准'}
 return '';
}
export function openGuidedTask(c:Ctx,r:TaskRow){c.go({view:'project',project:r.p.id,node:r.n.id,tab:'flow',completion:r.n.id,focus:r.t.id})}
export function EventList({c,project,limit=20}:{c:Ctx;project?:string;limit?:number}){const events=[...c.w.events].filter(e=>!project||e.project_id===project).sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,limit);return events.length?<div className="event-list">{events.map(e=><div className="event" key={e.id}><span className="event-dot"/><div><p><strong>{nameOf(c.w,e.actor_id)}</strong> {eventMessage(e)}</p><small>{c.w.projects.find(p=>p.id===e.project_id)?.code} · {stamp(e.created_at)}</small></div></div>)}</div>:<Empty title="尚無操作紀錄" detail="任務、參與人員及審批的操作會記錄在這裡。"/>}
export function TaskTable({rows,c,showProject=true,comfortable=false}:{rows:TaskRow[];c:Ctx;showProject?:boolean;comfortable?:boolean}){
 if(!comfortable)return <div className="table-scroll"><table aria-label="任務清單" className={`data-table task-table${showProject?' with-project':''}`}><thead><tr><th scope="col">任務</th>{showProject&&<th scope="col">案件 / 節點</th>}<th scope="col">負責人</th><th scope="col">狀態</th><th scope="col">排程</th><th scope="col">營業額點數</th><th scope="col"/></tr></thead><tbody>{rows.map(r=><tr key={r.t.id} className={`clickable ${r.t.status==='superseded'?'superseded-row':''}`} onClick={()=>openTask(c,r)}><td><div className="task-title"><TaskIcon status={r.t.status}/><div><button className="text-button" onClick={e=>{e.stopPropagation();openTask(c,r)}}>{r.t.title}</button><small>{r.t.required?'必做 SOP':'增補任務'}{r.t.revision>1?` · v${r.t.revision}`:''}</small></div></div></td>{showProject&&<td><span className="mono">{r.p.code}</span><small>{NODE_NAMES[r.n.key]||r.n.name}</small></td>}<td><span className="person-cell"><Avatar small user={c.w.users.find(u=>u.id===r.t.owner_id)}/>{nameOf(c.w,r.t.owner_id)}</span></td><td><Badge status={r.t.status}/></td><td><span className={`mono ${isLate(r.t,c.w.as_of)?'late-text':''}`}>{shortDate(r.t.start_date)} → {shortDate(r.t.due_date)}</span>{isLate(r.t,c.w.as_of)&&<small className="late-text">逾期 {elapsed(r.t.due_date,c.w.as_of)} 天</small>}</td><td className="mono">{num(r.t.points)} <span className="muted">點</span></td><td><ChevronRight size={16} className="muted"/></td></tr>)}</tbody></table>{!rows.length&&<Empty title="目前沒有符合的任務" detail="調整篩選條件，或從案件節點新增任務。"/>}</div>
 const showOwner=rows.some(r=>r.t.owner_id!==c.s.user?.id);
 const showPoints=rows.some(r=>r.t.points!=null);
 return <div className="table-scroll"><table aria-label="任務清單" className="data-table comfortable-tasks"><thead><tr><th scope="col">任務</th>{showProject&&<th scope="col">案件 / 節點</th>}{showOwner&&<th scope="col">負責人</th>}<th scope="col">狀態</th><th scope="col">有效期限</th>{showPoints&&<th scope="col">營業額點數</th>}</tr></thead><tbody>{rows.map(r=><tr key={r.t.id}><td className="work-task"><div className="task-title"><TaskIcon status={r.t.status}/><button className="text-button" title={r.t.title} onClick={()=>openTask(c,r)}>{r.t.title}</button></div></td>{showProject&&<td className="work-project"><span className="mono">{r.p.code}</span> · {NODE_NAMES[r.n.key]||r.n.name}</td>}{showOwner&&<td className="work-owner">{r.t.owner_id===c.s.user?.id?'本人':nameOf(c.w,r.t.owner_id)}</td>}<td className="work-status"><Badge status={r.t.status}/></td><td className={`work-due mono ${isLate(r.t,c.w.as_of)?'late-text':''}`}>{date(r.t.due_date)}</td>{showPoints&&<td className="work-points mono">{r.t.points==null?'—':`${num(r.t.points)} 點`}</td>}</tr>)}</tbody></table>{!rows.length&&<Empty title="目前沒有符合的任務" detail="調整篩選條件，或從案件節點新增任務。"/>}</div>
}
export function TaskIcon({status}:{status:string}){return status==='completed'?<CircleCheck size={18} className="complete-icon"/>:status==='paused'?<Pause size={18} className="paused-icon"/>:status==='in_progress'?<CircleDot size={18} className="accent-text"/>:<Circle size={18} className="muted"/>}
// Screens that still need tasks, schedules or approvals across cases read the full workspace, but only once the user opens them.
// The result is shared per session epoch and shell version, so a mutation or a newer shell never reuses an older copy.
export const fullReads=new Map<string,Promise<Workspace>>();
export function readFullWorkspace(version:number,generation=0,asOf='',authority=''){
 const key=`${getSessionEpoch()}:${version}:${generation}:${asOf}:${authority}`;
 for(const old of fullReads.keys())if(old!==key)fullReads.delete(old);
 let read=fullReads.get(key);
 if(!read){read=api<Workspace>('/api/workspace');fullReads.set(key,read);read.catch(()=>{if(fullReads.get(key)===read)fullReads.delete(key)})}
 return read;
}
export function FullWorkspaceGate({c,children}:{c:Ctx;children:(c:Ctx)=>ReactNode}){
 const shell=c.w.scope==='shell';
 const generation=c.reloadVersion??0;const authority=JSON.stringify(c.s.user);const asOf=c.w.as_of;
 const full=useViewData<Workspace|undefined>(shell?`full:${c.w.version}:${generation}:${asOf}:${authority}`:'full-loaded',(_signal,current)=>shell?readFullWorkspace(c.w.version,generation,asOf,authority).then(data=>{if(!current())throw new DOMException('stale','AbortError');return data}):Promise.resolve(undefined),[]);
 useEffect(()=>{if(shell&&full.data)perfMark('full-workspace-render')},[shell,full.data]);
 if(!shell)return <>{children(c)}</>;
 if(full.data)return <>{children({...c,w:{...full.data,freshness:c.w.freshness}})}</>;
 return full.error?<div className="error-banner" role="alert"><TriangleAlert size={18}/><span>{full.error}</span><button className="text-button" onClick={full.reload}>重試</button></div>:<div role="status"><p className="co-loading">正在讀取工作資料…</p><Skeleton lines={4}/></div>;
}
