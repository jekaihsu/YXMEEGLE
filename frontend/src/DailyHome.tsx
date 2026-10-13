import {useState, type ReactNode} from 'react';
import {ArrowRight, CalendarDays, ChevronRight, CircleCheck, Clock3, GitBranch} from 'lucide-react';
import {type HomeQueueItem,type HomeTaskDetail,type HomeWaitingItem,type Project} from './types';
import {Ctx,TaskRow,active,operationallyBlocked,isTaskActor,taskReadiness,openGuidedTask,allTasks,isLate,date,openTask,nameOf,elapsed,NODE_NAMES,STATUS,progress,Empty,unmatchedDaily,num,EventList,FullWorkspaceGate} from './appCommon';
import {Badge,Button,Page,Progress,Row} from './design';
import {isHomeAssigned,isHomeProxy,isHomeExecutable,isHomeLate,isHomeDueToday} from './executableTasks';
import './DailyHome.css';

type Item={key:string;title:string;detail:string;facts?:HomeTaskDetail|null;late?:number;today?:boolean;blocked?:boolean;icon:ReactNode;onClick:()=>void};

const uniqueRows=(rows:TaskRow[])=>{const seen=new Set<string>();return rows.filter(r=>{if(seen.has(r.t.id))return false;seen.add(r.t.id);return true})};

export function NextAction({c,rows}:{c:Ctx;rows:TaskRow[]}){
 const owned=rows.filter(r=>homeActionable(r,c));
 const ordered=[...owned].sort((a,b)=>(a.t.status==='in_progress'?-1:0)-(b.t.status==='in_progress'?-1:0)||(a.t.due_date||'9999').localeCompare(b.t.due_date||'9999'));
 const next=ordered[0];const blocked=ordered.filter(r=>operationallyBlocked(r));
 if(!owned.length)return null;
 return <section className="dh-hero" aria-label="接續我的工作"><p className="dh-kicker">接續我的工作 · {owned.length} 項待處理</p>{next?<><h2>{next.t.title}</h2><p>{next.p.code} · {next.n.name} · {next.t.status==='in_progress'?'作業中，接著補齊成果':'檢視內容後，由你確認開始'}</p><Button variant="primary" onClick={()=>openGuidedTask(c,next)}>{next.t.status==='in_progress'?'繼續此任務':'前往此任務'}<ArrowRight size={17}/></Button></>:<><h2>先補齊條件，再接續作業</h2><p>你負責的任務目前仍有待處理條件。</p></>}{blocked.slice(0,2).map(r=><button key={r.t.id} type="button" className="dh-blocked" onClick={()=>openGuidedTask(c,r)}><span><Badge tone="critical">受阻</Badge> {r.t.title}<small>{r.p.code} · {r.n.name} · 待解除作業條件</small></span><span>查看處理方式<ArrowRight size={14}/></span></button>)}</section>
}

type WaitingKind=HomeWaitingItem['kind'];
type WaitingItem=HomeWaitingItem;
const futureStart=(r:TaskRow,asOf:string)=>!!r.t.start_date&&r.t.start_date.slice(0,10)>asOf.slice(0,10);
const taskExecutionReason=(r:TaskRow,c:Ctx)=>{
 if(r.p.execution_allowed===false)return r.p.execution_readonly_reason||'案件執行歸屬待核定';
 const blockers=r.t.status==='pending'&&r.t.activation_blockers?.length?r.t.activation_blockers:r.t.execution_blockers;
 return blockers?.[0]||'';
};
const homeActionable=(r:TaskRow,c:Ctx)=>isHomeExecutable(r.t,r.p,c.w.as_of)&&(r.t.home_detail?true:!taskReadiness(r,c)&&!taskExecutionReason(r,c)&&!futureStart(r,c.w.as_of));
const waitingKind=(r:TaskRow,c:Ctx):WaitingKind|undefined=>{
 if(r.t.home_detail)return r.t.home_detail.kind||undefined;
 if(r.p.execution_status==='paused'||r.t.status==='paused')return 'paused';
 if(r.t.status==='rework')return 'correction';
 if(isHomeProxy(r.t,c.w,c.s.user?.id||''))return 'proxy';
 if(futureStart(r,c.w.as_of))return 'upcoming';
 if(r.t.can_execute!==true)return 'prerequisite';
 if(taskReadiness(r,c)||taskExecutionReason(r,c))return 'prerequisite';
 if(r.t.due_date&&r.t.due_date.slice(0,10)>c.w.as_of.slice(0,10))return 'upcoming';
 return undefined;
};
const waitingReason=(r:TaskRow,c:Ctx,kind:WaitingKind)=>{
 if(r.t.home_detail)return r.t.home_detail.reason||'目前原因待核對';
 if(kind==='paused')return '暫停原因待核對';
 if(kind==='correction')return '退回原因未記錄';
 if(kind==='proxy')return `代理 ${nameOf(c.w,r.t.owner_id)}；代理依據待核對`;
 if(kind==='upcoming')return r.t.start_date&&futureStart(r,c.w.as_of)?`排定 ${date(r.t.start_date)} 開始`:`預計 ${date(r.t.due_date)} 到期`;
 return taskExecutionReason(r,c)||(r.t.can_execute!==true?'指派與執行資格待核對':taskReadiness(r,c)||'待前置條件完成');
};
function HomeFacts({detail}:{detail:HomeTaskDetail}){
 const facts:string[]=[];
 if(detail.proxy){const p=detail.proxy;facts.push(`代理 ${p.principal_name}（${p.start_date} 至 ${p.end_date}；${p.basis||p.source||'依據待核對'}）`)}
 for(const reason of detail.blockers||[])if(reason!==detail.reason)facts.push(`作業條件：${reason}`);
 for(const upstream of detail.prerequisites||[])facts.push(`前置 ${upstream.title||upstream.task_id}：${upstream.owner_name||'負責人待核對'}；${upstream.ready?'成果已交付':upstream.missing?'任務資料待核對':upstream.output_present?'待確認完成':'成果尚未交付'}${upstream.source_batch_id?`；來源批次 ${upstream.source_batch_id}`:''}`);
 if(detail.correction)facts.push(detail.correction.reason?`退回原因：${detail.correction.reason}`:'退回原因未記錄', '修正範圍待核對');
 const risk=detail.risk;
 if(risk){
  facts.push(risk.original_due_date?`原始期限 ${date(risk.original_due_date)}`:'原始期限未提供');
  facts.push(risk.current_due_date?`現行期限 ${date(risk.current_due_date)}`:'現行期限未提供');
  facts.push(risk.estimated_due_date?`預估期限 ${date(risk.estimated_due_date)}`:'預估期限未提供');
  if(risk.overdue_calendar_days!=null)facts.push(risk.overdue_workdays!=null?`逾期 ${risk.overdue_workdays} 個工作日（${risk.overdue_calendar_days} 個曆日）`:`逾期 ${risk.overdue_calendar_days} 個曆日；工作日待核對`);
  if(detail.kind==='paused')facts.push('暫停計時規則待核定');
  if(risk.delivery_impact==='unavailable')facts.push('交付影響待核對');
 }
 if(!detail.delivery_links?.length)facts.push('本任務可核對的交付批次關聯未提供');
 for(const link of detail.delivery_links||[])facts.push(`來源批次 ${link.batch_id||'識別待核對'}（${link.status||'狀態待核對'}）`);
 return facts.length?<span className="dh-home-facts" style={{display:'block'}}>{facts.join(' · ')}</span>:null;
}

function QueueGroup({c,title,items}:{c:Ctx;title:string;items:HomeQueueItem[]}){
 const[expanded,setExpanded]=useState(false);const visible=expanded?items:items.slice(0,5);
 return <Group title={title} count={items.length} className="dh-personal-queue">
  {visible.map(i=>i.project_id?<Row key={i.id} label={i.title} detail={i.reason} onClick={()=>c.go({view:'project',project:i.project_id||undefined,node:i.node_id||undefined,task:i.task_id||undefined,tab:i.tab||'flow'})}/>:<Row key={i.id} label={i.title} detail={i.reason}/>)}
  {!items.length&&<Row label="目前沒有已核實的事項"/>}
  {items.length>visible.length&&<Row label={`顯示其餘 ${items.length-visible.length} 項`} onClick={()=>setExpanded(true)}/>}
 </Group>;
}
function HomeQueues({c}:{c:Ctx}){
 const[load,setLoad]=useState(false);
 if(c.w.scope==='shell')return <Group title="個人交接與確認" className="dh-personal-queue"><Row label="載入待我確認／我交辦事項" detail="開啟後讀取已核實的覆核與交辦紀錄" onClick={()=>setLoad(true)}/>{load&&<FullWorkspaceGate c={c}>{fc=><HomeQueues c={fc}/>}</FullWorkspaceGate>}</Group>;
 const queues=c.w.home_queues;
 if(!queues)return <Group title="個人交接與確認" className="dh-personal-queue"><Row label="個人確認與交辦資料尚未提供"/></Group>;
 return <><QueueGroup c={c} title="待我確認" items={queues.awaiting_confirmation||[]}/><QueueGroup c={c} title="我交辦的事項" items={queues.delegated_by_me||[]}/>{(queues.unavailable||[]).length>0&&<QueueGroup c={c} title="資料待核對" items={queues.unavailable}/>}</>;
}

const WAITING_LABELS:[WaitingKind,string][]=[['paused','暫停中的指派'],['correction','待修正'],['prerequisite','等待前置條件'],['upcoming','即將開始'],['proxy','代理工作']];
function WaitingWork({c,items,counts}:{c:Ctx;items:WaitingItem[];counts?:Partial<Record<WaitingKind,number>>}){
 return <>{WAITING_LABELS.map(([kind,label])=>{const rows=items.filter(i=>i.kind===kind),total=counts?.[kind]??rows.length;return total?<Group key={kind} title={label} count={total} className="dh-waiting">{rows.slice(0,5).map(i=><Row key={i.task_id} icon={<Clock3 size={20}/>} label={i.title} detail={<>{i.project_code} · {i.reason}{i.detail?<HomeFacts detail={i.detail}/>:kind==='paused'&&i.original_due_date?` · 原期限 ${date(i.original_due_date)}`:''}</>} onClick={()=>c.go({view:'project',project:i.project_id||undefined,node:i.node_id,task:i.task_id,tab:'flow'})}/>)}{total>Math.min(rows.length,5)&&<More onClick={()=>c.go({view:'work'})}>查看全部指派工作</More>}</Group>:null})}</>;
}

function Group({title,count,caption,className,hideTitle=false,children}:{title:string;count?:number;caption?:string;className?:string;hideTitle?:boolean;children:ReactNode}){
 const heading=<h2>{title}{count!=null&&<span className="heading-count">{count}</span>}{caption&&<small>{caption}</small>}</h2>;
 return <section aria-label={hideTitle?title:undefined} className={`ds-section ${className||''}`}>{!hideTitle&&heading}<div className="ds-group glass--flat">{children}</div></section>
}
const More=({onClick,children}:{onClick:()=>void;children:ReactNode})=><Row label={children} icon={<ArrowRight size={17}/>} onClick={onClick}/>;

function Inbox({c,count,caption,items,moreWork,morePending}:{c:Ctx;count:number;caption:string;items:Item[];moreWork:boolean;morePending:boolean}){
 return <Group title="需要關注" count={count} caption={caption} className="work-inbox">
  {items.map(i=><Row key={i.key} icon={i.icon} label={i.title} detail={<>{i.detail}{i.facts&&<HomeFacts detail={i.facts}/>}</>} onClick={i.onClick} value={<span className="dh-attention">{i.blocked&&<Badge tone="critical">受阻</Badge>}{i.late!=null?<Badge tone="critical">{i.facts?.risk.overdue_workdays!=null?`逾期 ${i.facts.risk.overdue_workdays} 個工作日`:`逾期 ${i.late} 個曆日`}</Badge>:i.today?<Badge tone="warning">當日到期</Badge>:!i.blocked&&<ChevronRight size={17}/>}</span>}/>)}
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
 const rows=assigned.filter(r=>homeActionable(r,c));const overdue=rows.filter(r=>isHomeLate(r.t,c.w.as_of));const pending=c.w.approvals.filter(a=>a.status==='pending');const dueToday=rows.filter(r=>isHomeDueToday(r.t,c.w.as_of));
 const waiting=assigned.flatMap(r=>{const kind=waitingKind(r,c);return kind?[{task_id:r.t.id,project_id:r.p.id,project_code:r.p.code,node_id:r.n.id,title:r.t.title,reason:waitingReason(r,c,kind),kind,original_due_date:r.t.original_due_date,due_date:r.t.due_date,detail:r.t.home_detail}]:[]});
 const formal=c.w.projects.filter(p=>p.case_type!=='intake');const intakes=c.w.projects.filter(p=>p.case_type==='intake');
 const late=(p:Project)=>p.nodes.flatMap(n=>n.tasks).filter(t=>isLate(t,c.w.as_of)).length;
 const focus=[...formal].sort((a,b)=>late(b)-late(a)).slice(0,5);
 const blocked=rows.filter(r=>operationallyBlocked(r));const attention=uniqueRows([...overdue,...blocked,...dueToday]);
 const tasks=uniqueRows([...overdue.slice(0,2),...blocked.slice(0,2),...dueToday,...overdue.slice(2),...blocked.slice(2)]).slice(0,5);const reports=c.w.projects.flatMap(p=>(p.daily_reports||[]).map(r=>({...r,p}))).filter(r=>r.date===c.w.as_of.slice(0,10));
 const items=[...tasks.map(r=>({...taskItem(c,r.t.id,r.t.title,`${r.p.code} · ${r.n.name} · ${nameOf(c.w,r.t.owner_id)}`,r.t.due_date,()=>openTask(c,r)),facts:r.t.home_detail,blocked:operationallyBlocked(r)})),...pending.slice(0,2).map(a=>approvalItem(c,a))];
 return <Head c={c}><div className="today-layout"><div className="today-main"><NextAction c={c} rows={assigned}/>
  <Inbox c={c} count={attention.length+pending.length} caption={countLine([['本人可執行逾期',overdue.length],['當日到期',dueToday.length],['受阻',blocked.length]])} items={items} moreWork={attention.length>5} morePending={pending.length>2}/>
  <WaitingWork c={c} items={waiting}/>
  <HomeQueues c={c}/>
  <Portfolio c={c} formal={formal} rows={focus.map(p=>({p,percent:progress(p),stage:p.nodes.filter(n=>['in_progress','paused'].includes(n.status)).map(n=>NODE_NAMES[n.key]||n.name).join('、')||STATUS[p.status]||p.status}))}/></div>
  <Aside c={c} formal={formal.length} intakes={intakes.length} activity={<section className="today-activity ds-section"><h2>近期活動</h2><div className="ds-group glass--flat"><EventList c={c} limit={3}/></div></section>} daily={<>{reports.slice(0,3).map(r=><Row key={r.id} label={r.case_code} detail={`${r.department} · ${r.person}`} onClick={()=>c.go({view:'project',project:r.p.id,tab:'daily'})}/>)}{!reports.length&&<Row label={c.s.mode==='lark'&&(c.w.source_status.status!=='ready'||unmatchedDaily(c.w)>0)?'日報來源待核對，尚無已配對紀錄':'資料日期內尚無已配對日報'}/>}</>}/></div></Head>
}
export function ShellDashboard({c}:{c:Ctx}){
 // Built from the shell response only: counts, the server's needs-attention list and project cards. No task, node or event scan.
 const counts=c.w.counts||{approvals_pending:0,daily_unmatched:0,my_overdue_tasks:0,my_active_tasks:0};const attention=c.w.attention||[];const pending=c.w.pending_approvals||[];const overdue=counts.overdue_tasks??0,dueToday=counts.due_today_tasks??0;
 const blocked=attention.filter(a=>['paused','blocked'].includes(a.status));
 const formal=c.w.projects.filter(p=>p.case_type!=='intake');const intakes=c.w.projects.filter(p=>p.case_type==='intake');
 const focus=[...formal].sort((a,b)=>(b.overdue_tasks??0)-(a.overdue_tasks??0)).slice(0,5);const percent=(p:Project)=>p.progress?.total_nodes?Math.round(p.progress.completed_nodes/p.progress.total_nodes*100):0;
 const items=[...attention.slice(0,5).map(a=>({...taskItem(c,a.task_id,a.title||'未命名任務',`${a.project_code} · ${a.node_name||NODE_NAMES[a.node_key]||a.node_key} · ${nameOf(c.w,a.assignee_id)}`,a.due_date,()=>c.go({view:'project',project:a.project_id,node:a.node_id,task:a.task_id,tab:'flow'})),facts:a.detail,blocked:['paused','blocked'].includes(a.status)})),...pending.map(a=>approvalItem(c,a))];
 const waiting=(c.w as typeof c.w&{home_waiting?:WaitingItem[]}).home_waiting||[];
 return <Head c={c}><div className="today-layout"><div className="today-main">
  <section className="dh-hero" aria-label="接續我的工作"><p className="dh-kicker">接續我的工作 · {counts.my_active_tasks} 項待處理</p><h2>從我的工作接續下一項任務</h2><p>檢視指派給你的任務，確認作業條件後開始。</p><Button variant="primary" onClick={()=>c.go({view:'work'})}>我的工作<ArrowRight size={17}/></Button></section>
  <Inbox c={c} count={overdue+dueToday+counts.approvals_pending} caption={[countLine([['本人可執行逾期',overdue],['當日到期',dueToday]]),blocked.length?`受阻 ${blocked.length}（已載入）`:''].filter(Boolean).join(' · ')} items={items} moreWork={overdue+dueToday>attention.slice(0,5).length} morePending={counts.approvals_pending>pending.length}/>
  <WaitingWork c={c} items={waiting} counts={c.w.home_waiting_counts}/>
  <HomeQueues c={c}/>
  <Portfolio c={c} formal={formal} rows={focus.map(p=>({p,percent:percent(p),stage:STATUS[p.execution_status||p.status]||p.status}))}/></div>
  <Aside c={c} formal={formal.length} intakes={intakes.length} activity={<ShellActivity c={c}/>} daily={<Row label="日報請至各案件的「日報」頁查看"/>}/></div></Head>
}
function ShellActivity({c}:{c:Ctx}){
 const[open,setOpen]=useState(false);
 return <section className="today-activity ds-section"><h2>近期活動</h2><div className="ds-group glass--flat">{open?<FullWorkspaceGate c={c}>{fc=><EventList c={fc} limit={3}/>}</FullWorkspaceGate>:<Row label={<span>載入近期活動</span>} onClick={()=>setOpen(true)}/>}</div></section>
}
