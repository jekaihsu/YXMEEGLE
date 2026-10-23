import type {Ctx} from '../appCommon';
import type {HomeCardId} from '../homeLayout';
import type {PanelRead} from '../useHomePanels';
import {workSource,sourceCount} from '../homeWorkSource';
import {Card,WorkCard} from '../homeCards';
import {DeadlineStrip} from '../homeCharts';
import {dayOffset,Kpis} from './shared';
export function MineCard({id,c,today,assigned,confirmation}:{id:HomeCardId;c:Ctx;today:string;assigned:PanelRead;confirmation:PanelRead}){
 if(id==='work'||id==='confirmation')return <WorkCard c={c} id={id} panel={id==='work'?'assigned':'confirmation'} today={today} read={id==='work'?assigned:confirmation}/>;
 if(id==='kpi'){
  const weekday=new Date(`${today}T00:00:00Z`).getUTCDay();
  const weekStart=dayOffset(today,-((weekday+6)%7));
  const weekEnd=dayOffset(today,weekday===0?0:7-weekday);
  const work=workSource(c,'assigned',today,assigned),confirm=workSource(c,'confirmation',today,confirmation);
  return <Kpis values={[
   {label:'逾期',href:'#view=work',value:sourceCount(work,item=>item.overdue)},
   {label:'今天到期',href:'#view=work',value:sourceCount(work,item=>item.due_today)},
   {label:'本週到期',href:'#view=work',value:sourceCount(work,item=>!!item.deadline&&item.deadline.slice(0,10)>=weekStart&&item.deadline.slice(0,10)<=weekEnd)},
   {label:'待我確認',href:'#view=work&tab=confirmation',value:sourceCount(confirm,()=>true)},
  ]}/>;
 }
 if(id==='deadlines'){
  const source=workSource(c,'assigned',today,assigned);
  return <Card id={id} compact={!source} subtitle="已載入工作，依期限日期計算" href="#view=projects">
   {source?<><DeadlineStrip days={Array.from({length:7},(_,i)=>{const day=dayOffset(today,i);return {day,count:source.items.filter(item=>item.deadline?.slice(0,10)===day).length}})}/>{!source.complete&&<p className="home-source-note">僅涵蓋已載入的期限預覽。</p>}</>:<p className="home-source-note">{assigned.pending?'期限分布讀取中…':assigned.error||'期限來源尚未提供。'}</p>}
  </Card>;
 }
 return null;
}
