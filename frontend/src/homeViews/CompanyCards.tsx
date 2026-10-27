import type {Ctx} from '../appCommon';
import {Row} from '../design';
import {homeHref,type HomeCardId} from '../homeLayout';
import {Card,Message,WorkCard} from '../homeCards';
import type {PanelRead} from '../useHomePanels';
import {useHomeCompany} from '../useHomeCompany';
import {StatusChart,WorkloadChart} from '../homeCharts';
import {Kpis} from './shared';
export function CompanyCard({id,c,today,confirmation,read}:{id:HomeCardId;c:Ctx;today:string;confirmation:PanelRead;read:ReturnType<typeof useHomeCompany>}){
 if(id==='confirmation')return <WorkCard id={id} panel="confirmation" c={c} today={today} read={confirmation}/>;
 if(id==='links')return <Card id={id} subtitle="前往完整管理工具" href="#view=projects"><nav className="home-quick-links" aria-label="管理捷徑">{[['reports','PM 週報'],['overview','管理總覽'],['projects','案件總覽']].filter(([view])=>view!=='reports'||c.s.user?.role==='pm'||c.s.user?.role==='manager'||c.s.user?.role==='工務助理'||c.s.user?.department==='工務助理'||['郭倢瑛','朱雅琪','林瑩瑄'].includes(c.s.user?.name||'')||c.s.user?.capabilities?.includes('manage_sources')).map(([view,label])=><a key={view} href={homeHref({view})}>{label}</a>)}</nav></Card>;
 const data=read.data;
 if(!data)return null;
 let content;
 if(id==='kpi')return <Kpis note="本週到期總數尚未提供。" values={[
  {label:'進行中案件',href:'#view=projects',value:data.totals.execution_status_counts.in_progress??null},
  {label:'逾期任務',href:'#view=projects',value:data.totals.tasks_overdue},
  {label:'待確認',href:'#view=projects',value:data.totals.pending_local_reviews+data.totals.pending_native_reviews},
  {label:'本週到期',href:'#view=work',value:null},
 ]}/>;
 if(id==='groups')content=<WorkloadChart label="各組已完成、未逾期與逾期任務數" rows={[...data.groups].sort((a,b)=>b.tasks_total-a.tasks_total).slice(0,5).map(row=>({label:row.group||'未分組',completed:row.tasks_completed,open:Math.max(0,row.tasks_total-row.tasks_completed-row.tasks_overdue),overdue:row.tasks_overdue}))}/>;
 if(id==='statuses')content=<StatusChart counts={data.totals.execution_status_counts}/>;
 if(id==='cases'){
  const rows=data.cases.filter(row=>row.tasks_overdue>0||row.pending_local_reviews+row.pending_native_reviews>0);
  content=<>{rows.slice(0,5).map(row=><Row key={row.id} href={homeHref({view:'project',project:row.id})} label={row.name||row.code} detail={`${row.group} · 逾期 ${row.tasks_overdue} · 待確認 ${row.pending_local_reviews+row.pending_native_reviews}`}/>)}{!rows.length&&<Message>{data.complete?'目前沒有需留意的案件。':'已載入預覽中沒有需留意案件，資料尚未完整。'}</Message>}</>;
 }
 return <Card id={id} subtitle={`授權公司快照 · ${data.as_of}`} href='#view=projects'>{content}</Card>;
}
