import {useState, type ReactNode} from 'react';
import {ArrowRight, CalendarDays, ChevronRight, CircleCheck, Clock3, GitBranch} from 'lucide-react';
import {type Project} from './types';
import {Ctx,TaskRow,active,isTaskActor,taskReadiness,openGuidedTask,allTasks,isLate,date,openTask,nameOf,elapsed,NODE_NAMES,STATUS,progress,Empty,unmatchedDaily,num,EventList,FullWorkspaceGate} from './appCommon';
import {Badge,Button,Page,Progress,Row} from './design';
import './DailyHome.css';

type Item={key:string;title:string;detail:string;late?:number;today?:boolean;blocked?:boolean;icon:ReactNode;onClick:()=>void};

const operationallyBlocked=(r:TaskRow)=>['paused','blocked'].includes(r.t.status)||(r.t.input_task_ids as string[]|undefined)?.some(id=>!r.p.nodes.some(n=>n.tasks.some(t=>t.id===id&&t.status==='completed'&&!!t.output)))===true;
const uniqueRows=(rows:TaskRow[])=>{const seen=new Set<string>();return rows.filter(r=>{if(seen.has(r.t.id))return false;seen.add(r.t.id);return true})};

export function NextAction({c,rows}:{c:Ctx;rows:TaskRow[]}){
 const owned=rows.filter(r=>active(r.t)&&isTaskActor(r.t,c)&&r.p.case_type!=='intake');
 const ordered=[...owned].sort((a,b)=>(a.t.status==='in_progress'?-1:0)-(b.t.status==='in_progress'?-1:0)||(a.t.due_date||'9999').localeCompare(b.t.due_date||'9999'));
 const next=ordered.find(r=>!taskReadiness(r,c));const blocked=ordered.filter(r=>operationallyBlocked(r));
 if(!owned.length)return null;
 return <section className="dh-hero" aria-label="接續我的工作"><p className="dh-kicker">接續我的工作 · {owned.length} 項待處理 · 可平行作業</p>{next?<><h2>{next.t.title}</h2><p>{next.p.code} · {next.n.name} · {next.t.status==='in_progress'?'作業中，接著補齊成果':'檢視內容後，由你確認開始'}</p><Button variant="primary" onClick={()=>openGuidedTask(c,next)}>{next.t.status==='in_progress'?'繼續此任務':'前往此任務'}<ArrowRight size={17}/></Button></>:<><h2>先補齊條件，再接續作業</h2><p>你負責的任務目前仍有待處理條件。</p></>}{blocked.slice(0,2).map(r=><button key={r.t.id} type="button" className="dh-blocked" onClick={()=>openGuidedTask(c,r)}><span><Badge tone="critical">受阻</Badge> {r.t.title}<small>{r.p.code} · {r.n.name} · 待解除作業條件</small></span><span>查看處理方式<ArrowRight size={14}/></span></button>)}</section>
}

function Group({title,count,caption,className,children}:{title:string;count?:number;caption?:string;className?:string;children:ReactNode}){
 return <section className={`ds-section ${className||''}`}><h2>{title}{count!=null&&<span className="heading-count">{count}</span>}{caption&&<small>{caption}</small>}</h2><div className="ds-group glass--flat">{children}</div></section>
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
  <Group title="案件分流" className="dh-totals"><Row href="#view=projects&tab=formal" label="正式案件" detail="依工程確認單建立" value={formal}/><Row href="#view=projects&tab=intake" label="待確認接案" detail="尚未列入正式案件" value={intakes}/></Group>
  <Group title="當日日報" className="today-daily">{daily}{unmatchedDaily(c.w)>0&&<Row label={`${num(unmatchedDaily(c.w))} 筆日報待配對`} onClick={()=>c.go({view:'admin',tab:'daily'})} value="前往核對"/>}<p>填報紀錄不等同任務完成，成果仍需確認交接。</p></Group>
  {activity}
 </aside>
}

const Head=({c,children}:{c:Ctx;children:ReactNode})=><Page eyebrow={`${date(c.w.as_of)} · 資料日期`} title="工作總覽" subtitle="先掌握待處理工作，再查看案件進度。" actions={<><Button onClick={()=>c.go({view:'schedule'})}><CalendarDays size={16}/>查看排程</Button><Button variant="primary" onClick={()=>c.go({view:'work'})}>我的工作<ArrowRight size={16}/></Button></>}>{children}</Page>;

export function Dashboard({c}:{c:Ctx}){
 const rows=allTasks(c.w);const overdue=rows.filter(r=>isLate(r.t,c.w.as_of));const pending=c.w.approvals.filter(a=>a.status==='pending');const dueToday=rows.filter(r=>active(r.t)&&r.t.due_date?.slice(0,10)===c.w.as_of.slice(0,10));
 const formal=c.w.projects.filter(p=>p.case_type!=='intake');const intakes=c.w.projects.filter(p=>p.case_type==='intake');
 const late=(p:Project)=>p.nodes.flatMap(n=>n.tasks).filter(t=>isLate(t,c.w.as_of)).length;
 const focus=[...formal].sort((a,b)=>late(b)-late(a)).slice(0,5);
 const blocked=rows.filter(r=>active(r.t)&&operationallyBlocked(r));const attention=uniqueRows([...overdue,...blocked,...dueToday]);
 const tasks=uniqueRows([...overdue.slice(0,2),...blocked.slice(0,2),...dueToday,...overdue.slice(2),...blocked.slice(2)]).slice(0,5);const reports=c.w.projects.flatMap(p=>p.daily_reports.map(r=>({...r,p}))).filter(r=>r.date===c.w.as_of.slice(0,10));
 const items=[...tasks.map(r=>({...taskItem(c,r.t.id,r.t.title,`${r.p.code} · ${r.n.name} · ${nameOf(c.w,r.t.owner_id)}`,r.t.due_date,()=>openTask(c,r)),blocked:operationallyBlocked(r)})),...pending.slice(0,2).map(a=>approvalItem(c,a))];
 return <Head c={c}><div className="today-layout"><div className="today-main"><NextAction c={c} rows={rows}/>
  <Inbox c={c} count={attention.length+pending.length} caption={`逾期 ${overdue.length} · 當日到期 ${dueToday.length} · 受阻 ${blocked.length}`} items={items} moreWork={attention.length>5} morePending={pending.length>2}/>
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
 return <Head c={c}><div className="today-layout"><div className="today-main">
  <section className="dh-hero" aria-label="接續我的工作"><p className="dh-kicker">接續我的工作 · {counts.my_active_tasks} 項待處理</p><h2>從我的工作接續下一項任務</h2><p>檢視指派給你的任務，確認作業條件後開始。</p><Button variant="primary" onClick={()=>c.go({view:'work'})}>我的工作<ArrowRight size={17}/></Button></section>
  <Inbox c={c} count={overdue+dueToday+counts.approvals_pending} caption={`逾期 ${overdue} · 當日到期 ${dueToday}${blocked.length?` · 受阻 ${blocked.length}（已載入）`:""}`} items={items} moreWork={overdue+dueToday>attention.slice(0,5).length} morePending={counts.approvals_pending>pending.length}/>
  <Portfolio c={c} formal={formal} rows={focus.map(p=>({p,percent:percent(p),stage:STATUS[p.execution_status||p.status]||p.status}))}/></div>
  <Aside c={c} formal={formal.length} intakes={intakes.length} activity={<ShellActivity c={c}/>} daily={<Row label="日報請至各案件的「日報」頁查看"/>}/></div></Head>
}
function ShellActivity({c}:{c:Ctx}){
 const[open,setOpen]=useState(false);
 return <section className="today-activity ds-section"><h2>近期活動</h2><div className="ds-group glass--flat">{open?<FullWorkspaceGate c={c}>{fc=><EventList c={fc} limit={3}/>}</FullWorkspaceGate>:<Row label={<span>載入近期活動</span>} onClick={()=>setOpen(true)}/>}</div></section>
}
