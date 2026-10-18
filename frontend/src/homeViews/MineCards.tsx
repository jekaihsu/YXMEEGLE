import type {Ctx} from '../appCommon';
import type {HomeCardId} from '../homeLayout';
import type {PanelRead} from '../useHomePanels';
import {Card,WorkCard} from '../homeCards';
import {DeadlineStrip} from '../homeCharts';
import {dayOffset,Kpis,panelCount,PanelNote} from './shared';
export function MineCard({id,c,today,assigned,confirmation}:{id:HomeCardId;c:Ctx;today:string;assigned:PanelRead;confirmation:PanelRead}){
 if(id==='work'||id==='confirmation')return <WorkCard c={c} id={id} panel={id==='work'?'assigned':'confirmation'} today={today} read={id==='work'?assigned:confirmation}/>;
 if(id==='kpi'){
  const weekday=new Date(`${today}T00:00:00Z`).getUTCDay();
  const weekStart=dayOffset(today,-((weekday+6)%7));
  const weekEnd=dayOffset(today,weekday===0?0:7-weekday);
  return <Card id={id} subtitle="依已讀取的個人清單統計" href="#view=work"><Kpis values={[
   {label:'逾期',value:panelCount(assigned,item=>item.overdue)},
   {label:'今天到期',value:panelCount(assigned,item=>item.due_today)},
   {label:'本週到期',value:panelCount(assigned,item=>!!item.deadline&&item.deadline.slice(0,10)>=weekStart&&item.deadline.slice(0,10)<=weekEnd)},
   {label:'待我確認',value:panelCount(confirmation,()=>true)},
  ]}/><PanelNote read={assigned} also={confirmation}/></Card>;
 }
 if(id==='deadlines')return <Card id={id} subtitle="已載入工作，依期限日期計算" href="#view=schedule">
  {assigned.body&&assigned.body.readState!=='disabled'&&<DeadlineStrip days={Array.from({length:7},(_,i)=>{const day=dayOffset(today,i);return {day,count:(assigned.body?.items||[]).filter(item=>item.deadline?.slice(0,10)===day).length}})}/>}<PanelNote read={assigned}/>
  {!assigned.body&&<p className="home-source-note">資料尚未完整，期限分布尚待讀取。</p>}
 </Card>;
 return null;
}
