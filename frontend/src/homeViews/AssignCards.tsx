import type {Ctx} from '../appCommon';
import type {HomeCardId} from '../homeLayout';
import {useHomePanels,type PanelRead} from '../useHomePanels';
import {Card,Message,WorkCard} from '../homeCards';
import {WorkloadChart,type HomeBar} from '../homeCharts';
import {Kpis,panelCount,PanelNote,PanelRows} from './shared';

export function useAssignData(c:Ctx){
 return {team:useHomePanels(c,{panel:'assigned',scope:'team',limit:100}),review:useHomePanels(c,{panel:'confirmation',scope:'team',limit:100}),delegated:useHomePanels(c,{panel:'delegated',scope:'mine',limit:100})};
}
export function AssignCard({id,c,today,assigned,team,review,delegated}:{id:HomeCardId;c:Ctx;today:string;assigned:PanelRead;team:PanelRead;review:PanelRead;delegated:PanelRead}){
 const items=team.body?.items||[];
 if(id==='work')return <details className="home-personal"><summary>我的工作</summary><WorkCard c={c} id="work" panel="assigned" today={today} read={assigned}/></details>;
 if(id==='delegated')return <WorkCard c={c} id={id} panel="delegated" today={today} read={delegated}/>;
 if(id==='kpi'){
  return <Card id={id} subtitle="管理範圍內已載入的工作" href="#view=work&tab=assigned&ctx=scope%3Dteam"><Kpis values={[
   {label:'待分配',value:null},{label:'待審核',value:panelCount(review,()=>true)},
   {label:'逾期',value:panelCount(team,item=>item.overdue)},{label:'今日請假組員',value:null},
  ]}/><Message>資料尚未完整。來源未提供完整未指派節點與管理組員名冊；今日請假組員總數尚待核對。</Message><PanelNote read={team} also={review}/></Card>;
 }
 if(id==='allocation'){
  const rows=[...new Map([...items.filter(item=>item.assignment_state!=='assigned'),...(review.body?.items||[])].map(item=>[item.id,item])).values()];
  return <Card id={id} subtitle="待核對指派與待審核事項" href="#view=work&tab=assigned&ctx=scope%3Dteam"><PanelRows read={team} also={review} items={rows} today={today}/><Message>資料尚未完整。未指派節點目前不在團隊清單中，請開啟案件處理分配。</Message></Card>;
 }
 if(id==='workload'){
  const byPerson=new Map<string,HomeBar>();
  for(const item of items)for(const person of item.assignees){
   const row=byPerson.get(person.id)||{label:person.name,completed:0,open:0,overdue:0};
   if(item.overdue)row.overdue++;else row.open++;
   byPerson.set(person.id,row);
  }
  return <Card id={id} subtitle="每位受指派人員的未完成項目，多人工作分別計入" href="#view=work&tab=assigned&ctx=scope%3Dteam">{team.body&&team.body.readState!=='disabled'?<WorkloadChart label="組員未完成與逾期工作數" rows={[...byPerson.values()].sort((a,b)=>b.open+b.overdue-a.open-a.overdue).slice(0,5)}/>:<Message>{team.pending?'讀取中…':'組員工作量尚待核對。'}</Message>}<PanelNote read={team}/></Card>;
 }
 return null;
}
