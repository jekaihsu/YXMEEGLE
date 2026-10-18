import {active,allTasks,type Ctx} from './appCommon';
import {isHomeAssigned} from './executableTasks';
import type {HomeItem,HomePanel,PanelRead} from './useHomePanels';

export type CountItem=Pick<HomeItem,'deadline'|'overdue'|'due_today'>;
export type CountSource={items:CountItem[];complete:boolean}|null;
export const usesDemoWork=(c:Ctx,read:PanelRead)=>c.s.mode==='demo'&&c.w.environment!=='production'&&(!read.body||read.body.readState==='disabled');
export const legacyWork=(c:Ctx)=>allTasks(c.w).filter(r=>active(r.t)&&isHomeAssigned(r.t,c.w,c.s.user?.id||'')).sort((a,b)=>(a.t.due_date||'9999').localeCompare(b.t.due_date||'9999'));
export const demoQueue=(c:Ctx,panel:HomePanel)=>panel==='confirmation'?c.w.home_queues?.awaiting_confirmation:panel==='delegated'?c.w.home_queues?.delegated_by_me:undefined;
export function panelSource(read:PanelRead):CountSource{
 const body=read.body;
 return body&&body.readState!=='disabled'?{items:body.items,complete:body.complete&&!body.has_more}:null;
}
export function workSource(c:Ctx,panel:HomePanel,today:string,read:PanelRead):CountSource{
 if(!usesDemoWork(c,read))return panelSource(read);
 if(panel==='assigned')return {items:legacyWork(c).map(({t})=>({deadline:t.due_date||null,overdue:!!t.due_date&&t.due_date.slice(0,10)<today,due_today:t.due_date?.slice(0,10)===today})),complete:c.w.scope!=='shell'};
 const queue=demoQueue(c,panel);
 return queue?{items:queue.map(()=>({deadline:null,overdue:false,due_today:false})),complete:c.w.scope!=='shell'}:null;
}
export function sourceCount(source:CountSource,predicate:(item:CountItem)=>boolean):number|string|null{
 if(!source)return null;
 const count=source.items.filter(predicate).length;
 return source.complete?count:`${count}+`;
}
