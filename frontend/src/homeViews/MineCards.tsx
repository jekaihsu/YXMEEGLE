import type {Ctx} from '../appCommon';
import type {HomeCardId} from '../homeLayout';
import type {PanelRead} from '../useHomePanels';
import {workSource,sourceCount} from '../homeWorkSource';
import {Card,WorkCard} from '../homeCards';
import {Row} from '../design';
import {pinStorageKey,readPins} from '../projectsListModel';
import {DeadlineStrip} from '../homeCharts';
import {dayOffset,Kpis} from './shared';
const pinnedIds=(c:Ctx)=>{
 try{return new Set(readPins(window.localStorage,pinStorageKey(c.w.workspace_id||c.s.workspace_id||'default',c.s.user?.id||'anonymous')))}catch{return new Set<string>()}
};
const myCases=(c:Ctx)=>{
 const me=c.s.user?.id||'',pins=pinnedIds(c);
 const rank=(p:{id:string})=>pins.has(p.id)?0:1;
 return c.w.projects.filter(p=>p.case_type!=='intake'&&p.status!=='completed'&&(pins.has(p.id)||p.pm_id===me||p.sales_id===me||p.owner_id===me||(p.nodes??[]).some(n=>(n.tasks??[]).some(t=>t.owner_id===me)))).map((p,i)=>({p,i,pinned:pins.has(p.id)})).sort((a,b)=>rank(a.p)-rank(b.p)||a.i-b.i).map(({p,pinned})=>({...p,pinned}));
};
export function MineCard({id,c,today,assigned,confirmation}:{id:HomeCardId;c:Ctx;today:string;assigned:PanelRead;confirmation:PanelRead}){
 if(id==='work'||id==='confirmation')return <WorkCard c={c} id={id} panel={id==='work'?'assigned':'confirmation'} today={today} read={id==='work'?assigned:confirmation}/>;
 if(id==='mycases'){
  const rows=myCases(c);
  return <Card id={id} subtitle="你負責、釘選或有你任務的案件" href="#view=projects" action="開啟案件總覽">
   {rows.slice(0,8).map(p=><Row key={p.id} label={`${p.code} ${p.name}`} detail={p.pinned?`已釘選 · ${p.client}`:p.client} value={p.due_date?`期限 ${p.due_date.slice(0,10).replaceAll('-','/')}`:''} href={`#view=project&project=${p.id}`}/>)}
   {!rows.length&&<p className="home-source-note">目前沒有你負責、釘選或有你任務的案件。可在案件總覽釘選案件。</p>}
  </Card>;
 }
 if(id==='kpi'){
  const weekday=new Date(`${today}T00:00:00Z`).getUTCDay();
  const weekStart=dayOffset(today,-((weekday+6)%7));
  const weekEnd=dayOffset(today,weekday===0?0:7-weekday);
  const work=workSource(c,'assigned',today,assigned);
  return <Kpis values={[
   {label:'逾期',href:'#view=work',value:sourceCount(work,item=>item.overdue)},
   {label:'今天到期',href:'#view=work',value:sourceCount(work,item=>item.due_today)},
   {label:'本週到期',href:'#view=work',value:sourceCount(work,item=>!!item.deadline&&item.deadline.slice(0,10)>=weekStart&&item.deadline.slice(0,10)<=weekEnd)},
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
