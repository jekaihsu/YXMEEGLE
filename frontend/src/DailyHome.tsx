import {useState, type ReactNode} from 'react';
import {ArrowRight, CalendarDays, ChevronRight, CircleCheck, Clock3, GitBranch} from 'lucide-react';
import {type Project} from './types';
import {Ctx,TaskRow,active,operationallyBlocked,isTaskActor,taskReadiness,openGuidedTask,allTasks,isLate,date,openTask,nameOf,elapsed,NODE_NAMES,STATUS,progress,Empty,unmatchedDaily,num,EventList,FullWorkspaceGate} from './appCommon';
import {Badge,Button,Page,Progress,Row} from './design';
import {isHomeAssigned,isHomeProxy,isHomeExecutable,isHomeLate,isHomeDueToday} from './executableTasks';
import './DailyHome.css';

type Item={key:string;title:string;detail:string;late?:number;today?:boolean;blocked?:boolean;icon:ReactNode;onClick:()=>void};

const uniqueRows=(rows:TaskRow[])=>{const seen=new Set<string>();return rows.filter(r=>{if(seen.has(r.t.id))return false;seen.add(r.t.id);return true})};

export function NextAction({c,rows}:{c:Ctx;rows:TaskRow[]}){
 const owned=rows.filter(r=>isHomeExecutable(r.t,r.p)&&r.p.case_type!=='intake'&&!taskReadiness(r,c)&&!taskExecutionReason(r,c)&&!futureStart(r,c.w.as_of));
 const ordered=[...owned].sort((a,b)=>(a.t.status==='in_progress'?-1:0)-(b.t.status==='in_progress'?-1:0)||(a.t.due_date||'9999').localeCompare(b.t.due_date||'9999'));
 const next=ordered.find(r=>!taskReadiness(r,c));const blocked=ordered.filter(r=>operationallyBlocked(r));
 if(!owned.length)return null;
 return <section className="dh-hero" aria-label="接續我的工作"><p className="dh-kicker">接續我的工作 · {owned.length} 項待處理</p>{next?<><h2>{next.t.title}</h2><p>{next.p.code} · {next.n.name} · {next.t.status==='in_progress'?'作業中，接著補齊成果':'檢視內容後，由你確認開始'}</p><Button variant="primary" onClick={()=>openGuidedTask(c,next)}>{next.t.status==='in_progress'?'繼續此任務':'前往此任務'}<ArrowRight size={17}/></Button></>:<><h2>先補齊條件，再接續作業</h2><p>你負責的任務目前仍有待處理條件。</p></>}{blocked.slice(0,2).map(r=><button key={r.t.id} type="button" className="dh-blocked" onClick={()=>openGuidedTask(c,r)}><span><Badge tone="critical">受阻</Badge> {r.t.title}<small>{r.p.code} · {r.n.name} · 待解除作業條件</small></span><span>查看處理方式<ArrowRight size={14}/></span></button>)}</section>
}

type WaitingKind='paused'|'correction'|'prerequisite'|'upcoming'|'proxy';
type WaitingItem={task_id:string;project_id:string;project_code:string;node_id:string;title:string;reason:string;kind:WaitingKind;original_due_date?:string|null;due_date?:string|null};
const futureStart=(r:TaskRow,asOf:string)=>!!r.t.start_date&&r.t.start_date.slice(0,10)>asOf.slice(0,10);
const taskExecutionReason=(r:TaskRow,c:Ctx)=>{
 if(r.p.execution_allowed===false)return r.p.execution_readonly_reason||'案件執行歸屬待核定';
 const blockers=r.t.status==='pending'&&r.t.activation_blockers?.length?r.t.activation_blockers:r.t.execution_blockers;
 return blockers?.[0]||'';
};
const waitingKind=(r:TaskRow,c:Ctx):WaitingKind|undefined=>{
 if(r.p.execution_status==='paused'||r.t.status==='paused')return 'paused';
 if(r.t.status==='rework')return 'correction';
 if(isHomeProxy(r.t,c.w,c.s.user?.id||''))return 'proxy';
 if(futureStart(r,c.w.as_of))return 'upcoming';
 if(r.t.can_execute!==true)return 'prerequisite';
 if(taskReadiness(r,c)||taskExecutionReason(r,c))return 'prerequisite';
 if(r.t.due_date&&r.t.due_date.slice(0,10)>c.w.as_of.slice(0,10))return 'upcoming';
 return undefined;
};
const waitingReason=(r:TaskRow,c:Ctx,kind:WaitingKind)=>kind==='paused'?(r.p.execution_status==='paused'?'案件暫停，原期限保留':'任務暫停，原期限保留'):
 kind==='correction'?'任務退回修正，需檢視待補內容':kind==='proxy'?(()=>{const d=(c.w.delegations||[]).find((x:{delegate_id:string;principal_id:string;task_ids:string[]})=>x.delegate_id===c.s.user?.id&&x.principal_id===r.t.owner_id&&x.task_ids?.includes(r.t.id));return `代理 ${nameOf(c.w,r.t.owner_id)}；${d?.start_date||'期間待核對'} 至 ${d?.end_date||'期間待核對'}；${d?.qualification_note||d?.source||'已核定代理'}${taskReadiness(r,c)?` · ${taskReadiness(r,c)}`:''}`})():
 kind==='upcoming'?r.t.start_date&&r.t.start_date.slice(0,10)>c.w.as_of.slice(0,10)?`排定 ${date(r.t.start_date)} 開始`:`預計 ${date(r.t.due_date)} 到期`:
 (r.t.can_execute!==true?'指派與執行資格待核對':taskExecutionReason(r,c)||taskReadiness(r,c)||'待前置條件完成');
const WAITING_LABELS:[WaitingKind,string][]=[['paused','暫停中的指派'],['correction','待修正'],['prerequisite','等待前置條件'],['upcoming','即將開始'],['proxy','代理工作']];
function WaitingWork({c,items,counts}:{c:Ctx;items:WaitingItem[];counts?:Partial<Record<WaitingKind,number>>}){
 return <>{WAITING_LABELS.map(([kind,label])=>{const rows=items.filter(i=>i.kind===kind),total=counts?.[kind]??rows.length;return total?<Group key={kind} title={label} count={total} className="dh-waiting">{rows.slice(0,5).map(i=><Row key={i.task_id} icon={<Clock3 size={20}/>} label={i.title} detail={`${i.project_code} · ${i.reason}${kind==='paused'&&i.original_due_date?` · 原期限 ${date(i.original_due_date)}`:''}`} onClick={()=>c.go({view:'project',project:i.project_id,node:i.node_id,task:i.task_id,tab:'flow'})}/>)}{total>rows.length&&<More onClick={()=>c.go({view:'work'})}>查看全部指派工作</More>}</Group>:null})}</>;
}

function Group({title,count,caption,className,hideTitle=false,children}:{title:string;count?:number;caption?:string;className?:string;hideTitle?:boolean;children:ReactNode}){
 const heading=<h2>{title}{count!=null&&<span className="heading-count">{count}</span>}{caption&&<small>{caption}</small>}</h2>;
 return <section aria-label={hideTitle?title:undefined} className={`ds-section ${className||''}`}>{!hideTitle&&heading}<div className="ds-group glass--flat">{children}</div></section>
}
const More=({onClick,children}:{onClick:()=>void;children:ReactNode})=><Row label={children} icon={<ArrowRight size={17}/>} onClick={onClick}/>;

function Inbox({c,count,caption,items,moreWork,morePending}:{c:Ctx;count:number;caption:string;items:Item[];moreWork:boolean;morePending:boolean}){
 return <Group title="需要關注" count={count} caption={caption} className="work-inbox">
  {items.map(i=><Row key={i.key} icon={i.icon} label={i.title} detail={i.detail} onClick={i.onClick} value={<span className="dh-attention">{i.blocked&&<Badge tone="critical">受阻</Badge>}{i.late!=null?<Badge tone="critical">逾期 {i.late} 天</Badge>:i.today?<Badge tone="warning">當日到期</Badge>:!i.blocked&&<ChevronRight size={17}/>}</span>}/>)}
  {!items.length&&<Row icon={<CircleCheck size={20}/>} label="資料日期內沒有到期或待審工作" detail="其他排定任務可在「我的工作」查看。"/>}
  {moreWork&&<More onClick={()=>c.go({view:'work',tab:'all'})}>查看全部工作</More>}{morePending&&<More onClick={()=>c.go({view:'approvals'})}>查看全部待審申請</More>}
 </Group>
}
const taskItem=(c:Ctx,key:string,title:string,detail:string,due:string|null,go:()=>void):Item=>{const late=!!due&&due.slice(0,10)<c.w.as_of.slice(0,10);return{key,title,detail,late:late?elapsed(due,c.w.as_of):undefined,today:!!due&&!late&&due.slice(0,10)===c.w.as_of.slice(0,10),icon:<Clock3 size={20}/>,onClick:go}};
const approvalItem=(c:Ctx,a:{id:string;title:string;type:string;project_id:string}):Item=>({key:a.id,title:a.title,detail:`${a.type==='change'?'設計變更':'期限展延'} · 等待確認`,icon:<GitBranch size={20}/>,onClick:()=>c.go({view:'project',project:a.project_id,tab:'approvals'})});

function Portfolio({c,formal,rows}:{c:Ctx;formal:Project[];rows:{p:Project;stage:string;percent:number}[]}){
 return <Group title="案件進度" caption="正式案件">
  {rows.map(({p,stage,percent})=><div key={p.id} className="project-preview-row"><Row href={`#view=project&project=${encodeURIComponent(p.id)}`} label={p.name} detail={`${p.code} · ${p.client} · ${stage}`} value={<span className="dh-progress"><strong>{percent}<small>%</small></strong><Progress value={percent} label={`${p.code} 任務進度`}/></span>}/></div>)}
  {!rows.length&&<Empty title="尚無正式案件" detail="待成案資料會分開保留，確認成案後再進入此清單。"/>}
  <More onClick={()=>c.go({view:'projects'})}>{`查看全部 ${formal.length} 案`}</More>
 </Group>
}

function Aside({c,formal,intakes,daily,activity}:{c:Ctx;formal:number;intakes:number;daily:ReactNode;activity:ReactNode}){
 return <aside className="today-aside">
  <Group title="案件分流" className="dh-totals" hideTitle><Row href="#view=projects&tab=formal" label="正式案件" detail="依工程確認單建立" value={formal}/><Row href="#view=projects&tab=intake" label="待確認接案" detail="尚未列入正式案件" value={intakes}/></Group>
  <Group title="當日日報" className="today-daily">{daily}{unmatchedDaily(c.w)>0&&<Row label={`${num(unmatchedDaily(c.w))} 筆日報待配對`} onClick={()=>c.go({view:'admin',tab:'daily'})} value="前往核對"/>}</Group>
  {activity}
 </aside>
}

// Zero counts are noise in a caption; an all-clear reads better as nothing at all.
const countLine=(parts:[string,number][])=>parts.filter(([,n])=>n>0).map(([l,n])=>`${l} ${n}`).join(' · ');

const Head=({c,children}:{c:Ctx;children:ReactNode})=><Page eyebrow={`${date(c.w.as_of)} · 資料日期`} title="工作總覽" subtitle="先掌握待處理工作，再查看案件進度。" actions={<><Button onClick={()=>c.go({view:'schedule'})}><CalendarDays size={16}/>查看排程</Button></>}>{children}</Page>;

export function Dashboard({c}:{c:Ctx}){
 // Home counts only the viewer's executable work on cases that are not paused (executableTasks.ts); source deadlines elsewhere stay visible on the Company view.
 const all=allTasks(c.w);const assigned=all.filter(r=>isHomeAssigned(r.t,c.w,c.s.user?.id||'')&&active(r.t));
 const rows=assigned.filter(r=>isHomeExecutable(r.t,r.p,c.w.as_of)&&!taskReadiness(r,c)&&!taskExecutionReason(r,c)&&!futureStart(r,c.w.as_of));const overdue=rows.filter(r=>isHomeLate(r.t,c.w.as_of));const pending=c.w.approvals.filter(a=>a.status==='pending');const dueToday=rows.filter(r=>isHomeDueToday(r.t,c.w.as_of));
 const waiting=assigned.flatMap(r=>{const kind=waitingKind(r,c);return kind?[{task_id:r.t.id,project_id:r.p.id,project_code:r.p.code,node_id:r.n.id,title:r.t.title,reason:waitingReason(r,c,kind),kind,original_due_date:r.t.original_due_date,due_date:r.t.due_date}]:[]});
 const formal=c.w.projects.filter(p=>p.case_type!=='intake');const intakes=c.w.projects.filter(p=>p.case_type==='intake');
 const late=(p:Project)=>p.nodes.flatMap(n=>n.tasks).filter(t=>isLate(t,c.w.as_of)).length;
 const focus=[...formal].sort((a,b)=>late(b)-late(a)).slice(0,5);
 const blocked=rows.filter(r=>operationallyBlocked(r));const attention=uniqueRows([...overdue,...blocked,...dueToday]);
 const tasks=uniqueRows([...overdue.slice(0,2),...blocked.slice(0,2),...dueToday,...overdue.slice(2),...blocked.slice(2)]).slice(0,5);const reports=c.w.projects.flatMap(p=>(p.daily_reports||[]).map(r=>({...r,p}))).filter(r=>r.date===c.w.as_of.slice(0,10));
 const items=[...tasks.map(r=>({...taskItem(c,r.t.id,r.t.title,`${r.p.code} · ${r.n.name} · ${nameOf(c.w,r.t.owner_id)}`,r.t.due_date,()=>openTask(c,r)),blocked:operationallyBlocked(r)})),...pending.slice(0,2).map(a=>approvalItem(c,a))];
 return <Head c={c}><div className="today-layout"><div className="today-main"><NextAction c={c} rows={assigned}/>
  <Inbox c={c} count={attention.length+pending.length} caption={countLine([['本人可執行逾期',overdue.length],['當日到期',dueToday.length],['受阻',blocked.length]])} items={items} moreWork={attention.length>5} morePending={pending.length>2}/>
  <WaitingWork c={c} items={waiting}/>
  <Portfolio c={c} formal={formal} rows={focus.map(p=>({p,percent:progress(p),stage:p.nodes.filter(n=>['in_progress','paused'].includes(n.status)).map(n=>NODE_NAMES[n.key]||n.name).join('、')||STATUS[p.status]||p.status}))}/></div>
  <Aside c={c} formal={formal.length} intakes={intakes.length} activity={<section className="today-activity ds-section"><h2>近期活動</h2><div className="ds-group glass--flat"><EventList c={c} limit={3}/></div></section>} daily={<>{reports.slice(0,3).map(r=><Row key={r.id} label={r.case_code} detail={`${r.department} · ${r.person}`} onClick={()=>c.go({view:'project',project:r.p.id,tab:'daily'})}/>)}{!reports.length&&<Row label={c.s.mode==='lark'&&(c.w.source_status.status!=='ready'||unmatchedDaily(c.w)>0)?'日報來源待核對，尚無已配對紀錄':'資料日期內尚無已配對日報'}/>}</>}/></div></Head>
}
export function ShellDashboard({c}:{c:Ctx}){
 // Built from the shell response only: counts, the server's needs-attention list and project cards. No task, node or event scan.
 const counts=c.w.counts||{approvals_pending:0,daily_unmatched:0,my_overdue_tasks:0,my_active_tasks:0};const attention=c.w.attention||[];const pending=c.w.pending_approvals||[];const overdue=counts.overdue_tasks??0,dueToday=counts.due_today_tasks??0;
 const blocked=attention.filter(a=>['paused','blocked'].includes(a.status));
 const formal=c.w.projects.filter(p=>p.case_type!=='intake');const intakes=c.w.projects.filter(p=>p.case_type==='intake');
 const focus=[...formal].sort((a,b)=>(b.overdue_tasks??0)-(a.overdue_tasks??0)).slice(0,5);const percent=(p:Project)=>p.progress?.total_nodes?Math.round(p.progress.completed_nodes/p.progress.total_nodes*100):0;
 const items=[...attention.slice(0,5).map(a=>({...taskItem(c,a.task_id,a.title||'未命名任務',`${a.project_code} · ${a.node_name||NODE_NAMES[a.node_key]||a.node_key} · ${nameOf(c.w,a.assignee_id)}`,a.due_date,()=>c.go({view:'project',project:a.project_id,node:a.node_id,task:a.task_id,tab:'flow'})),blocked:['paused','blocked'].includes(a.status)})),...pending.map(a=>approvalItem(c,a))];
 const waiting=(c.w as typeof c.w&{home_waiting?:WaitingItem[]}).home_waiting||[];
 return <Head c={c}><div className="today-layout"><div className="today-main">
  <section className="dh-hero" aria-label="接續我的工作"><p className="dh-kicker">接續我的工作 · {counts.my_active_tasks} 項待處理</p><h2>從我的工作接續下一項任務</h2><p>檢視指派給你的任務，確認作業條件後開始。</p><Button variant="primary" onClick={()=>c.go({view:'work'})}>我的工作<ArrowRight size={17}/></Button></section>
  <Inbox c={c} count={overdue+dueToday+counts.approvals_pending} caption={[countLine([['本人可執行逾期',overdue],['當日到期',dueToday]]),blocked.length?`受阻 ${blocked.length}（已載入）`:''].filter(Boolean).join(' · ')} items={items} moreWork={overdue+dueToday>attention.slice(0,5).length} morePending={counts.approvals_pending>pending.length}/>
  <WaitingWork c={c} items={waiting} counts={c.w.home_waiting_counts}/>
  <Portfolio c={c} formal={formal} rows={focus.map(p=>({p,percent:percent(p),stage:STATUS[p.execution_status||p.status]||p.status}))}/></div>
  <Aside c={c} formal={formal.length} intakes={intakes.length} activity={<ShellActivity c={c}/>} daily={<Row label="日報請至各案件的「日報」頁查看"/>}/></div></Head>
}
function ShellActivity({c}:{c:Ctx}){
 const[open,setOpen]=useState(false);
 return <section className="today-activity ds-section"><h2>近期活動</h2><div className="ds-group glass--flat">{open?<FullWorkspaceGate c={c}>{fc=><EventList c={fc} limit={3}/>}</FullWorkspaceGate>:<Row label={<span>載入近期活動</span>} onClick={()=>setOpen(true)}/>}</div></section>
}
